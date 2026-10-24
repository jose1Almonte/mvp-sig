"""Experimentos de recuperacion semantica sobre el gold set.

Responde a dos preguntas que condicionan la evaluacion del sistema:

1. **Sensibilidad a k**: cuanta evidencia hace falta para que el documento
   esperado aparezca entre los recovered (y, por tanto, cuanto crece el
   recall cuando se entrega un conjunto mayor al modelo).
2. **Recuperacion hibrida**: si la fusion por RRF de una senal densa (Chroma)
   y otra lexica (solapamiento de tokens ponderado por IDF sobre el titulo
   del documento + el cuerpo del fragmento) mejora la recuperacion.

Uso::

    python scripts/experimento_recuperacion.py [--k 5 10 20 50 100]

Requiere la corpus ingerido (``python run.py ingesta``).
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from mvp_sig.evaluation.goldset import CASOS  # noqa: E402
from mvp_sig.evaluation.metrics import (  # noqa: E402
    evaluar_caso_documento,
    evaluar_recuperacion,
)
from mvp_sig.knowledge.vectorstore import VectorStore  # noqa: E402

# Palabras vacias del español: no aportan señal para discriminar documentos.
STOP = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "y", "o", "u", "en", "con", "por", "para", "que", "se", "al", "su",
    "sus", "lo", "es", "son", "debe", "deben", "deberia", "ser", "como",
    "este", "esta", "estos", "estas", "a", "the", "of", "and",
}
_TOK = re.compile(r"[a-z0-9]+")


def tokens(texto: str) -> list[str]:
    """Tokens significativos de un texto."""
    return [t for t in _TOK.findall(texto.lower()) if len(t) > 2 and t not in STOP]


def fusion_rrf(dense: list, lexico: list, k_rrf: int = 60) -> list:
    """Reciprocal Rank Fusion de dos ordenaciones disjuntas o no."""
    ranks_d = {id(f): i + 1 for i, f in enumerate(dense)}
    ranks_l = {id(f): i + 1 for i, f in enumerate(lexico)}
    unicos = {id(f): f for f in dense + lexico}
    return sorted(
        unicos.values(),
        key=lambda f: -(
            1 / (k_rrf + ranks_d.get(id(f), 10**6))
            + 1 / (k_rrf + ranks_l.get(id(f), 10**6))
        ),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, nargs="*", default=[5, 10, 20, 50, 100])
    args = ap.parse_args()

    store = VectorStore()
    if store.contar(VectorStore.EVIDENCIAS) == 0:
        print("La colección de evidencias está vacía. Ejecute antes: python run.py ingesta")
        return

    # ------------------------------------------------------------------ #
    # 1. Sensibilidad a k (recuperación densa)
    # ------------------------------------------------------------------ #
    print("=" * 78)
    print("1. Sensibilidad a k  (recuperación densa, nivel documento)")
    print("=" * 78)
    print(f"{'k':>5} | {'P@k':>7} {'R@k':>7} {'MRR':>7} {'nDCG':>7}")
    print("-" * 44)
    for k in args.k:
        m = evaluar_recuperacion(store, CASOS, k=k)
        print(
            f"{k:5} | {m['precision@k_documento']:7.3f} {m['recall@k_documento']:7.3f} "
            f"{m['mrr_documento']:7.3f} {m['ndcg@k_documento']:7.3f}"
        )

    # ------------------------------------------------------------------ #
    # 2. Recuperación híbrida (RRF densa + léxica)
    # ------------------------------------------------------------------ #
    print()
    print("=" * 78)
    print("2. Recuperación híbrida  (RRF: densa + léxica IDF)")
    print("=" * 78)

    filas = store.listar(VectorStore.EVIDENCIAS)
    freq: Counter[str] = Counter()
    for f in filas:
        meta = f.get("metadatos", {})
        freq.update(set(tokens(f"{meta.get('documento', '')} {f.get('texto', '')}")))
    total = len(filas) or 1
    idf = {t: math.log((total + 1) / (c + 0.5)) for t, c in freq.items()}

    print(f"{'cand':>5} {'k':>4} | {'P@doc':>7} {'R@doc':>7} {'MRR':>7} {'nDCG':>7}")
    print("-" * 44)
    for k_cand in (50, 100):
        acc = {"precision": 0.0, "recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
        for caso in CASOS:
            candidatos = store.buscar(VectorStore.EVIDENCIAS, caso.consulta, k=k_cand)
            q = set(tokens(caso.consulta))
            norm_q = sum(idf.get(t, 0.0) for t in q) or 1.0

            def lexico(f, _q=q, _n=norm_q):
                meta = f.metadatos or {}
                comunes = _q & set(tokens(f"{meta.get('documento', '')} {f.texto}"))
                return sum(idf.get(t, 0.0) for t in comunes) / _n

            orden_lex = sorted(candidatos, key=lexico, reverse=True)
            r = evaluar_caso_documento(caso, fusion_rrf(candidatos, orden_lex)[:5], k=5)
            for clave in acc:
                acc[clave] += getattr(r, clave)
        n = len(CASOS)
        print(
            f"{k_cand:5} {5:4} | {acc['precision']/n:7.3f} {acc['recall']/n:7.3f} "
            f"{acc['mrr']/n:7.3f} {acc['ndcg']/n:7.3f}"
        )

    print()
    print("Referencia (densa pura):")
    for k in (5,):
        m = evaluar_recuperacion(store, CASOS, k=k)
        print(
            f"{'-':>5} {k:4} | {m['precision@k_documento']:7.3f} {m['recall@k_documento']:7.3f} "
            f"{m['mrr_documento']:7.3f} {m['ndcg@k_documento']:7.3f}"
        )


if __name__ == "__main__":
    main()
