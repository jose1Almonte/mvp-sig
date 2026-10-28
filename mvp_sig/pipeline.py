"""Orquestador end-to-end del sistema de diagnóstico (equivalente al flujo n8n).

    ingesta -> indexacion -> recuperacion -> generacion -> verificacion -> informe

Cada paso deja traza en `Runtime.pasos_completados`, de modo que la corrida
sea auditable y reproducible (requisito de trazabilidad del anteproyecto).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from mvp_sig.diagnosis.engine import InformeDiagnostico, MotorDiagnostico
from mvp_sig.diagnosis.kpis import KPI, analizar_consistencia, construir_matriz_kpis
from mvp_sig.ingestion.catalog import (
    RegistroEvidencia,
    ahora_iso,
    clave_documento,
    clasificar_ambitos,
    id_documento,
    inferir_tipo_documento,
    metadatos_responsable,
    sha256_archivo,
)
from mvp_sig.ingestion.cleaner import Chunk, limpiar_documento, segmentar_bloque
from mvp_sig.ingestion.extractors import extract_documento
from mvp_sig.knowledge.requirements import Requisito, construir_corpus_requisitos, resumen_corpus
from mvp_sig.knowledge.vectorstore import VectorStore
from mvp_sig.llm.provider import LLMProvider, crear_proveedor
from mvp_sig.settings import PATHS, Runtime


@dataclass
class ResultadoIngesta:
    """Salida de la fase de pre-procesamiento e indexación de evidencias."""

    registros: list[RegistroEvidencia] = field(default_factory=list)
    chunks: int = 0
    documentos_ok: int = 0
    documentos_fallidos: int = 0
    omitidos: int = 0
    excluidos: int = 0
    segundos: float = 0.0
    advertencias: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "documentos_ok": self.documentos_ok,
            "documentos_fallidos": self.documentos_fallidos,
            "omitidos": self.omitidos,
            "excluidos": self.excluidos,
            "chunks": self.chunks,
            "segundos": round(self.segundos, 2),
            "advertencias": self.advertencias,
            "registros": [r.to_dict() for r in self.registros],
        }


class Pipeline:
    """Fachada única del sistema."""

    def __init__(
        self,
        store: VectorStore | None = None,
        llm: LLMProvider | None = None,
        runtime: Runtime | None = None,
        catalogo_dir: Path | None = None,
        manuales_dir: Path | None = None,
    ) -> None:
        self.runtime = runtime or Runtime()
        self.store = store or VectorStore()
        self.llm = llm or crear_proveedor()
        # El catálogo documental es un artefacto del corpus ingerido.  Es
        # parametrizable para que las pruebas no sobrescriban el catálogo real.
        self.catalogo_dir = Path(catalogo_dir) if catalogo_dir else PATHS.catalog
        # Lo mismo para la carpeta donde se materializa la evidencia manual.
        self.manuales_dir = Path(manuales_dir) if manuales_dir else PATHS.manuales

    # ------------------------------------------------------------------ #
    # Fase 1: ingesta e indexación de evidencias
    # ------------------------------------------------------------------ #
    def _procesar_documento(
        self,
        ruta: Path,
        *,
        motor_extraccion: str = "auto",
        ambitos_forzados: list[str] | None = None,
        ambito_principal_forzado: str | None = None,
        tipo_documento_forzado: str | None = None,
        organizacion_forzada: str | None = None,
        codigo_forzado: str | None = None,
        origen: str = "corpus",
    ) -> tuple[RegistroEvidencia, list[Chunk]]:
        """Extrae, limpia, segmenta y clasifica **un** documento.

        No toca la base vectorial ni el catálogo: eso es responsabilidad de
        quien llama.  Así el mismo código sirve para la ingesta completa (que
        recrea las colecciones) y para el registro manual de una evidencia
        (que sólo las actualiza).

        Los parámetros ``*_forzados`` permiten que la evidencia registrada a
        mano lleve metadatos decididos por el usuario (ámbito, tipo, código) en
        lugar de los inferidos del nombre del archivo.
        """
        extraido = extract_documento(ruta, motor=motor_extraccion)
        if not extraido.ok:
            registro = RegistroEvidencia(
                documento=ruta.name,
                ruta=str(ruta),
                tipo=extraido.tipo,
                tipo_documento=tipo_documento_forzado or inferir_tipo_documento(ruta.name),
                ambitos=list(ambitos_forzados or ["integral"]),
                ambito_principal=ambito_principal_forzado or "integral",
                paginas=extraido.paginas,
                bloques=0,
                chunks=0,
                caracteres=0,
                sha256="",
                modificado="",
                indexado=ahora_iso(),
                estado="error",
                notas=[extraido.error or "sin contenido"],
            )
            return registro, []

        bloques = limpiar_documento(extraido, es_norma=False)
        if not bloques:
            registro = RegistroEvidencia(
                documento=ruta.name,
                ruta=str(ruta),
                tipo=extraido.tipo,
                tipo_documento=tipo_documento_forzado or inferir_tipo_documento(ruta.name),
                ambitos=list(ambitos_forzados or ["integral"]),
                ambito_principal=ambito_principal_forzado or "integral",
                paginas=extraido.paginas,
                bloques=0,
                chunks=0,
                caracteres=0,
                sha256="",
                modificado="",
                indexado=ahora_iso(),
                estado="error",
                notas=["sin texto utilizable tras la limpieza (¿el texto es demasiado corto?)"],
            )
            return registro, []

        if ambitos_forzados:
            ambitos = list(ambitos_forzados)
            principal = ambito_principal_forzado or ambitos[0]
        else:
            muestra = " ".join(b.texto for b in bloques)[:6000]
            ambitos, principal = clasificar_ambitos(ruta.name, muestra)
            if ambito_principal_forzado:
                principal = ambito_principal_forzado

        tipo_doc = tipo_documento_forzado or inferir_tipo_documento(ruta.name)
        extras = metadatos_responsable(ruta.name)
        organizacion = (
            organizacion_forzada if organizacion_forzada is not None else extras["organizacion"]
        )
        codigo = codigo_forzado if codigo_forzado is not None else extras["codigo"]

        chunks_doc: list[Chunk] = []
        for bloque in bloques:
            nuevos = segmentar_bloque(
                bloque.texto,
                bloque,
                documento=ruta.name,
                ruta=str(ruta),
                tipo=extraido.tipo,
                ambitos=ambitos,
                ambito_principal=principal,
                offset=len(chunks_doc),
            )
            chunks_doc.extend(nuevos)

        for ch in chunks_doc:
            ch.metadatos.update(
                {
                    "tipo_documento": tipo_doc,
                    "organizacion": organizacion,
                    "codigo": codigo,
                    "origen": origen,
                }
            )

        registro = RegistroEvidencia(
            documento=ruta.name,
            ruta=str(ruta),
            tipo=extraido.tipo,
            tipo_documento=tipo_doc,
            ambitos=ambitos,
            ambito_principal=principal,
            paginas=extraido.paginas,
            bloques=len(bloques),
            chunks=len(chunks_doc),
            caracteres=sum(len(b.texto) for b in bloques),
            sha256=sha256_archivo(ruta),
            modificado=str(Path(ruta).stat().st_mtime),
            indexado=ahora_iso(),
            estado="indexado",
            notas=[],
            organizacion=organizacion,
            codigo=codigo,
        )
        return registro, chunks_doc

    def ingerir(
        self,
        raiz: str | Path,
        *,
        extensiones: tuple[str, ...] = (".pdf", ".docx", ".xlsx", ".xls"),
        limite: int | None = None,
        verbose: bool = True,
        lote_documentos: int = 25,
        motor_extraccion: str = "auto",
    ) -> ResultadoIngesta:
        raiz = Path(raiz)
        if not raiz.exists():
            raise FileNotFoundError(f"La ruta del corpus no existe: {raiz}")

        inicio = time.perf_counter()
        resultado = ResultadoIngesta()
        # La ingesta recrea la colección de evidencias, de modo que la evidencia
        # registrada a mano se perdería.  Se aparta antes de tocar nada para
        # poder reindexarla al final.
        manuales_previos = self._manuales_del_catalogo()
        archivos = sorted(
            p for p in raiz.rglob("*") if p.is_file() and p.suffix.lower() in extensiones
        )
        # Los documentos excluidos por el auditor no se reindexan: la decisión
        # persiste aunque se vuelva a procesar el corpus entero.
        if archivos:
            exclusiones = self.cargar_exclusiones()
            rutas_excluidas = {str(d.get("ruta") or "") for d in exclusiones}
            # También se compara la forma normalizada: el catálogo puede haber
            # guardado la ruta con separadores distintos a los que usa el
            # recorrido de archivos.
            rutas_excluidas |= {
                str(Path(r)) for r in rutas_excluidas if r
            }
            antes = len(archivos)
            archivos = [p for p in archivos if str(p) not in rutas_excluidas]
            resultado.excluidos = antes - len(archivos)
            if resultado.excluidos and verbose:
                print(
                    f"  -> {resultado.excluidos} documento(s) excluido(s) por el auditor; "
                    "no se indexan",
                    flush=True,
                )
        if limite:
            archivos = archivos[:limite]

        ids: list[str] = []
        documentos: list[str] = []
        metadatos: list[dict] = []

        # La colección se recrea una sola vez y se alimenta por lotes: así la
        # memoria resident no crece con el tamaño del corpus.
        self.store.coleccion(VectorStore.EVIDENCIAS, recrear=True)

        def volcar() -> int:
            """Vuelca a la base vectorial todo lo acumulado desde el último volcado.

            Se vuelca siempre el lote completo: un umbral mínimo dejaría
            documentos sin indexar siempre que el corpus terminase justo
            antes del siguiente límite de lote.
            """
            if not ids:
                return 0
            n = len(ids)
            try:
                self.store.upsertir(
                    VectorStore.EVIDENCIAS, ids, documentos, metadatos, verbose=False
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Fallo al indexar un lote de {n} fragmentos en la colección "
                    f"'{VectorStore.EVIDENCIAS}': {exc}"
                ) from exc
            ids.clear()
            documentos.clear()
            metadatos.clear()
            return n

        for i, ruta in enumerate(archivos, start=1):
            if verbose:
                print(f"  [{i}/{len(archivos)}] {ruta.name} [motor:{motor_extraccion}]", flush=True)
            registro, chunks_doc = self._procesar_documento(ruta, motor_extraccion=motor_extraccion)
            if registro.estado == "error":
                resultado.documentos_fallidos += 1
                resultado.omitidos += 1
                resultado.advertencias.append(f"{ruta.name}: {registro.notas[0]}")
                resultado.registros.append(registro)
                continue

            for ch in chunks_doc:
                ids.append(ch.id)
                documentos.append(ch.texto)
                metadatos.append(ch.to_metadata())

            resultado.documentos_ok += 1
            resultado.chunks += len(chunks_doc)
            resultado.registros.append(registro)

            if i % lote_documentos == 0:
                volcados = volcar()
                if verbose:
                    print(
                        f"  -> {self.store.contar(VectorStore.EVIDENCIAS)} fragmentos indexados",
                        flush=True,
                    )

        volcados = volcar()
        if verbose and volcados:
            print(
                f"  -> {self.store.contar(VectorStore.EVIDENCIAS)} fragmentos indexados",
                flush=True,
            )

        resultado.segundos = time.perf_counter() - inicio
        self.runtime.completar(
            "ingesta",
            f"{resultado.documentos_ok} documentos, {resultado.chunks} fragmentos, {resultado.segundos:.1f}s",
        )
        self.guardar_catalogo(resultado)
        self.reindexar_manuales(manuales_previos, verbose=verbose)
        return resultado

    def guardar_catalogo(self, resultado: ResultadoIngesta) -> Path:
        self.catalogo_dir.mkdir(parents=True, exist_ok=True)
        ruta = self.catalogo_dir / "catalogo_evidencias.json"
        ruta.write_text(
            json.dumps(resultado.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return ruta

    def cargar_catalogo(self) -> dict:
        ruta = self.catalogo_dir / "catalogo_evidencias.json"
        if not ruta.exists():
            return {}
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        # Compatibilidad con catálogos anteriores a los identificadores
        # estables: los documentos homónimos necesitan una clave y un id que
        # no dependan del nombre del archivo.
        for registro in datos.get("registros", []):
            if not registro.get("clave"):
                registro["clave"] = clave_documento(
                    str(registro.get("documento") or ""), str(registro.get("ruta") or "")
                )
            if not registro.get("id"):
                registro["id"] = id_documento(str(registro.get("ruta") or ""))
        return datos

    # ------------------------------------------------------------------ #
    # Registro incremental de una evidencia
    # ------------------------------------------------------------------ #
    def _manuales_del_catalogo(self) -> list[dict]:
        """Entradas del catálogo que corresponden a evidencia manual."""
        return [
            r
            for r in self.cargar_catalogo().get("registros", [])
            if self._es_manual(Path(str(r.get("ruta") or "")))
        ]

    def reindexar_manuales(self, registros: list[dict] | None = None, verbose: bool = False) -> int:
        """Vuelve a indexar la evidencia manual registrada previamente.

        La ingesta completa **recrea** la colección de evidencias, de modo que
        las evidencias registradas a mano se perderían.  Este método las
        recupera: recupera los documentos de la carpeta de manuales y los
        vuelve a indexar con sus metadatos, actualizando el catálogo.

        Devuelve el número de documentos reindexados.
        """
        if registros is None:
            registros = self._manuales_del_catalogo()
        reindexados = 0
        for r in registros:
            ruta = Path(str(r.get("ruta") or ""))
            if not ruta.is_file():
                if verbose:
                    print(f"  [manual] no se encuentra {ruta.name}; se omite", flush=True)
                continue
            if self.esta_excluido(ruta):
                if verbose:
                    print(f"  [manual] '{ruta.name}' está excluido; se omite", flush=True)
                continue
            registro, _ = self.ingerir_documento(
                ruta,
                ambitos=r.get("ambitos"),
                ambito_principal=r.get("ambito_principal"),
                tipo_documento=r.get("tipo_documento"),
                organizacion=r.get("organizacion") or None,
                codigo=r.get("codigo") or None,
                origen="manual",
            )
            if registro.estado == "error":
                if verbose:
                    print(f"  [manual] {ruta.name}: {registro.notas[0]}", flush=True)
                continue
            self.actualizar_catalogo(registro)
            reindexados += 1
            if verbose:
                print(
                    f"  [manual] reindexada '{registro.documento}' "
                    f"({registro.chunks} fragmentos)",
                    flush=True,
                )
        return reindexados

    def ingerir_documento(
        self,
        ruta: str | Path,
        *,
        ambitos: list[str] | None = None,
        ambito_principal: str | None = None,
        tipo_documento: str | None = None,
        organizacion: str | None = None,
        codigo: str | None = None,
        origen: str = "manual",
    ) -> tuple[RegistroEvidencia, list[Chunk]]:
        """Indexa **un** documento sin recrear la colección de evidencias.

        Es la contraparte incremental de `ingerir`: el corpus ya indexado se
        conserva intacto y sólo se añaden los fragmentos del documento
        indicado.  Si el documento ya estaba registrado, sus fragmentos
        anteriores se sustituyen (upsert), de modo que registrarlo dos veces
        no duplica evidencia.

        Devuelve el registro documental y los fragmentos generados.
        """
        ruta = Path(ruta)
        if not ruta.exists():
            raise FileNotFoundError(f"No existe el documento: {ruta}")

        registro, chunks = self._procesar_documento(
            ruta,
            ambitos_forzados=ambitos,
            ambito_principal_forzado=ambito_principal,
            tipo_documento_forzado=tipo_documento,
            organizacion_forzada=organizacion,
            codigo_forzado=codigo,
            origen=origen,
        )
        if registro.estado == "error":
            return registro, []

        # Se retiran los fragmentos previos del mismo documento antes de
        # insertar: si cambió el texto, no deben quedar restos del anterior.
        # El borrado se acota a la ruta exacta para no afectar a un documento
        # homónimo del corpus.
        self.store.borrar_por_documento(
            VectorStore.EVIDENCIAS, registro.documento, ruta=registro.ruta
        )
        self.store.upsertir(
            VectorStore.EVIDENCIAS,
            [c.id for c in chunks],
            [c.texto for c in chunks],
            [c.to_metadata() for c in chunks],
            verbose=False,
        )
        self.runtime.completar(
            "registro_evidencia", f"{registro.documento} ({registro.chunks} fragmentos)"
        )
        return registro, chunks

    def actualizar_catalogo(self, registro: RegistroEvidencia) -> Path:
        """Inserta o sustituye una entrada del catálogo documental.

        A diferencia de `guardar_catalogo`, que reescribe el catálogo entero
        con el resultado de una ingesta completa, este método **fusiona** una
        entrada: conserva el resto del catálogo y sólo reemplaza el registro
        del documento indicado.

        La fusión se hace por `clave` (nombre + resumen de la ruta) y no por
        nombre: el corpus contiene documentos homónimos y una acción sobre uno
        no puede afectar al otro.
        """
        self.catalogo_dir.mkdir(parents=True, exist_ok=True)
        ruta = self.catalogo_dir / "catalogo_evidencias.json"
        catalogo = self.cargar_catalogo()
        registros = [
            r for r in catalogo.get("registros", []) if r.get("clave") != registro.clave
        ]
        registros.append(registro.to_dict())

        ok = sum(1 for r in registros if r.get("estado") == "indexado")
        fallidos = sum(1 for r in registros if r.get("estado") != "indexado")
        catalogo.update(
            {
                "documentos_ok": ok,
                "documentos_fallidos": fallidos,
                "omitidos": fallidos,
                "chunks": sum(int(r.get("chunks") or 0) for r in registros),
                "registros": registros,
            }
        )
        ruta.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")
        return ruta

    def eliminar_evidencia(self, documento: str) -> dict:
        """Da de baja una evidencia: borra sus fragmentos, su catálogo y su archivo.

        Sólo se permite sobre documentos cuyo `ruta` esté dentro de la carpeta
        de evidencias manuales: el corpus de la organización es material de
        estudio y **sus archivos no se borran**.  Para retirar un documento del
        corpus del diagnóstico está `excluir_evidencia`, que lo saca del índice
        y de la catalogación pero conserva el archivo original.
        """
        catalogo = self.cargar_catalogo()
        registro, error = self._resolver(catalogo, documento)
        if registro is None:
            return {"ok": False, "motivo": error}

        ruta = Path(registro.get("ruta") or "")
        if not self._es_manual(ruta):
            return {
                "ok": False,
                "motivo": (
                    "'{d}' pertenece al corpus indexado: su archivo no se borra. "
                    "Use la exclusión para retirarlo del diagnóstico.".format(
                        d=registro.get("documento", documento)
                    )
                ),
            }

        # Se usa la ruta **tal cual** figura en el catálogo: `Path` normaliza
        # los separadores y en Windows convertiría «/corpus/x.docx» en
        # «\corpus\x.docx», que ya no casaría con los metadatos del fragmento.
        fragmentos = self.store.borrar_por_documento(
            VectorStore.EVIDENCIAS,
            str(registro.get("documento") or documento),
            ruta=str(registro.get("ruta") or ""),
        )
        self._quitar_del_catalogo(catalogo, registro)
        try:
            if ruta.is_file():
                ruta.unlink()
        except OSError:
            pass

        self.runtime.completar("baja_evidencia", f"{documento} ({fragmentos} fragmentos)")
        return {
            "ok": True,
            "documento": registro.get("documento", documento),
            "clave": registro.get("clave", ""),
            "fragmentos_eliminados": fragmentos,
            "mensaje": (
                f"'{registro.get('documento', documento)}' se dio de baja "
                f"({fragmentos} fragmentos eliminados)."
            ),
        }

    def _quitar_del_catalogo(self, catalogo: dict, registro: dict) -> None:
        """Elimina una entrada del catálogo y recalcula los contadores.

        La entrada se localiza por `id` y, si el catálogo es legado y no lo
        tiene, por `clave`; nunca por el nombre, porque el corpus contiene
        documentos homónimos que deben seguir distinguibles.
        """
        identificador = registro.get("id") or registro.get("clave")
        if identificador:
            registros = [
                r
                for r in catalogo.get("registros", [])
                if not (r.get("id") == identificador or r.get("clave") == identificador)
            ]
        else:
            nombre = registro.get("documento")
            registros = [r for r in catalogo.get("registros", []) if r.get("documento") != nombre]
        catalogo["registros"] = registros
        catalogo["documentos_ok"] = sum(1 for r in registros if r.get("estado") == "indexado")
        catalogo["documentos_fallidos"] = sum(
            1 for r in registros if r.get("estado") != "indexado"
        )
        catalogo["chunks"] = sum(int(r.get("chunks") or 0) for r in registros)
        self.catalogo_dir.mkdir(parents=True, exist_ok=True)
        ruta_cat = self.catalogo_dir / "catalogo_evidencias.json"
        ruta_cat.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")

    def _resolver(self, catalogo: dict | None = None, referencia: str = "") -> tuple[dict | None, str]:
        """Resuelve una referencia de documento a una entrada del catálogo.

        Acepta, en este orden de precisión:

        * el `id` corto (12 hexadecimales, seguro en una URL),
        * la `clave` legible (``nombre#resumen``),
        * el nombre del documento, si es único.

        Con el nombre puede haber más de una coincidencia, porque el corpus
        contiene 17 pares de documentos homónimos: en ese caso se devuelve un
        error con los identificadores candidatos en lugar de elegir uno
        arbitrariamente.
        """
        if catalogo is None:
            catalogo = self.cargar_catalogo()
        registros = catalogo.get("registros", [])
        if not referencia:
            return None, "No se indicó qué documento."

        for campo in ("id", "clave"):
            exacto = next((r for r in registros if r.get(campo) == referencia), None)
            if exacto is not None:
                return exacto, ""

        coincidencias = [r for r in registros if r.get("documento") == referencia]
        if len(coincidencias) == 1:
            return coincidencias[0], ""
        if len(coincidencias) > 1:
            candidatos = ", ".join(
                f"{r.get('documento', '')} [{r.get('id', '') or r.get('clave', '')}]"
                for r in coincidencias[:6]
            )
            return None, (
                f"Hay {len(coincidencias)} documentos llamados '{referencia}'. "
                f"Indique el id de uno de ellos: {candidatos}"
            )
        return None, f"'{referencia}' no está en el catálogo."

    # ------------------------------------------------------------------ #
    # Edición del corpus: exclusión, reindexado y metadatos
    # ------------------------------------------------------------------ #
    def cargar_exclusiones(self) -> list[dict]:
        """Documentos retirados del diagnóstico por decisión del auditor."""
        ruta = self.catalogo_dir / "exclusiones.json"
        if not ruta.exists():
            return []
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        documentos = datos.get("documentos", [])
        return documentos if isinstance(documentos, list) else []

    def guardar_exclusiones(self, documentos: list[dict]) -> Path:
        self.catalogo_dir.mkdir(parents=True, exist_ok=True)
        ruta = self.catalogo_dir / "exclusiones.json"
        ruta.write_text(
            json.dumps(
                {"documentos": documentos, "actualizado": ahora_iso()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ruta

    def exclusiones(self) -> list[dict]:
        """Lista de exclusiones con su metadato congelado."""
        return self.cargar_exclusiones()

    def esta_excluido(self, ruta: str | Path) -> bool:
        """True si la ruta concreta está excluida del diagnóstico.

        Se compara la ruta tal cual figura en la exclusión y también su forma
        normalizada, para que el cambio de separadores (`/` frente a `\\`) no
        haga perder una exclusión.
        """
        objetivo = str(ruta)
        for d in self.cargar_exclusiones():
            guardada = str(d.get("ruta") or "")
            if not guardada:
                continue
            if guardada == objetivo:
                return True
            if str(Path(guardada)) == str(Path(objetivo)):
                return True
        return False

    def inventario(self) -> list[dict]:
        """Inventario completo de evidencias: corpus indexado + manual + excluidas.

        Es la vista que consume la interfaz: una fila por documento, con su
        origen (`corpus` / `manual`), sus metadatos y su estado.
        """
        catalogo = self.cargar_catalogo()
        exclusiones = {str(d.get("ruta") or ""): d for d in self.cargar_exclusiones()}
        salida: list[dict] = []

        def fila(registro: dict, origen: str, excluido: bool) -> dict:
            ruta = str(registro.get("ruta") or "")
            return {
                "id": registro.get("id", ""),
                "clave": registro.get("clave", ""),
                "documento": registro.get("documento", ""),
                "ruta": ruta,
                "tipo": registro.get("tipo", ""),
                "tipo_documento": registro.get("tipo_documento", ""),
                "ambitos": registro.get("ambitos", []),
                "ambito_principal": registro.get("ambito_principal", ""),
                "organizacion": registro.get("organizacion", ""),
                "codigo": registro.get("codigo", ""),
                # Un documento excluido no aporta fragmentos al índice: el
                # recuento histórico se conserva aparte para no inflar los
                # totales del inventario.
                "chunks": 0 if excluido else int(registro.get("chunks") or 0),
                "chunks_historicos": int(registro.get("chunks") or 0),
                "caracteres": int(registro.get("caracteres") or 0),
                "estado": "excluido" if excluido else registro.get("estado", ""),
                "origen": origen,
                "indexado": registro.get("indexado", ""),
                "excluido": excluido,
                "motivo_exclusion": registro.get("motivo", "") if excluido else "",
            }

        for r in catalogo.get("registros", []):
            origen = "manual" if self._es_manual(Path(str(r.get("ruta") or ""))) else "corpus"
            salida.append(fila(r, origen, False))

        for exclusion in exclusiones.values():
            meta = dict(exclusion)
            meta.update(exclusion.get("metadatos") or {})
            ruta = str(exclusion.get("ruta") or "")
            if any(f["ruta"] == ruta for f in salida):
                continue
            origen = "manual" if self._es_manual(Path(ruta)) else "corpus"
            salida.append(fila(meta, origen, True))

        salida.sort(key=lambda f: (f["origen"], f["documento"].lower()))
        return salida

    def excluir_evidencia(self, referencia: str, motivo: str = "") -> dict:
        """Retira un documento del diagnóstico sin tocar su archivo.

        A diferencia de `eliminar_evidencia` (que borra también el archivo y
        sólo aplica a la evidencia manual), la **exclusión** sirve para
        cualquier documento: lo saca del índice vectorial y del catálogo, pero
        conserva el archivo original en su carpeta.

        La exclusión **persiste**: la ingesta completa la respeta, de modo que
        un documento excluido no vuelve a aparecer por el hecho de reindexar el
        corpus.  Esto es lo que hace que el corpus sea editable sin perder
        decisiones.
        """
        catalogo = self.cargar_catalogo()
        registro, error = self._resolver(catalogo, referencia)
        if registro is None:
            return {"ok": False, "motivo": error}

        documento = str(registro.get("documento") or referencia)
        # Ruta tal cual figura en el catálogo: es la misma cadena que se
        # guarda en los metadatos del fragmento y la que usa la ingesta para
        # reconocer un documento excluido.
        ruta_str = str(registro.get("ruta") or "")
        ruta = Path(ruta_str)

        fragmentos = self.store.borrar_por_documento(
            VectorStore.EVIDENCIAS, documento, ruta=ruta_str
        )
        self._quitar_del_catalogo(catalogo, registro)

        exclusiones = [
            d for d in self.cargar_exclusiones() if str(d.get("ruta") or "") != ruta_str
        ]
        exclusiones.append(
            {
                "id": registro.get("id", ""),
                "clave": registro.get("clave", ""),
                "documento": documento,
                "ruta": ruta_str,
                "excluido": ahora_iso(),
                "motivo": motivo or "Excluido desde la interfaz",
                "metadatos": {
                    "id": registro.get("id", ""),
                    "clave": registro.get("clave", ""),
                    "tipo": registro.get("tipo", ""),
                    "tipo_documento": registro.get("tipo_documento", ""),
                    "ambitos": registro.get("ambitos", []),
                    "ambito_principal": registro.get("ambito_principal", ""),
                    "organizacion": registro.get("organizacion", ""),
                    "codigo": registro.get("codigo", ""),
                    "chunks": registro.get("chunks", 0),
                    "caracteres": registro.get("caracteres", 0),
                    "sha256": registro.get("sha256", ""),
                    "indexado": registro.get("indexado", ""),
                },
            }
        )
        self.guardar_exclusiones(exclusiones)

        self.runtime.completar("exclusion_evidencia", f"{documento} ({fragmentos} fragmentos)")
        return {
            "ok": True,
            "documento": documento,
            "clave": registro.get("clave", ""),
            "fragmentos_eliminados": fragmentos,
            "mensaje": (
                f"'{documento}' quedó excluido del diagnóstico "
                f"({fragmentos} fragmentos retirados). El archivo se conserva."
            ),
        }

    def reincorporar_evidencia(self, referencia: str) -> dict:
        """Devuelve al diagnóstico un documento excluido.

        Lo reindexa con los metadatos que tenía cuando se excluyó, de modo que
        la clasificación que el auditor había corregido no se pierda.
        """
        exclusiones = self.cargar_exclusiones()
        por_id = next(
            (
                d
                for d in exclusiones
                if str(d.get("id") or "") == referencia
                or str(d.get("clave") or "") == referencia
            ),
            None,
        )
        coincidencia = por_id
        if coincidencia is None:
            por_nombre = [
                d for d in exclusiones if str(d.get("documento") or "") == referencia
            ]
            if len(por_nombre) == 1:
                coincidencia = por_nombre[0]
            elif len(por_nombre) > 1:
                candidatos = ", ".join(
                    f"{d.get('documento', '')} [{d.get('id', '')}]" for d in por_nombre[:6]
                )
                return {
                    "ok": False,
                    "motivo": (
                        f"Hay {len(por_nombre)} documentos excluidos llamados "
                        f"'{referencia}'. Indique el id de uno: {candidatos}"
                    ),
                }
        if coincidencia is None:
            return {"ok": False, "motivo": f"'{referencia}' no está excluido."}

        resto = [
            d
            for d in exclusiones
            if str(d.get("ruta") or "") != str(coincidencia.get("ruta") or "")
        ]
        self.guardar_exclusiones(resto)

        ruta = Path(str(coincidencia.get("ruta") or ""))
        if not ruta.is_file():
            return {
                "ok": True,
                "reindexado": False,
                "documento": coincidencia.get("documento", referencia),
                "mensaje": (
                    f"'{coincidencia.get('documento', referencia)}' ya no está excluido, "
                    f"pero su archivo no se encuentra: {ruta}. "
                    "Vuelve a indexarlo cuando el archivo esté disponible."
                ),
            }

        meta = coincidencia.get("metadatos") or {}
        registro, _ = self.ingerir_documento(
            ruta,
            ambitos=meta.get("ambitos"),
            ambito_principal=meta.get("ambito_principal"),
            tipo_documento=meta.get("tipo_documento"),
            organizacion=meta.get("organizacion") or None,
            codigo=meta.get("codigo") or None,
            origen="manual" if self._es_manual(ruta) else "corpus",
        )
        if registro.estado == "error":
            return {
                "ok": False,
                "motivo": (
                    f"No se pudo reindexar '{registro.documento}': "
                    f"{registro.notas[0] if registro.notas else 'error desconocido'}"
                ),
            }
        self.actualizar_catalogo(registro)
        return {
            "ok": True,
            "reindexado": True,
            "documento": registro.documento,
            "clave": registro.clave,
            "fragmentos": registro.chunks,
            "mensaje": (
                f"'{registro.documento}' volvió al diagnóstico "
                f"({registro.chunks} fragmentos indexados)."
            ),
        }

    def actualizar_metadatos(
        self,
        referencia: str,
        *,
        ambitos: list[str] | None = None,
        ambito_principal: str | None = None,
        tipo_documento: str | None = None,
        organizacion: str | None = None,
        codigo: str | None = None,
    ) -> dict:
        """Corrige la clasificación de un documento y lo reindexa.

        La clasificación automática (ámbito, tipo documental, responsable) se
        infiere del nombre del archivo y acierta a menudo; cuando falla, el
        auditor necesita corregirla **sin rehacer la ingesta completa**.  Este
        método reindexa un único documento con los metadatos indicados y deja
        el resto del corpus intacto.

        Los campos que no se indican conservan su valor actual.
        """
        catalogo = self.cargar_catalogo()
        registro, error = self._resolver(catalogo, referencia)
        if registro is None:
            return {"ok": False, "motivo": error}

        ruta = Path(str(registro.get("ruta") or ""))
        if not ruta.is_file():
            return {
                "ok": False,
                "motivo": f"No se encuentra el archivo de '{registro.get('documento')}': {ruta}",
            }

        ambitos_final = list(ambitos) if ambitos is not None else list(registro.get("ambitos") or [])
        principal_final = (
            ambito_principal if ambito_principal is not None else registro.get("ambito_principal")
        )
        if principal_final and ambitos_final and principal_final not in ambitos_final:
            ambitos_final = [principal_final, *ambitos_final]

        nuevo, _ = self.ingerir_documento(
            ruta,
            ambitos=ambitos_final or None,
            ambito_principal=principal_final or None,
            tipo_documento=(
                tipo_documento if tipo_documento is not None else registro.get("tipo_documento")
            ),
            organizacion=(
                organizacion if organizacion is not None else (registro.get("organizacion") or None)
            ),
            codigo=codigo if codigo is not None else (registro.get("codigo") or None),
            origen="manual" if self._es_manual(ruta) else "corpus",
        )
        if nuevo.estado == "error":
            return {
                "ok": False,
                "motivo": (
                    f"No se pudo reindexar '{nuevo.documento}': "
                    f"{nuevo.notas[0] if nuevo.notas else 'error desconocido'}"
                ),
            }
        self.actualizar_catalogo(nuevo)
        return {
            "ok": True,
            "documento": nuevo.documento,
            "clave": nuevo.clave,
            "fragmentos": nuevo.chunks,
            "metadatos": {
                "ambitos": nuevo.ambitos,
                "ambito_principal": nuevo.ambito_principal,
                "tipo_documento": nuevo.tipo_documento,
                "organizacion": nuevo.organizacion,
                "codigo": nuevo.codigo,
            },
            "mensaje": (
                f"'{nuevo.documento}' se actualizó y se reindexó "
                f"({nuevo.chunks} fragmentos)."
            ),
        }

    def reindexar_documento(self, referencia: str) -> dict:
        """Reindexa un documento desde su archivo conservando sus metadatos.

        Sirve para recoger los cambios hechos en el archivo original sin
        esperar a la ingesta completa.
        """
        return self.actualizar_metadatos(referencia)

    def _es_manual(self, ruta: Path) -> bool:
        """True si la ruta está dentro de la carpeta de evidencias manuales."""
        base = Path(self.manuales_dir)
        try:
            return Path(ruta).resolve().is_relative_to(base.resolve())
        except (AttributeError, OSError, ValueError):
            # Python < 3.9 o rutas indeterminadas: comparación por cadena.
            return str(base) in str(ruta)

    # ------------------------------------------------------------------ #
    # Fase 2: indexación del corpus normativo
    # ------------------------------------------------------------------ #
    def indexar_requisitos(
        self,
        normas: list[str] | None = None,
        *,
        solo_normativos: bool = True,
    ) -> list[Requisito]:
        """Indexa el catálogo de requisitos en la colección `iso_requisitos`.

        Por defecto sólo se indexan las unidades *exigibles* (las que encierran
        un "debe"): una NOTA, un ejemplo o una definición no generan una no
        conformidad, de modo que evaluarlos como si fueran requisitos
        invalidaría el diagnóstico.
        """
        requisitos = construir_corpus_requisitos(normas, solo_normativos=solo_normativos)
        ids = [r.id for r in requisitos]
        textos = [r.texto for r in requisitos]
        metas = [r.to_metadata() for r in requisitos]
        self.store.indexar(
            VectorStore.REQUISITOS, ids, textos, metas, recrear=True, verbose=False
        )
        self.runtime.completar("indexacion_requisitos", f"{len(requisitos)} requisitos")
        return requisitos

    def cargar_requisitos(
        self,
        normas: list[str] | None = None,
        *,
        solo_normativos: bool = True,
    ) -> list[Requisito]:
        """Recupera los requisitos desde la base vectorial (sin recomputar)."""
        filas = self.store.listar(VectorStore.REQUISITOS)
        if not filas:
            return construir_corpus_requisitos(normas, solo_normativos=solo_normativos)
        requisitos: list[Requisito] = []
        for f in filas:
            m = f["metadatos"]
            pagina = int(m.get("pagina", -1))
            tipo = m.get("tipo", "requisito")
            extra = {
                k: v
                for k, v in m.items()
                if k not in {"id", "norma", "ambito", "clausula", "tipo", "pagina", "fuente"}
            }
            extra["normativo"] = bool(m.get("normativo", tipo == "requisito"))
            requisitos.append(
                Requisito(
                    id=m.get("id", f["id"]),
                    norma=m.get("norma", "ISO9001"),
                    ambito=m.get("ambito", "calidad"),
                    clausula=m.get("clausula", "0"),
                    texto=f["texto"],
                    pagina=pagina if pagina > 0 else None,
                    fuente=m.get("fuente", ""),
                    tipo=tipo,
                    metadatos=extra,
                )
            )
        if normas:
            requisitos = [r for r in requisitos if r.norma in normas]
        if solo_normativos:
            requisitos = [r for r in requisitos if r.normativo]
        return requisitos

    # ------------------------------------------------------------------ #
    # Fase 3: diagnóstico
    # ------------------------------------------------------------------ #
    def diagnosticar(
        self,
        *,
        normas: list[str] | None = None,
        ambitos: list[str] | None = None,
        clausulas: list[str] | None = None,
        limite: int | None = None,
        top_k: int | None = None,
        organizacion: str = "Organización evaluada",
        contexto_extra: str = "",
        con_resumen: bool = True,
        proveedor: str | None = None,
        modelo: str | None = None,
        progreso=None,
        notificar_n8n: bool = False,
        sin_limite: bool = False,
    ) -> InformeDiagnostico:
        llm = self.llm
        if proveedor or modelo:
            llm = crear_proveedor(proveedor, modelo)

        requisitos = self.cargar_requisitos(normas)
        if ambitos:
            requisitos = [r for r in requisitos if r.ambito in ambitos]
        if clausulas:
            set_clausulas = set(clausulas)
            requisitos = [r for r in requisitos if r.clausula in set_clausulas]
        if limite and not sin_limite:
            requisitos = requisitos[:limite]

        motor = MotorDiagnostico(
            self.store, llm, top_k=top_k, organizacion=organizacion
        )
        self.runtime.completar("consulta_requisito", f"{len(requisitos)} requisitos seleccionados")
        informe = motor.diagnosticar(
            requisitos, contexto_extra=contexto_extra, con_resumen=con_resumen, progreso=progreso
        )
        self.runtime.completar("consolidacion_diagnostico", f"{len(informe.resultados)} veredictos")

        if notificar_n8n:
            self.notificar_n8n(informe)
        return informe

    # ------------------------------------------------------------------ #
    # Orquestador externo (n8n)
    # ------------------------------------------------------------------ #
    def notificar_n8n(self, informe) -> dict:
        """Publica el informe en el webhook de n8n, si hay uno configurado.

        La notificación es best-effort: si el orquestador no está disponible,
        el diagnóstico sigue siendo válido y sólo queda registrado el aviso.
        """
        from mvp_sig.integrations.n8n import notificar, webhook_configurado

        if not webhook_configurado():
            self.runtime.advertir(
                "N8N_WEBHOOK no está configurado: no se notificó al orquestador."
            )
            return {"enviado": False, "detalle": "webhook no configurado"}

        resultado = notificar(informe)
        if resultado.enviado:
            self.runtime.completar("notificacion_n8n", f"HTTP {resultado.codigo}")
        else:
            self.runtime.advertir(f"Notificación a n8n fallida: {resultado.detalle}")
        return resultado.to_dict()

    # ------------------------------------------------------------------ #
    # Fase 4: matriz de KPIs
    # ------------------------------------------------------------------ #
    def matriz_kpis(self, con_normativos: bool = True) -> tuple[list[KPI], dict]:
        requisitos = self.cargar_requisitos() if con_normativos else None
        kpis = construir_matriz_kpis(requisitos)
        analisis = analizar_consistencia(kpis)
        self.runtime.completar("matriz_kpis", f"{len(kpis)} indicadores")
        return kpis, analisis

    # ------------------------------------------------------------------ #
    # Estado
    # ------------------------------------------------------------------ #
    def estado(self) -> dict:
        return {
            "base_vectorial": {
                "requisitos": self.store.contar(VectorStore.REQUISITOS),
                "evidencias": self.store.contar(VectorStore.EVIDENCIAS),
                "embeddings": self.store.embeddings.nombre,
                "modelo_embeddings": getattr(self.store.embeddings, "modelo", "n/a"),
            },
            "llm": self.llm.info(),
            "catalogo": self.cargar_catalogo().get("documentos_ok", 0),
            "pasos": self.runtime.pasos_completados,
            "advertencias": self.runtime.warnings,
        }
