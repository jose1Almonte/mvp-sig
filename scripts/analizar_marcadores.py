"""Analiza los marcadores de página residual en los fragmentos semilla."""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.settings import NORMAS, PATHS  # noqa: E402

INICIO = re.compile(r"(?m)^\s*[-–—]\s*\d{1,3}\s*[-–—]\s*")
MEDIO = re.compile(r"(?<=\s)[-–—]\s{0,3}\d{1,3}\s{0,3}[-–—](?=\s|$)")

for clave, spec in NORMAS.items():
    ruta = PATHS.seed_fragments / spec.fragmentos_json
    datos = __import__("json").loads(ruta.read_text(encoding="utf-8"))
    ini = medio = 0
    ejemplos = []
    for d in datos:
        t = d.get("contenido", "")
        n_ini = len(INICIO.findall(t))
        n_medio = len(MEDIO.findall(t))
        ini += n_ini
        medio += n_medio
        if n_medio and len(ejemplos) < 4:
            for m in MEDIO.finditer(t):
                ejemplos.append(t[max(0, m.start() - 45) : m.end() + 45].replace("\n", " "))
    print(f"{clave}: marcadores a inicio de línea={ini}  en medio de línea={medio}")
    for e in ejemplos:
        print(f"    ...{e}...")

# ¿Qué páginas tienen marcadores?
print("\n--- páginas marcadas ---")
datos = __import__("json").loads(
    (PATHS.seed_fragments / NORMAS["ISO9001"].fragmentos_json).read_text(encoding="utf-8")
)
marcadas = []
for d in datos:
    t = d.get("contenido", "")
    if INICIO.search(t) or MEDIO.search(t):
        marcadas.append(d.get("metadatos", {}).get("pagina"))
print("páginas con marcador:", sorted(set(x for x in marcadas if x is not None)))
