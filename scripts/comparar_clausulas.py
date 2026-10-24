"""Compara la cláusula de los metadatos semilla con la cláusula detectada."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.knowledge.requirements import detectar_clausula  # noqa: E402
from mvp_sig.settings import NORMAS, PATHS  # noqa: E402
from mvp_sig.utils.text import limpiar_ruido_iso  # noqa: E402

for clave, spec in NORMAS.items():
    datos = json.loads((PATHS.seed_fragments / spec.fragmentos_json).read_text(encoding="utf-8"))
    meta_claus = [d.get("metadatos", {}).get("clausula") for d in datos]
    sin_meta = sum(1 for c in meta_claus if not c)
    print(f"\n=== {clave}: {len(datos)} fragmentos; sin 'clausula' en metadatos: {sin_meta}")
    print("    valores:", Counter(c for c in meta_claus if c).most_common(12))

    # Reproducir el rastreo secuencial y comparar con los metadatos.
    actual = "1"
    coincidencias = 0
    comparables = 0
    for d in datos:
        texto = limpiar_ruido_iso(d.get("contenido", ""))
        if not texto:
            continue
        detectada = detectar_clausula(texto, actual)
        if detectada != actual:
            actual = detectada
        meta = d.get("metadatos", {}).get("clausula")
        if meta:
            comparables += 1
            if str(meta) == str(actual):
                coincidencias += 1
    print(f"    coincidencia metadatos vs. rastreo secuencial: {coincidencias}/{comparables}")
