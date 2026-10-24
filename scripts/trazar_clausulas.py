"""Traza la detección de cláusula fragmento a fragmento para localizar la deriva."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.knowledge.requirements import detectar_clausula  # noqa: E402
from mvp_sig.settings import NORMAS, PATHS  # noqa: E402
from mvp_sig.utils.text import limpiar_ruido_iso  # noqa: E402

clave = sys.argv[1] if len(sys.argv) > 1 else "ISO9001"
spec = NORMAS[clave]
datos = json.loads((PATHS.seed_fragments / spec.fragmentos_json).read_text(encoding="utf-8"))

actual = "1"
for i, d in enumerate(datos):
    texto = limpiar_ruido_iso(d.get("contenido", ""))
    if not texto:
        continue
    detectada = detectar_clausula(texto, actual)
    if detectada != actual:
        actual = detectada
    meta = d.get("metadatos", {}).get("clausula")
    marca = "" if str(meta) == str(actual) else "   <<< DIVERGE"
    cabecera = " ".join(texto.split())[:120]
    print(f"[{i:3}] p{d.get('metadatos', {}).get('pagina')} det={actual:12} meta={str(meta):14}{marca}")
    print(f"      {cabecera}")
