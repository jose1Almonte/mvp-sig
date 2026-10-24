"""Muestra la estructura de los fragmentos semilla de una norma."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.settings import NORMAS, PATHS  # noqa: E402

spec = NORMAS["ISO9001"]
ruta = PATHS.seed_fragments / spec.fragmentos_json
datos = json.loads(ruta.read_text(encoding="utf-8"))
print(f"Fragmentos de {spec.nombre_archivo}: {len(datos)}")
print("claves:", list(datos[0].keys()))
print("metadatos de ejemplo:", datos[0].get("metadatos"))

print("\n--- 3 primeros fragmentos (texto recortado) ---")
for d in datos[:3]:
    print("\n=== pagina", d.get("metadatos", {}).get("pagina"))
    print(repr(d.get("contenido", ""))[:900])
