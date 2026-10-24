"""Inspección del catálogo de requisitos normativos."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.knowledge.requirements import construir_corpus_requisitos  # noqa: E402

requisitos = construir_corpus_requisitos()

print(f"Total requisitos: {len(requisitos)}")
print("\n--- por norma ---")
for k, v in Counter(r.norma for r in requisitos).items():
    print(f"  {k}: {v}")

print("\n--- distribución de cláusulas (ISO9001) ---")
clausulas = Counter(r.clausula for r in requisitos if r.norma == "ISO9001")
for c, n in sorted(clausulas.items(), key=lambda x: (len(x[0]), x[0])):
    print(f"  cl.{c:8} -> {n} requisitos")

print("\n--- primeros 12 requisitos ---")
for r in requisitos[:12]:
    print(f"\n  id={r.id}  norma={r.norma}  cl={r.clausula}  ambito={r.ambito}  pag={r.pagina}")
    print(f"    {r.texto[:160]}")
