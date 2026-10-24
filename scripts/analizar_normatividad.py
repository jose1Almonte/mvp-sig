"""Cuantifica cuánto del catálogo de requisitos es realmente normativo."""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.knowledge.requirements import construir_corpus_requisitos  # noqa: E402

# Modalidad normativa propia de las ISO en español
NORMATIVO = re.compile(
    r"\b(debe|deben|deberá|deberán|deberán ser|shall|should not|needs to|"
    r"no debe|no deben|debe establecer|debe mantener)\b",
    re.IGNORECASE,
)
# Bloques informativos: NOTA n / Ejemplo / Nota
INFORMATIVO = re.compile(r"(^|\s)(NOTA\s*\d*|Ejemplo|Ejemplos)\s*:?\s", re.IGNORECASE)

requisitos = construir_corpus_requisitos()

con_modal = [r for r in requisitos if NORMATIVO.search(r.texto)]
sin_modal = [r for r in requisitos if not NORMATIVO.search(r.texto)]
introduccion = [r for r in requisitos if r.clausula.startswith("0")]
informativo = [r for r in requisitos if INFORMATIVO.search(r.texto[:400])]

print(f"Total: {len(requisitos)}")
print(f"  con modalidad normativa ('debe'): {len(con_modal)}")
print(f"  SIN modalidad normativa           : {len(sin_modal)}")
print(f"  en la Introducción (cláusula 0.x): {len(introduccion)}")
print(f"  arrancan con NOTA/Ejemplo         : {len(informativo)}")

print("\n--- requisitos SIN modalidad normativa (primeros 15) ---")
for r in sin_modal[:15]:
    print(f"  {r.id:22} cl.{r.clausula:10} {r.texto[:110]}")

print("\n--- requisitos de la Introducción ---")
for r in introduccion:
    print(f"  {r.id:22} {r.texto[:130]}")

print("\n--- reparto por norma de los sin modalidad ---")
for k, v in Counter(r.norma for r in sin_modal).items():
    print(f"  {k}: {v} de {[x for x in requisitos if x.norma == k].__len__()}")
