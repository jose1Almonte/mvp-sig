"""Matriz de trazabilidad requisito-evidencia.

Es el entregable central de la tesis: cada fila enlaza un requisito normativo
con el veredicto, la evidencia documental que lo sustenta (con cita literal) y
el hallazgo. Se exporta en CSV, JSON y HTML para el informe.
"""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from mvp_sig.diagnosis.engine import InformeDiagnostico, ResultadoDiagnostico
from mvp_sig.utils.text import truncar

COLUMNAS = [
    "requisito_id",
    "norma",
    "clausula",
    "ambito",
    "requisito",
    "veredicto",
    "confianza",
    "confianza_evidence",
    "traza_verificada",
    "evidencia_documento",
    "evidencia_pagina",
    "evidencia_seccion",
    "evidencia_cita",
    "evidencia_verificada",
    "similitud",
    "hallazgo",
    "severidad",
    "recomendacion",
    "justificacion",
    "modelo",
    "fecha",
]


def _fila(r: ResultadoDiagnostico, fecha: str) -> dict:
    ev = r.evidencia[0] if r.evidencia else None
    return {
        "requisito_id": r.requisito_id,
        "norma": r.norma,
        "clausula": r.clausula,
        "ambito": r.ambito,
        "requisito": truncar(r.requisito_texto, 400),
        "veredicto": r.veredicto,
        "confianza": round(r.confianza, 3),
        "confianza_evidence": round(r.confianza_evidence, 3),
        "traza_verificada": "SI" if r.traza_verificada else "NO",
        "evidencia_documento": ev.documento if ev else "",
        "evidencia_pagina": ev.pagina if ev else "",
        "evidencia_seccion": ev.seccion if ev else "",
        "evidencia_cita": truncar(ev.cita, 500) if ev else "",
        "evidencia_verificada": ("SI" if ev.verificada else "NO") if ev else "",
        "similitud": round(ev.puntaje, 4) if ev else "",
        "hallazgo": r.hallazgo,
        "severidad": r.severidad,
        "recomendacion": r.recomendacion,
        "justificacion": truncar(r.justificacion, 700),
        "modelo": f"{r.proveedor}/{r.modelo}",
        "fecha": fecha,
    }


def construir_filas(informe: InformeDiagnostico) -> list[dict]:
    fecha = informe.generado[:10]
    return [_fila(r, fecha) for r in informe.resultados]


def exportar_csv(informe: InformeDiagnostico, ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    filas = construir_filas(informe)
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNAS)
        writer.writeheader()
        writer.writerows(filas)
    return ruta


