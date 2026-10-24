"""Explora el vocabulario de modalidad presente en los requisitos no normativos."""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.knowledge.requirements import construir_corpus_requisitos  # noqa: E402

requisitos = construir_corpus_requisitos()

# Verbos candidatos a modalidad normativa en la traducción oficial al español
CANDIDATOS = [
    "debe", "deben", "deberá", "deberán", "shall", "debe ser", "deben ser",
    "no debe", "no deben", "se requiere", "es necesario", "necesario",
    "tiene que", "han de", "deberán ser", "deberá ser", "debe establecer",
    "debe mantener", "debe conservar", "debe demostrar", "debe comunicar",
]
CUERPO = re.compile(r"\d")
PATRON = re.compile(
    r"\b(debe|deben|deber[aá]n?|shall|no debe|no deben|se requiere|"
    r"es necesario|tiene que|han de)\b",
    re.IGNORECASE,
)

sig = [r for r in requisitos if r.clausula.split(".")[0] in {str(i) for i in range(4, 11)}]
con = [r for r in sig if PATRON.search(r.texto)]
sin = [r for r in sig if not PATRON.search(r.texto)]
print(f"Cláusulas 4-10: {len(sig)}   con modalidad: {len(con)}   sin modalidad: {len(sin)}")

print("\n--- 25 requisitos de cláusulas 4-10 SIN modalidad detectada ---")
for r in sin[:25]:
    print(f"\n  {r.id:22} cl.{r.clausula}")
    print(f"    {r.texto[:230]}")

print("\n--- frequencies of candidate modals across the whole corpus ---")
for c in CANDIDATOS:
    n = sum(1 for r in requisitos if c.lower() in r.texto.lower())
    if n:
        print(f"  {c:22} {n}")
