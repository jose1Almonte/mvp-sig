"""Métricas de evaluación del pipeline (fase 4.1 del anteproyecto).

Dos familias:
  * **Recuperación**: precisión@k, recall@k, MRR y nDCG sobre el gold set.
  * **Diagnóstico**: cobertura, tasa de trazabilidad verificada, acuerdo entre
    modelos y coste por requisito.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from mvp_sig.diagnosis.engine import ResultadoDiagnostico
from mvp_sig.evaluation.goldset import CASOS, CasoGold
from mvp_sig.knowledge.vectorstore import VectorStore


@dataclass
class ResultadoRecuperacion:
    """Métricas de recuperación para un caso del gold set."""

    caso_id: str
    consulta: str
    documentos_esperados: list[str]
    documentos_obtenidos: list[str]
    relevant_retrieved: int
    precision: float
    recall: float
    mrr: float
    ndcg: float
    detalle: list[dict] = field(default_factory=list)


def evaluar_caso(caso: CasoGold, frags, k: int = 5) -> ResultadoRecuperacion:
    """Calcula las métricas de un único caso de recuperación (por fragmento)."""
    esperados = caso.documentos_esperados
    obtenidos = [f.metadatos.get("documento", "") for f in frags]
    relevantes = [f for f, doc in zip(frags, obtenidos) if caso.coincide(doc)]

    # relevance vector
    rel = [1 if caso.coincide(doc) else 0 for doc in obtenidos]

    precision = sum(rel) / len(rel) if rel else 0.0
    n_esperados = len(esperados)
    hits = len({f.metadatos.get("documento", "") for f in relevantes})
    recall = min(1.0, hits / n_esperados) if n_esperados else 0.0

    # MRR
    mrr = 0.0
    for i, r in enumerate(rel, start=1):
        if r:
            mrr = 1.0 / i
            break

    # nDCG
    dcg = sum(rel[i] / math.log2(i + 2) for i in range(len(rel)))
    ideal = sorted(rel, reverse=True)
    idcg = sum(ideal[i] / math.log2(i + 2) for i in range(len(ideal)))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    return ResultadoRecuperacion(
        caso_id=caso.id,
        consulta=caso.consulta,
        documentos_esperados=esperados,
        documentos_obtenidos=obtenidos,
        relevant_retrieved=hits,
        precision=round(precision, 4),
        recall=round(recall, 4),
        mrr=round(mrr, 4),
        ndcg=round(ndcg, 4),
        detalle=[
            {
                "documento": f.metadatos.get("documento", ""),
                "puntaje": round(f.puntaje, 4),
                "relevante": bool(r),
            }
            for f, r in zip(frags, rel)
        ],
    )


def evaluar_caso_documento(caso: CasoGold, frags, k: int = 5) -> ResultadoRecuperacion:
    """Calcula las métricas de un caso **por documento**, no por fragmento.

    El *gold set* define la relevancia a nivel de documento: un fragmento es
    relevante si pertenece a un documento que sustenta el requisito.  Al
    agregar los fragmentos recuperados por documento se obtiene la ranked
    list que realmente se entrega al evaluador (la cita apunta al documento),
    y se evita penalizar al sistema por haber troceado un documento en varios
    fragmentos.
    """
    esperados = caso.documentos_esperados

    documentos: list[str] = []
    for f in frags:
        d = f.metadatos.get("documento", "")
        if d and d not in documentos:
            documentos.append(d)

    rel = [1 if caso.coincide(doc) else 0 for doc in documentos]
    precision = sum(rel) / len(rel) if rel else 0.0
    hits = sum(rel)
    recall = min(1.0, hits / len(esperados)) if esperados else 0.0

    mrr = 0.0
    for i, r in enumerate(rel, start=1):
        if r:
            mrr = 1.0 / i
            break

    dcg = sum(rel[i] / math.log2(i + 2) for i in range(len(rel)))
    ideal = sorted(rel, reverse=True)
    idcg = sum(ideal[i] / math.log2(i + 2) for i in range(len(ideal)))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    return ResultadoRecuperacion(
        caso_id=caso.id,
        consulta=caso.consulta,
        documentos_esperados=esperados,
        documentos_obtenidos=documentos,
        relevant_retrieved=hits,
        precision=round(precision, 4),
        recall=round(recall, 4),
        mrr=round(mrr, 4),
        ndcg=round(ndcg, 4),
        detalle=[{"documento": d, "relevante": bool(r)} for d, r in zip(documentos, rel)],
    )


def evaluar_recuperacion(
    store: VectorStore,
    casos: list[CasoGold] | None = None,
    *,
    k: int = 5,
    score_min: float = 0.0,
) -> dict:
    """Evalúa la recuperación sobre el gold set completo.

    Se reportan dos niveles, porque miden cosas distintas:

    * **fragmento**: precisión de los *k* fragmentos recuperados (lo que
      devuelve el almacén vectorial).
    * **documento**: los mismos fragmentos agregados por documento (lo que
      se cita como evidencia).  El *gold set* define la relevancia por
      documento, de modo que este es el indicador de referencia.
    """
    casos = casos or CASOS
    resultados = []
    resultados_doc = []
    for caso in casos:
        frags = store.buscar(
            VectorStore.EVIDENCIAS,
            caso.consulta,
            k=k,
            score_min=score_min,
        )
        resultados.append(evaluar_caso(caso, frags, k=k))
        resultados_doc.append(evaluar_caso_documento(caso, frags, k=k))

    n = len(resultados) or 1
    nd = len(resultados_doc) or 1
    return {
        "casos": len(resultados),
        "k": k,
        # Nivel fragmento
        "precision@k": round(sum(r.precision for r in resultados) / n, 4),
        "recall@k": round(sum(r.recall for r in resultados) / n, 4),
        "mrr": round(sum(r.mrr for r in resultados) / n, 4),
        "ndcg@k": round(sum(r.ndcg for r in resultados) / n, 4),
        # Nivel documento (indicador de referencia)
        "precision@k_documento": round(sum(r.precision for r in resultados_doc) / nd, 4),
        "recall@k_documento": round(sum(r.recall for r in resultados_doc) / nd, 4),
        "mrr_documento": round(sum(r.mrr for r in resultados_doc) / nd, 4),
        "ndcg@k_documento": round(sum(r.ndcg for r in resultados_doc) / nd, 4),
        "detalle": [
            {
                "caso_id": r.caso_id,
                "consulta": r.consulta,
                "precision": r.precision,
                "recall": r.recall,
                "mrr": r.mrr,
                "ndcg": r.ndcg,
                "precision_documento": d.precision,
                "recall_documento": d.recall,
                "mrr_documento": d.mrr,
                "ndcg_documento": d.ndcg,
                "obtenidos": r.documentos_obtenidos,
                "esperados": r.documentos_esperados,
            }
            for r, d in zip(resultados, resultados_doc)
        ],
    }


# --------------------------------------------------------------------------- #
# Evaluación del diagnóstico
# --------------------------------------------------------------------------- #
def evaluar_diagnostico(resultados: list[ResultadoDiagnostico]) -> dict:
    """Métricas agregadas del diagnóstico ya calculado."""
    from mvp_sig.diagnosis.engine import calcular_metricas

    m = calcular_metricas(resultados)
    n = len(resultados) or 1
    # Índices de calidad de la evidencia
    con_cita = sum(1 for r in resultados if r.evidencia)
    citas_totales = sum(len(r.evidencia) for r in resultados)
    citas_ok = sum(1 for r in resultados for e in r.evidencia if e.verificada)
    m.update(
        {
            "requisitos_con_cita": con_cita,
            "citas_totales": citas_totales,
            "citas_verificadas": citas_ok,
            "tasa_citas_verificadas": round(citas_ok / citas_totales, 4) if citas_totales else 0.0,
            "confianza_media": round(sum(r.confianza for r in resultados) / n, 4),
            "confianza_evidencia_media": round(
                sum(r.confianza_evidence for r in resultados) / n, 4
            ),
        }
    )
    return m


def comparar_modelos(resultados_por_modelo: dict[str, list[ResultadoDiagnostico]]) -> dict:
    """Compara el veredicto de varios modelos sobre los mismos requisitos.

    Calcula el *acuerdo inter-modelo* (coincidencia de veredicto) y la tasa de
    trazabilidad verificada de cada uno: los dos indicadores que permiten
    seleccionar el LLM más costo-efectivo (objetivo 3.3.c).
    """
    modelos = list(resultados_por_modelo.keys())
    if len(modelos) < 2:
        return {}

    # Índice por requisito para cada modelo
    index: dict[str, dict[str, str]] = {}
    for modelo, res in resultados_por_modelo.items():
        index[modelo] = {r.requisito_id: r.veredicto for r in res}

    ids_comunes = set.intersection(*[set(v.keys()) for v in index.values()])
    if not ids_comunes:
        return {}

    resumen = {}
    for modelo in modelos:
        res = resultados_por_modelo[modelo]
        sub = [r for r in res if r.requisito_id in ids_comunes]
        m = evaluar_diagnostico(sub)
        m["modelo"] = modelo
        m["acuerdo_con_otros"] = 0.0
        resumen[modelo] = m

    # Acuerdo pairwise (promedio del índice de coincidencia)
    for i, a in enumerate(modelos):
        acuerdos = []
        for j, b in enumerate(modelos):
            if i == j:
                continue
            comunes = ids_comunes
            coincide = sum(1 for x in comunes if index[a][x] == index[b][x])
            acuerdos.append(coincide / len(comunes))
        resumen[a]["acuerdo_con_otros"] = round(sum(acuerdos) / len(acuerdos), 4) if acuerdos else 0.0

    return {
        "requisitos_comparados": len(ids_comunes),
        "modelos": modelos,
        "resumen": resumen,
    }