def exportar_json(informe: InformeDiagnostico, ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(informe.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


_COLORES = {
    "CUMPLE": ("#E8F5E9", "#1B5E20"),
    "CUMPLE_PARCIAL": ("#FFF8E1", "#F9A825"),
    "NO_CUMPLE": ("#FFEBEE", "#C62828"),
    "NO_APLICA": ("#ECEFF1", "#546E7A"),
}


def exportar_html(informe: InformeDiagnostico, ruta: str | Path) -> Path:
    """Informe HTML autocontenido, listo para presentar o adjuntar."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    m = informe.metricas or {}

    def esc(x) -> str:
        return html.escape(str(x))

    filas = []
    for r in informe.resultados:
        fondo, tinta = _COLORES.get(r.veredicto, ("#fff", "#000"))
        ev_html = ""
        for e in r.evidencia:
            marca = "&#10003;" if e.verificada else "&#10007;"
            color = "#2E7D32" if e.verificada else "#C62828"
            ev_html += (
                f"<div class='ev'><span style='color:{color};font-weight:bold'>{marca}</span> "
                f"<b>{esc(e.documento)}</b>"
                + (f" (pág. {esc(e.pagina)})" if e.pagina else "")
                + (f" — {esc(truncar(e.seccion, 60))}" if e.seccion else "")
                + f"<blockquote>{esc(truncar(e.cita, 320))}</blockquote>"
                + f"<small>Similitud {e.puntaje:.3f} · fragmento <code>{esc(truncar(e.fragmento_id, 70))}</code></small>"
                "</div>"
            )
        if not ev_html:
            ev_html = "<div class='ev'><i>Sin evidencia citada.</i></div>"
        filas.append(
            f"<tr>"
            f"<td><b>{esc(r.requisito_id)}</b><br><small>{esc(r.norma)} · cl. {esc(r.clausula)} · {esc(r.ambito)}</small></td>"
            f"<td>{esc(truncar(r.requisito_texto, 260))}</td>"
            f"<td style='background:{fondo};color:{tinta};text-align:center;font-weight:bold'>{esc(r.veredicto)}</td>"
            f"<td style='text-align:center'>{r.confianza:.2f}</td>"
            f"<td>{ev_html}</td>"
            f"<td>{esc(r.hallazgo)}<br><small><b>{esc(r.severidad)}</b></small><br><i>{esc(r.recomendacion)}</i>"
            f"<br><small class='just'>{esc(truncar(r.justificacion, 400))}</small></td>"
            f"</tr>"
        )

    resumen = ""
    if informe.resumen_ejecutivo:
        resumen = (
            "<section class='resumen'><h2>Resumen ejecutivo</h2>"
            f"<pre>{esc(informe.resumen_ejecutivo)}</pre></section>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Diagnóstico de cumplimiento normativo SIG</title>
<style>
 body{{font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:28px;background:#fafafa;color:#212121}}
 h1{{font-size:21px;margin:0 0 4px}} .sub{{color:#666;font-size:13px;margin-bottom:18px}}
 table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.12)}}
 th{{background:#263238;color:#fff;padding:9px;text-align:left;font-size:12px;position:sticky;top:0}}
 td{{padding:9px;border-bottom:1px solid #ececec;vertical-align:top;font-size:13px}}
 tr:nth-child(even) td{{background:#fcfcfc}}
 blockquote{{margin:5px 0;padding:5px 9px;border-left:3px solid #90a4ae;background:#f5f7f8;font-style:italic}}
 .ev{{margin-bottom:8px}} small{{color:#777;font-size:11px}}
 .just{{display:block;margin-top:5px;font-style:italic;color:#555}}
 .resumen pre{{white-space:pre-wrap;background:#fff;padding:16px;border:1px solid #e0e0e0;font-family:inherit}}
 .kpis{{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}}
 .kpi{{background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:9px 14px;min-width:130px}}
 .kpi b{{display:block;font-size:20px}} .kpi span{{font-size:11px;color:#666}}
</style></head><body>
<h1>Diagnóstico de cumplimiento normativo — Sistema Integrado de Gestión</h1>
<div class="sub">
 Organizaci&oacute;n: {esc(informe.organizacion)} · Generado: {esc(informe.generado)} ·
 Motor: {esc(informe.proveedor)}/{esc(informe.modelo)}
</div>
<div class="kpis">
 <div class="kpi"><b>{m.get('requisitos_evaluados', 0)}</b><span>requisitos evaluados</span></div>
 <div class="kpi"><b>{m.get('tasa_cumplimiento', 0) * 100:.1f}%</b><span>tasa de cumplimiento</span></div>
 <div class="kpi"><b>{m.get('tasa_no_cumplimiento', 0) * 100:.1f}%</b><span>tasa de no cumplimiento</span></div>
 <div class="kpi"><b>{m.get('tasa_trazabilidad_verificada', 0) * 100:.1f}%</b><span>trazabilidad verificada</span></div>
 <div class="kpi"><b>{m.get('latencia_media_s', 0):.1f}s</b><span>latencia media</span></div>
</div>
{resumen}
<table><thead><tr>
<th style="width:12%">Requisito</th><th style="width:24%">Texto del requisito</th>
<th style="width:9%">Veredicto</th><th style="width:5%">Conf.</th>
<th style="width:28%">Evidencia</th><th style="width:22%">Hallazgo / Recomendaci&oacute;n</th>
</tr></thead><tbody>
{''.join(filas)}
</tbody></table>
</body></html>"""
    ruta.write_text(doc, encoding="utf-8")
    return ruta


def exportar_todo(informe: InformeDiagnostico, carpeta: str | Path, prefijo: str = "diagnostico") -> dict[str, Path]:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    return {
        "csv": exportar_csv(informe, carpeta / f"{prefijo}_{sello}.csv"),
        "json": exportar_json(informe, carpeta / f"{prefijo}_{sello}.json"),
        "html": exportar_html(informe, carpeta / f"{prefijo}_{sello}.html"),
    }
