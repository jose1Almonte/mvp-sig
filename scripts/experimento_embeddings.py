"""Comparación de modelos de embeddings sobre el corpus real.

La limitación más relevante del MVP es que ``mxbai-embed-large`` está
orientado al inglés mientras que el corpus y las consultas normativas están
en español.  Este experimento mide si otro modelo disponible en el equipo
(``nomic-embed-text``, que sí es multilingüe) mejora la recuperación.

Procedimiento
-------------
1. Se leen los fragmentos y sus metadatos de la colección real **por lotes**
   (sin volver a extraer los documentos y sin retener el corpus en memoria).
2. Se reindexa *el mismo corpus* con el modelo alternativo en una base
   temporal, de modo que la base de producción no se toca.
3. Se evalúa el *gold set* contra ambas bases y se comparan los indicadores.

Uso::

    python scripts/experimento_embeddings.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mvp_sig.evaluation.metrics import evaluar_recuperacion  # noqa: E402
from mvp_sig.knowledge.embeddings import OllamaEmbeddings  # noqa: E402
from mvp_sig.knowledge.vectorstore import VectorStore  # noqa: E402
from mvp_sig.settings import MODELS, PATHS  # noqa: E402

RUTA_TEMP = PATHS.storage / "chroma_experimento_embeddings"

# Candidatos multilingües disponibles en el equipo.
CANDIDATOS = [
    ("nomic-embed-text", 768),
    ("mxbai-embed-large", 1024),
]

LOTE = 500


def _reindexar(store: VectorStore, store_alt: VectorStore) -> int:
    """Copia el corpus de producción a la base alternativa, lote a lote."""
    col = store.coleccion(VectorStore.EVIDENCIAS)
    total = col.count()
    col_alt = store_alt.coleccion(VectorStore.EVIDENCIAS, recrear=True)

    indexados = 0
    for inicio in range(0, total, LOTE):
        datos = col.get(
            include=["metadatas", "documents"],
            limit=min(LOTE, total - inicio),
            offset=inicio,
        )
        ids = datos.get("ids") or []
        docs = datos.get("documents") or []
        metas = datos.get("metadatas") or []
        if not ids:
            break
        vectores = store_alt.embeddings.embed_documents(list(docs))
        col_alt.upsert(ids=list(ids), documents=list(docs), metadatas=list(metas), embeddings=vectores)
        indexados += len(ids)
        print(f"    reindexados {indexados}/{total}", flush=True)
    return indexados


def _fila(nombre: str, dim: int, m: dict) -> str:
    return (
        f"  {nombre:<22} {dim:>5} {m['precision@k']:>7.3f} {m['recall@k']:>7.3f} "
        f"{m['mrr']:>7.3f} {m['ndcg@k']:>7.3f} {m['precision@k_documento']:>9.3f} "
        f"{m['recall@k_documento']:>9.3f} {m['mrr_documento']:>9.3f} "
        f"{m['ndcg@k_documento']:>9.3f}"
    )


def main() -> None:
    print("=" * 78)
    print("COMPARACIÓN DE MODELOS DE EMBEDDINGS")
    print("=" * 78)

    store = VectorStore()
    col = store.coleccion(VectorStore.EVIDENCIAS)
    total = col.count()
    print(f"  Colección de producción: {total} fragmentos")

    resultados: dict = {
        "fragmentos": total,
        "base_produccion": {
            "modelo": MODELS.embedding_model,
            "dim": MODELS.embedding_dim,
        },
        "comparaciones": [],
    }

    # --- Línea base: el modelo en producción ------------------------------ #
    print("\n  Evaluando el modelo de producción...")
    base = evaluar_recuperacion(store, k=5)
    resultados["base_produccion"].update({k: v for k, v in base.items() if k != "detalle"})

    # --- Candidatos alternativos ------------------------------------------ #
    for nombre, dim in CANDIDATOS:
        if nombre == MODELS.embedding_model:
            continue
        print(f"\n  Probando '{nombre}' ({dim} dims)...")
        emb = OllamaEmbeddings(modelo=nombre, dim=dim)
        if not emb.disponible():
            print("    no disponible en Ollama: se omite")
            resultados["comparaciones"].append({"modelo": nombre, "estado": "no disponible"})
            continue

        shutil.rmtree(RUTA_TEMP, ignore_errors=True)
        store_alt = VectorStore(ruta=str(RUTA_TEMP), embeddings=emb)
        inicio = time.perf_counter()
        n = _reindexar(store, store_alt)
        segundos = time.perf_counter() - inicio
        print(f"    reindexados {n} fragmentos en {segundos:.1f} s")

        metricas = evaluar_recuperacion(store_alt, k=5)
        resultados["comparaciones"].append(
            {
                "modelo": nombre,
                "dim": dim,
                "estado": "ok",
                "segundos_indexado": round(segundos, 1),
                **{k: v for k, v in metricas.items() if k != "detalle"},
            }
        )
        del store_alt
        shutil.rmtree(RUTA_TEMP, ignore_errors=True)

    # --- Informe ----------------------------------------------------------- #
    print(f"\n{'=' * 78}\nINDICADORES DE RECUPERACIÓN (k=5, conjunto de oro)\n{'=' * 78}")
    print(
        f"  {'modelo':<22} {'dim':>5} {'P@5':>7} {'R@5':>7} {'MRR':>7} {'nDCG':>7} "
        f"{'P@5 doc':>9} {'R@5 doc':>9} {'MRR doc':>9} {'nDCG doc':>9}"
    )
    b = resultados["base_produccion"]
    print(_fila(b["modelo"], b["dim"], b))
    for c in resultados["comparaciones"]:
        if c.get("estado") == "ok":
            print(_fila(c["modelo"], c["dim"], c))

    destino = PATHS.reports / "experimento_embeddings.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Informe: {destino}")


if __name__ == "__main__":
    main()
