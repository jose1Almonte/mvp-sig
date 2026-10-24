"""Base de datos vectorial (ChromaDB persistente).

Dos colecciones con roles distintos:
  * ``iso_requisitos``  -> el catálogo de requisitos normativos (clave del diagnóstico).
  * ``evidencias``      -> los fragmentos de la documentación de la organización.

Ambas comparten el esquema de metadatos para permitir el filtrado por ámbito
y la trazabilidad cruzada.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Iterable, Sequence

from mvp_sig.knowledge.embeddings import EmbeddingProvider, obtener_embeddings
from mvp_sig.settings import PATHS


@dataclass
class FragmentoRecuperado:
    """Fragmento recuperado de la base vectorial con su puntaje de similitud."""

    id: str
    texto: str
    puntaje: float
    metadatos: dict
    coleccion: str


class VectorStore:
    """Envoltura sobre ChromaDB con dos colecciones."""

    REQUISITOS = "iso_requisitos"
    EVIDENCIAS = "evidencias"

    def __init__(
        self,
        ruta: str | None = None,
        embeddings: EmbeddingProvider | None = None,
        cliente=None,
    ) -> None:
        import chromadb

        PATHS.ensure()
        self.ruta = ruta or str(PATHS.chroma)
        self.embeddings = embeddings or obtener_embeddings()
        self._cliente = cliente or chromadb.PersistentClient(path=self.ruta)

    # -- colecciones ------------------------------------------------------ #
    def coleccion(self, nombre: str, recrear: bool = False):
        if recrear:
            try:
                self._cliente.delete_collection(nombre)
            except Exception:  # noqa: BLE001 - la colección puede no existir
                pass
        col = self._cliente.get_or_create_collection(
            name=nombre,
            metadata={"hnsw:space": "cosine"},
        )
        return col

    # -- indexación -------------------------------------------------------- #
    def indexar(
        self,
        nombre: str,
        ids: Sequence[str],
        documentos: Sequence[str],
        metadatos: Sequence[dict],
        *,
        recrear: bool = False,
        lote: int = 256,
        verbose: bool = True,
    ) -> int:
        """Indexa documentos (recalcula embeddings). Devuelve el total indexado."""
        if not ids:
            return 0
        col = self.coleccion(nombre, recrear=recrear)
        total = 0
        for i in range(0, len(ids), lote):
            trozo_ids = list(ids[i : i + lote])
            trozo_docs = list(documentos[i : i + lote])
            trozo_meta = list(metadatos[i : i + lote])
            vectores = self.embeddings.embed_documents(trozo_docs)
            # upsert: si el id existe, se reemplaza
            col.upsert(ids=trozo_ids, documents=trozo_docs, metadatas=trozo_meta, embeddings=vectores)
            total += len(trozo_ids)
            if verbose:
                print(f"    indexados {total}/{len(ids)} en '{nombre}'", flush=True)
        return total

    def upsertir(
        self,
        nombre: str,
        ids: Sequence[str],
        documentos: Sequence[str],
        metadatos: Sequence[dict],
        *,
        lote: int = 256,
        verbose: bool = False,
    ) -> int:
        """Añade fragmentos a una colección existente sin recrearla.

        Permite indexar de forma incremental: el corpus completo se procesa
        documento a documento y se vuelca por lotes, de modo que la memoria
       resident no crece con el tamaño del corpus.
        """
        if not ids:
            return 0
        col = self.coleccion(nombre)
        total = 0
        for i in range(0, len(ids), lote):
            trozo_ids = list(ids[i : i + lote])
            trozo_docs = list(documentos[i : i + lote])
            trozo_meta = list(metadatos[i : i + lote])
            vectores = self.embeddings.embed_documents(trozo_docs)
            col.upsert(ids=trozo_ids, documents=trozo_docs, metadatas=trozo_meta, embeddings=vectores)
            total += len(trozo_ids)
            if verbose:
                print(f"    upsertados {total} en '{nombre}'", flush=True)
        return total

    # -- consulta ------------------------------------------------------------ #
    def buscar(
        self,
        nombre: str,
        consulta: str,
        *,
        k: int = 5,
        where: dict | None = None,
        score_min: float = 0.0,
        ambitos_aceptados: Iterable[str] | None = None,
    ) -> list[FragmentoRecuperado]:
        """Recupera fragmentos similares.

        ``ambitos_aceptados`` filtra además por la lista completa de ámbitos
        del documento (``ambitos``), ya que Chroma indexa ese campo como texto
        plano y no admite ``$contains`` de forma fiable entre versiones.
        """
        col = self.coleccion(nombre)
        if col.count() == 0:
            return []
        vector = self.embeddings.embed_query(consulta)
        # Se sobre-solicitan resultados para poder filtrar por ámbitos multiples.
        n = max(1, k * 4 if ambitos_aceptados else k)
        respuesta = col.query(
            query_embeddings=[vector],
            n_results=min(n, col.count()),
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        docs = (respuesta.get("documents") or [[]])[0]
        metas = (respuesta.get("metadatas") or [[]])[0]
        dists = (respuesta.get("distances") or [[]])[0]
        ids = (respuesta.get("ids") or [[]])[0]

        aceptados = set(ambitos_aceptados) if ambitos_aceptados else None
        salida: list[FragmentoRecuperado] = []
        for i, doc in enumerate(docs):
            dist = float(dists[i]) if i < len(dists) else 1.0
            score = 1.0 - dist  # distancia coseno -> similitud
            if score < score_min:
                continue
            meta = metas[i] if i < len(metas) else {}
            if aceptados is not None:
                lista = str(meta.get("ambitos", "")).split("|")
                if not (aceptados & set(lista)):
                    continue
            salida.append(
                FragmentoRecuperado(
                    id=ids[i] if i < len(ids) else f"idx{i}",
                    texto=doc or "",
                    puntaje=score,
                    metadatos=meta,
                    coleccion=nombre,
                )
            )
            if len(salida) >= k:
                break
        return salida

    def contar(self, nombre: str) -> int:
        try:
            return self.coleccion(nombre).count()
        except Exception:  # noqa: BLE001
            return 0

    def listar(self, nombre: str, limite: int | None = None, donde: dict | None = None) -> list[dict]:
        col = self.coleccion(nombre)
        total = col.count()
        if total == 0:
            return []
        kwargs = {"include": ["metadatas", "documents"]}
        if limite:
            kwargs["limit"] = min(limite, total)
        if donde:
            kwargs["where"] = donde
        datos = col.get(**kwargs)
        salida = []
        for i, doc_id in enumerate(datos.get("ids", [])):
            meta = (datos.get("metadatas") or [{}] * (i + 1))[i] or {}
            doc = (datos.get("documents") or [""] * (i + 1))[i] or ""
            salida.append({"id": doc_id, "metadatos": meta, "texto": doc})
        return salida

    # -- mantenimiento -------------------------------------------------------- #
    def borrar_por_documento(self, nombre: str, documento: str, ruta: str | None = None) -> int:
        """Elimina de una colección los fragmentos que pertenecen a un documento.

        Se usa para dar de baja una evidencia registrada manualmente sin
        tener que reindexar el corpus completo: el borrado es selectivo, por
        metadato, y no toca el resto de la colección.

        ``ruta`` acota el borrado a un archivo concreto.  Hace falta porque el
        corpus puede contener documentos homónimos en carpetas distintas: sin
        la ruta, dar de baja una evidencia manual homónima borraría también
        los fragmentos del documento del corpus.

        Devuelve el número de fragmentos eliminados.
        """
        try:
            col = self.coleccion(nombre)
        except Exception:  # noqa: BLE001 - la colección puede no existir
            return 0
        where: dict
        if ruta:
            where = {"$and": [{"documento": documento}, {"ruta": ruta}]}
        else:
            where = {"documento": documento}
        try:
            antes = col.count()
            col.delete(where=where)
            return max(0, antes - col.count())
        except Exception:  # noqa: BLE001
            return 0

    def reiniciar(self, coleccion: str | None = None) -> None:
        if coleccion:
            try:
                self._cliente.delete_collection(coleccion)
            except Exception:  # noqa: BLE001
                pass
            return
        for nombre in (self.REQUISITOS, self.EVIDENCIAS):
            try:
                self._cliente.delete_collection(nombre)
            except Exception:  # noqa: BLE001
                pass

    def purgar(self) -> None:
        """Borra por completo la base persistente."""
        if shutil.os.path.isdir(self.ruta):
            shutil.rmtree(self.ruta, ignore_errors=True)
        PATHS.ensure()


def filtro_ambito(ambitos: Iterable[str]) -> dict | None:
    """Construye el filtro `where` de Chroma para un conjunto de ámbitos."""
    lista = [a for a in ambitos if a]
    if not lista:
        return None
    if len(lista) == 1:
        return {"ambito": lista[0]}
    return {"ambito": {"$in": lista}}
