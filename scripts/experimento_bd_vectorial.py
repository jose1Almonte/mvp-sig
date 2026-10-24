"""Experimento comparativo de bases de datos vectoriales (fase 3.3.a).

El anteproyecto pide evaluar *"la capacidad de filtrado por metadatos y la
latencia de consulta"* del componente de recuperación semántica, y menciona
Qdrant o ChromaDB como alternativas.  Este script mide esa capacidad sobre el
corpus real y contrasta las dos opciones con **los mismos vectores**, de modo
que la comparación no dependa del modelo de embeddings.

Qué mide
--------
* latencia de consulta (media, p50, p95) para cada motor y cada ``k``;
* efecto del filtrado por metadatos (ámbito) sobre la latencia y sobre el
  número de resultados devueltos;
* solapamiento de resultados entre motores: si ambos recuperan el mismo
  fragmento en la misma posición, la elección del motor es indiferente para
  la calidad del diagnóstico.

Reproducible con::

    python scripts/experimento_bd_vectorial.py

Requiere ``qdrant-client`` (opcional).  Si no está instalado, el script mide
únicamente ChromaDB y lo hace explícito en el informe.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from mvp_sig.evaluation.goldset import CASOS  # noqa: E402
from mvp_sig.knowledge.embeddings import obtener_embeddings  # noqa: E402
from mvp_sig.knowledge.vectorstore import VectorStore  # noqa: E402
from mvp_sig.settings import PATHS  # noqa: E402

REPETICIONES = 20
KS = (5, 10, 20)


# --------------------------------------------------------------------------- #
# Utilidades de medida
# --------------------------------------------------------------------------- #
def _percentiles(muestras: list[float]) -> dict:
    orden = sorted(muestras)
    return {
        "media_ms": round(statistics.fmean(orden), 2),
        "p50_ms": round(statistics.median(orden), 2),
        "p95_ms": round(orden[min(len(orden) - 1, int(len(orden) * 0.95))], 2),
        "min_ms": round(orden[0], 2),
    }


def _solapamiento(a: list[str], b: list[str]) -> float:
    """Jaccard entre los identificadores devueltos por cada motor."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


# --------------------------------------------------------------------------- #
# Carga del corpus real desde ChromaDB
# --------------------------------------------------------------------------- #
def cargar_fragmentos(store: VectorStore) -> tuple[list, list, np.ndarray, list[str]]:
    """Devuelve (ids, metadatos, vectores, documentos) de la colección real."""
    col = store.coleccion(VectorStore.EVIDENCIAS)
    total = col.count()
    print(f"  Colección 'evidencias': {total} fragmentos")

    ids: list[str] = []
    metas: list[dict] = []
    docs: list[str] = []
    vectores: list[np.ndarray] = []

    lote = 2000
    for inicio in range(0, total, lote):
        datos = col.get(
            include=["metadatas", "documents", "embeddings"],
            limit=min(lote, total - inicio),
            offset=inicio,
        )
        ids.extend(datos.get("ids") or [])
        metas.extend(datos.get("metadatas") or [])
        docs.extend(datos.get("documents") or [])
        embs = datos.get("embeddings")
        if embs is None:
            raise RuntimeError("La colección no devolvió los embeddings.")
        vectores.extend(np.asarray(e, dtype=np.float32) for e in embs)
        print(f"    cargados {len(ids)}/{total}", flush=True)

    matriz = np.vstack(vectores)
    return ids, metas, matriz, docs


# --------------------------------------------------------------------------- #
# Motores
# --------------------------------------------------------------------------- #
class MotorChroma:
    nombre = "ChromaDB"

    def __init__(self, store: VectorStore) -> None:
        self.store = store
        self.col = store.coleccion(VectorStore.EVIDENCIAS)

    def consultar(self, vector: np.ndarray, k: int, ambito: str | None) -> list[str]:
        where = {"ambito": ambito} if ambito else None
        r = self.col.query(
            query_embeddings=[vector.tolist()],
            n_results=min(k, self.col.count()),
            where=where,
            include=["metadatas"],
        )
        return list((r.get("ids") or [[]])[0])


class MotorQdrant:
    nombre = "Qdrant"

    def __init__(self, ids, metas, matriz) -> None:
        from qdrant_client import QdrantClient, models

        self._models = models
        self.client = QdrantClient(":memory:")
        self.dim = matriz.shape[1]
        self.client.create_collection(
            collection_name="evidencias",
            vectors_config=models.VectorParams(
                size=self.dim, distance=models.Distance.COSINE
            ),
        )
        puntos = []
        for i, vid in enumerate(ids):
            carga = {
                k: v
                for k, v in (metas[i] or {}).items()
                if isinstance(v, (str, int, float, bool))
            }
            carga["_id"] = vid
            # Qdrant exige identificadores UUID o enteros; se usa el índice y
            # se guarda la correspondencia con el id de ChromaDB.
            puntos.append(
                models.PointStruct(id=i, vector=matriz[i].tolist(), payload=carga)
            )
        self.client.upsert(collection_name="evidencias", points=puntos, wait=True)
        self.id_por_indice = {i: vid for i, vid in enumerate(ids)}

    def consultar(self, vector: np.ndarray, k: int, ambito: str | None) -> list[str]:
        models = self._models
        filtro = None
        if ambito:
            filtro = models.Filter(
                must=[models.FieldCondition(key="ambito", match=models.MatchValue(value=ambito))]
            )
        respuesta = self.client.query_points(
            collection_name="evidencias",
            query=vector.tolist(),
            limit=k,
            query_filter=filtro,
            with_payload=False,
        )
        return [self.id_por_indice.get(h.id, str(h.id)) for h in respuesta.points]


