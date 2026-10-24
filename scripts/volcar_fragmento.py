"""Vuelca fragmentos concretos de una norma para diseñar la regla de cláusula."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.settings import NORMAS, PATHS  # noqa: E402
from mvp_sig.utils.text import limpiar_ruido_iso  # noqa: E402

clave = sys.argv[1] if len(sys.argv) > 1 else "ISO9001"
indices = [int(x) for x in sys.argv[2:]] or [3, 17, 39]
datos = json.loads((PATHS.seed_fragments / NORMAS[clave].fragmentos_json).read_text(encoding="utf-8"))

for i in indices:
    d = datos[i]
    texto = limpiar_ruido_iso(d.get("contenido", ""))
    print(f"\n{'=' * 70}\nFRAGMENTO {i}  pagina={d.get('metadatos', {}).get('pagina')}  "
          f"meta_clausula={d.get('metadatos', {}).get('clausula')}\n{'=' * 70}")
    print(repr(texto[:1400]))
