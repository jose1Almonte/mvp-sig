"""Inspección del último informe de diagnóstico: trazabilidad y citas."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.settings import PATHS  # noqa: E402

informes = sorted(PATHS.reports.glob("diagnostico_*.json"), key=lambda p: p.stat().st_mtime)
if not informes:
    raise SystemExit("No hay informes de diagnóstico.")
ruta = informes[-1]
print("Informe:", ruta.name)
datos = json.loads(ruta.read_text(encoding="utf-8"))

print(f"\nOrganización: {datos['organizacion']}   Proveedor: {datos['proveedor']}  Modelo: {datos['modelo']}")
m = datos["metricas"]
print("\n--- Métricas ---")
for clave in (
    "requisitos_evaluados",
    "tasa_cumplimiento",
    "tasa_no_cumplimiento",
    "tasa_trazabilidad_verificada",
    "requisitos_con_evidencia_citada",
    "citas_totales",
    "citas_verificadas",
    "latencia_media_s",
    "tokens_entrada",
    "tokens_salida",
):
    if clave in m:
        print(f"  {clave:38} {m[clave]}")

print("\n--- Resultados ---")
for r in datos["resultados"]:
    print(f"\n[{r['veredicto']}] {r['requisito_id']}  ({r['norma']} cl.{r['clausula']})")
    print(f"   confianza={r['confianza']}  conf_evidence={r['confianza_evidence']}  "
          f"traza_verificada={r['traza_verificada']}  mejor_puntaje={r['mejor_puntaje']}")
    print(f"   texto: {r['requisito_texto'][:110]}")
    print(f"   justif: {r['justificacion'][:170]}")
    for e in r["evidencias"]:
        marca = "OK " if e["verificada"] else "NO "
        print(f"   {marca}[{e['ref']}] {e['documento']} p.{e['pagina']} sec='{e['seccion']}' "
              f"puntaje={e['puntaje']}")
        print(f"        cita: {e['cita'][:140]}")
        if e["motivo_fallo"]:
            print(f"        motivo: {e['motivo_fallo'][:140]}")