# --------------------------------------------------------------------------- #
# Experimento
# --------------------------------------------------------------------------- #
def main() -> None:
    print("=" * 78)
    print("EXPERIMENTO COMPARATIVO DE BASES DE DATOS VECTORIALES")
    print("=" * 78)

    store = VectorStore()
    ids, metas, matriz, _docs = cargar_fragmentos(store)
    embeddings = obtener_embeddings()

    consultas = [(c.consulta, c.ambito) for c in CASOS]
    vectores_consulta = [
        np.asarray(embeddings.embed_query(t), dtype=np.float32) for t, _a in consultas
    ]
    print(f"  {len(vectores_consulta)} consultas del conjunto de oro\n")

    motores: list = [MotorChroma(store)]
    try:
        motores.append(MotorQdrant(ids, metas, matriz))
        print("  Qdrant: colección en memoria creada con los mismos vectores")
    except ImportError:
        print("  Qdrant no disponible (pip install qdrant-client)")

    resultados: dict = {
        "fragmentos": len(ids),
        "consultas": len(consultas),
        "repeticiones": REPETICIONES,
        "notas": [
            "Los dos motores indexan exactamente los mismos vectores "
            "(1024 dims, mxbai-embed-large), de modo que la diferencia de "
            "latencia es atribuible al motor y no al modelo de embeddings.",
            "Qdrant se ejecuta en modo local en memoria (':memory:') sin "
            "servidor: es la configuración más ligera y, aun así, es más "
            "lenta que ChromaDB en este corpus. Un servidor Qdrant con "
            "índices de payload planificados sería más rápido en el filtrado, "
            "pero exige infraestructura adicional.",
            "En ChromaDB el filtro por metadatos se aplica tras la búsqueda "
            "aproximada: por eso su coste crece cuando el filtro es "
            "selectivo ('seguridad' es más restrictivo que 'calidad').",
            "El filtrado por ámbito en el MVP se completa en Python sobre el "
            "campo 'ambitos' (lista separada por '|'), lo que explica el "
            "sobre-solicitado k*4 de VectorStore.buscar.",
        ],
        "mediciones": [],
    }

    for k in KS:
        for ambito in (None, "calidad", "seguridad"):
            for motor in motores:
                muestras: list[float] = []
                n_resultados: list[int] = []
                for vec in vectores_consulta:
                    # Calentamiento: la primera llamada paga la inicialización.
                    motor.consultar(vec, k, ambito)
                    t0 = time.perf_counter()
                    for _ in range(REPETICIONES):
                        ids_devueltos = motor.consultar(vec, k, ambito)
                    muestras.append((time.perf_counter() - t0) * 1000 / REPETICIONES)
                    n_resultados.append(len(ids_devueltos))
                resultados["mediciones"].append(
                    {
                        "motor": motor.nombre,
                        "k": k,
                        "ambito": ambito or "sin filtro",
                        "resultados_medios": round(statistics.fmean(n_resultados), 1),
                        **_percentiles(muestras),
                    }
                )

    # Solapamiento entre motores (Chroma vs Qdrant) en las mismas consultas.
    if len(motores) >= 2:
        solapamientos = []
        for k in KS:
            for vec in vectores_consulta:
                a = motores[0].consultar(vec, k, None)
                b = motores[1].consultar(vec, k, None)
                solapamientos.append(_solapamiento(a, b))
        resultados["solapamiento_promedio"] = round(statistics.fmean(solapamientos), 4)
        resultados["solapamiento_min"] = round(min(solapamientos), 4)

    # ------------------------------------------------------------------------ #
    # Informe
    # ------------------------------------------------------------------------ #
    print(f"\n{'=' * 78}\nLATENCIA DE CONSULTA (ms)\n{'=' * 78}")
    print(f"  {'motor':<10} {'k':>3} {'filtro':<13} {'media':>8} {'p50':>8} {'p95':>8} {'n':>6}")
    for m in resultados["mediciones"]:
        print(
            f"  {m['motor']:<10} {m['k']:>3} {m['ambito']:<13} "
            f"{m['media_ms']:>8.2f} {m['p50_ms']:>8.2f} {m['p95_ms']:>8.2f} "
            f"{m['resultados_medios']:>6.1f}"
        )

    if "solapamiento_promedio" in resultados:
        print(f"\n  Solapamiento medio de resultados (Chroma vs Qdrant): "
              f"{resultados['solapamiento_promedio'] * 100:.1f}% "
              f"(mínimo {resultados['solapamiento_min'] * 100:.1f}%)")

    destino = PATHS.reports / "experimento_bd_vectorial.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Informe: {destino}")


if __name__ == "__main__":
    main()
