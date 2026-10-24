"""Registro manual de evidencia: texto pegado o archivo suelto.

La ingesta por carpeta cubre el corpus documental de la organización, pero en
la práctica el auditor recibe evidencia por vías que no son un archivo del
expediente: un acta escaneada que llega por correo, un reporte exportado del
sistema de gestión, el acta de una reunión que sólo existe en papel.  Este
módulo permite incorporar esa evidencia **sin rehacer la ingesta completa**.

Dos decisiones de diseño que importan:

1. **La evidencia manual se materializa como archivo** en
   `data/evidencias_manuales/`.  Una evidencia que no existe en ningún
   archivo no es evidencia: el sistema tiene que poder citarla, volver a
   indexarla y mostrar su origen.  El texto pegado se guarda como `.txt`.

2. **El indexado es incremental.**  Se añaden los fragmentos del documento al
   corpus ya indexado; no se recrea la colección.  Esto permite registrar
   evidencia mientras se trabaja, sin los ~6 minutos de la ingesta completa.

La metadata (ámbito, tipo documental, organización, código) es **editable**:
una evidencia pegada a mano no tiene un nombre de archivo del que inferir el
ámbito, así que la decisión la toma quien la registra.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Extensiones que el extractor sabe leer.
EXTENSIONES_PERMITIDAS = (".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md")

# Tamaño máximo admitido para un archivo subido (30 MB): por encima de esto la
# interfaz debe rechazar el archivo en vez de dejar que reviente la memoria.
MAX_BYTES = 30 * 1024 * 1024

_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class ResultadoRegistro:
    """Salida del registro de una evidencia manual."""

    ok: bool
    documento: str = ""
    ruta: str = ""
    estado: str = ""
    chunks: int = 0
    ambitos: list[str] = field(default_factory=list)
    ambito_principal: str = ""
    tipo_documento: str = ""
    mensaje: str = ""
    avisos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "documento": self.documento,
            "ruta": self.ruta,
            "estado": self.estado,
            "chunks": self.chunks,
            "ambitos": self.ambitos,
            "ambito_principal": self.ambito_principal,
            "tipo_documento": self.tipo_documento,
            "mensaje": self.mensaje,
            "avisos": self.avisos,
        }


# --------------------------------------------------------------------------- #
# Utilidades de nombre
# --------------------------------------------------------------------------- #
def sanear_nombre(nombre: str, sufijo: str = "") -> str:
    """Limpia un nombre de archivo para poder guardarlo en disco.

    El nombre se trata como **texto plano**, no como ruta: un nombre como
    «Acta: revisión/2026» no debe truncarse a «2026» porque el `/` se
    interprete como separador de carpetas.  Los caracteres no válidos se
    sustituyen por `_`.

    Si se indica `sufijo` (p. ej. «.txt») y el nombre no lleva ya una
    extensión admitida, se le añade.
    """
    base = (nombre or "").strip() or "evidencia"
    base = _INVALIDOS.sub("_", base).strip() or "evidencia"
    if sufijo:
        ext = Path(base).suffix.lower()
        if ext not in EXTENSIONES_PERMITIDAS:
            base += sufijo
    return base


def nombre_disponible(pipeline, nombre: str) -> tuple[str, list[str]]:
    """Devuelve un nombre que no choque con el catálogo y los avisos generados.

    Hay dos casos distintos:

    * El nombre coincide con un documento **del corpus**: la matriz de
      trazabilidad mostraría dos fuentes indistinguibles, así que la copia
      manual se marca con el sufijo «(manual)».
    * El nombre coincide con **otra evidencia manual** ya registrada: en ese
      caso se trata de una actualización, no de un documento nuevo, y se
      conserva el nombre para que el registro siga siendo idempotente.
    """
    avisos: list[str] = []
    base = str(Path(pipeline.manuales_dir))
    registros = pipeline.cargar_catalogo().get("registros", [])
    homonimos = [r for r in registros if r.get("documento") == nombre]

    # Una evidencia manual anterior con el mismo nombre es una *actualización*:
    # se conserva el nombre para que el registro siga siendo idempotente.
    if any(base in str(r.get("ruta") or "") for r in homonimos):
        avisos.append(
            f"«{nombre}» ya estaba registrada como evidencia manual; "
            "se actualizó con el contenido nuevo."
        )
        return nombre, avisos

    if homonimos:
        candidato = f"{Path(nombre).stem} (manual){Path(nombre).suffix}"
        avisos.append(
            f"Ya existe un documento llamado «{nombre}» en el corpus; "
            f"la evidencia se registró como «{candidato}»."
        )
        return candidato, avisos

    return nombre, avisos


def _forzar_extension(nombre: str, ext: str) -> str:
    """Sustituye la extensión de un nombre por la indicada."""
    base = Path(nombre)
    try:
        return str(base.with_suffix(ext))
    except ValueError:
        return base.name + ext


def _ruta_manual(pipeline, nombre: str) -> Path:
    """Ruta destino de una evidencia manual dentro de la carpeta del pipeline."""
    base = Path(pipeline.manuales_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / nombre


def _escribir_y_registrar(pipeline, ruta: Path, escribir, **opciones) -> ResultadoRegistro:
    """Escribe el archivo, lo indexa y **deshace** la escritura si falla.

    Sin este cuidado, registrar una evidencia que no se puede indexar (por
    ejemplo, un texto demasiado corto) dejaría el archivo sobrescrito con
    contenido inválido mientras el índice sigue apuntando al fragmento
    anterior: la evidencia previa quedaría corrupta y sin que nadie lo note.

    Se guarda una copia de seguridad mientras se indexa y, si el indexado
    falla, se restaura: o bien vuelve el contenido anterior, o bien se borra
    el archivo nuevo para no dejar huérfanos.
    """
    respaldo = ruta.with_name(ruta.name + ".bak")
    habia = ruta.exists()
    if habia:
        try:
            shutil.copyfile(ruta, respaldo)
        except OSError:
            respaldo = ruta  # sin copia: no se restaurará, pero no se rompe nada

    try:
        escribir()
    except OSError as exc:
        _restaurar(ruta, respaldo, habia)
        return ResultadoRegistro(ok=False, mensaje=f"No se pudo guardar la evidencia: {exc}")

    resultado = _registrar_en_pipeline(pipeline, ruta, **opciones)
    if not resultado.ok:
        _restaurar(ruta, respaldo, habia)
    if respaldo != ruta:
        respaldo.unlink(missing_ok=True)
    return resultado


def _restaurar(ruta: Path, respaldo: Path, habia: bool) -> None:
    """Deja el archivo como estaba antes del intento fallido."""
    try:
        if habia and respaldo.exists():
            shutil.copyfile(respaldo, ruta)
        elif not habia:
            ruta.unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
def registrar_texto(
    pipeline,
    texto: str,
    nombre: str = "",
    *,
    ambitos: list[str] | None = None,
    ambito_principal: str | None = None,
    tipo_documento: str | None = None,
    organizacion: str | None = None,
    codigo: str | None = None,
) -> ResultadoRegistro:
    """Registra como evidencia un texto pegado por el usuario.

    El texto se guarda como `.txt` en `data/evidencias_manuales/` y se indexa
    de forma incremental junto al corpus ya procesado.
    """
    if not texto or not texto.strip():
        return ResultadoRegistro(ok=False, mensaje="El texto está vacío.")

    nombre = _forzar_extension(sanear_nombre(nombre or "Evidencia manual"), ".txt")
    nombre, avisos = nombre_disponible(pipeline, nombre)

    ruta = _ruta_manual(pipeline, nombre)
    # Se escribe con codificación UTF-8 explícita: en Windows el valor por
    # defecto puede ser cp1252 y perdería los acentos del texto pegado.
    return _escribir_y_registrar(
        pipeline,
        ruta,
        lambda: ruta.write_text(texto, encoding="utf-8"),
        ambitos=ambitos,
        ambito_principal=ambito_principal,
        tipo_documento=tipo_documento,
        organizacion=organizacion,
        codigo=codigo,
        avisos=avisos,
    )


def registrar_archivo(
    pipeline,
    origen: str | Path | bytes,
    nombre: str = "",
    *,
    ambitos: list[str] | None = None,
    ambito_principal: str | None = None,
    tipo_documento: str | None = None,
    organizacion: str | None = None,
    codigo: str | None = None,
    extension: str = "",
) -> ResultadoRegistro:
    """Registra como evidencia un archivo suelto (PDF, DOCX, XLSX, XLS, TXT).

    `origen` puede ser:

    * una ruta existente en disco (se copia a la carpeta de manuales), o
    * los bytes del archivo (caso de una subida HTTP, donde el archivo aún
      no está en disco).

    `extension` es la extensión original del archivo cuando el nombre elegido
    no la lleva (p. ej. «Acta de revisión» para un PDF subido).
    """
    avisos: list[str] = []

    if isinstance(origen, (bytes, bytearray)):
        contenido = bytes(origen)
        if len(contenido) > MAX_BYTES:
            return ResultadoRegistro(
                ok=False,
                mensaje=(
                    f"El archivo supera el límite de {MAX_BYTES // (1024 * 1024)} MB."
                ),
            )
        base = nombre or "evidencia"
        if extension and Path(base).suffix.lower() not in EXTENSIONES_PERMITIDAS:
            base += extension
        nombre = sanear_nombre(base)
        nombre, avisos = nombre_disponible(pipeline, nombre)
        ruta = _ruta_manual(pipeline, nombre)
        escribir = lambda: ruta.write_bytes(contenido)  # noqa: E731
    else:
        origen_path = Path(origen)
        if not origen_path.exists():
            return ResultadoRegistro(ok=False, mensaje=f"No existe el archivo: {origen_path}")
        if origen_path.suffix.lower() not in EXTENSIONES_PERMITIDAS:
            return ResultadoRegistro(
                ok=False,
                mensaje=(
                    f"Formato no admitido: '{origen_path.suffix}'. "
                    f"Se aceptan {', '.join(EXTENSIONES_PERMITIDAS)}."
                ),
            )
        nombre = sanear_nombre(nombre or origen_path.name, origen_path.suffix)
        nombre, avisos = nombre_disponible(pipeline, nombre)
        ruta = _ruta_manual(pipeline, nombre)

        def escribir() -> None:
            if origen_path.resolve() != ruta.resolve():
                shutil.copyfile(origen_path, ruta)

    return _escribir_y_registrar(
        pipeline,
        ruta,
        escribir,
        ambitos=ambitos,
        ambito_principal=ambito_principal,
        tipo_documento=tipo_documento,
        organizacion=organizacion,
        codigo=codigo,
        avisos=avisos,
    )


def _registrar_en_pipeline(
    pipeline,
    ruta: Path,
    *,
    ambitos: list[str] | None,
    ambito_principal: str | None,
    tipo_documento: str | None,
    organizacion: str | None,
    codigo: str | None,
    avisos: list[str],
) -> ResultadoRegistro:
    """Indexa el documento y lo inserta en el catálogo."""
    registro, chunks = pipeline.ingerir_documento(
        ruta,
        ambitos=ambitos,
        ambito_principal=ambito_principal,
        tipo_documento=tipo_documento,
        organizacion=organizacion,
        codigo=codigo,
        origen="manual",
    )
    if registro.estado == "error":
        return ResultadoRegistro(
            ok=False,
            documento=registro.documento,
            ruta=str(ruta),
            estado="error",
            mensaje=registro.notas[0] if registro.notas else "No se pudo procesar el documento.",
            avisos=avisos,
        )

    pipeline.actualizar_catalogo(registro)
    return ResultadoRegistro(
        ok=True,
        documento=registro.documento,
        ruta=str(ruta),
        estado="indexado",
        chunks=len(chunks),
        ambitos=registro.ambitos,
        ambito_principal=registro.ambito_principal,
        tipo_documento=registro.tipo_documento,
        mensaje=(
            f"«{registro.documento}» registrada: {len(chunks)} fragmentos indexados. "
            "Ya puede ser citada por el diagnóstico."
        ),
        avisos=avisos,
    )


# --------------------------------------------------------------------------- #
# Consulta y baja
# --------------------------------------------------------------------------- #
def listar_manuales(pipeline) -> list[dict]:
    """Lista las evidencias manuales registradas, con su estado en el índice."""
    catalogo = pipeline.cargar_catalogo()
    base = str(Path(pipeline.manuales_dir))
    salida: list[dict] = []
    for r in catalogo.get("registros", []):
        ruta = str(r.get("ruta") or "")
        if base not in ruta:
            continue
        salida.append(
            {
                "documento": r.get("documento"),
                "ruta": ruta,
                "tipo_documento": r.get("tipo_documento"),
                "ambitos": r.get("ambitos", []),
                "ambito_principal": r.get("ambito_principal"),
                "chunks": r.get("chunks", 0),
                "caracteres": r.get("caracteres", 0),
                "sha256": r.get("sha256", ""),
                "indexado": r.get("indexado", ""),
                "estado": r.get("estado", ""),
            }
        )
    return salida
