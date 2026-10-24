"""Benchmarking de modelos de lenguaje (objetivo específico 3.3.c).

Ejecuta el mismo conjunto de requisitos sobre varios modelos y compara:
    respuesta correcta (veredicto), latencia, tokens, coste y trazabilidad.

Genera un informe comparativo en CSV y Markdown, que es el insumo del
capítulo de resultados del anteproyecto.
"""
from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from mvp_sig.diagnosis.engine import MotorDiagnostico, ResultadoDiagnostico
from mvp_sig.knowledge.requirements import Requisito
from mvp_sig.knowledge.vectorstore import VectorStore
from mvp_sig.llm.provider import crear_proveedor, proveedores_disponibles

# Modelos de la comparativa del anteproyecto (objetivo 3.3.c).
# La lista canónica, con precios de referencia y estado, vive en
# `mvp_sig.evaluation.costos`; aquí sólo se declara el orden de ejecución.
MODELOS_PROPUESTOS = [
    ("ollama", "llama3.1:8b"),
    ("ollama", "llama3.2"),
    ("ollama", "gpt-oss:120b-cloud"),
    ("ollama", "deepseek-v3"),
    ("ollama", "mistral-large"),
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4o"),
    ("anthropic", "claude-3-5-sonnet-latest"),
    ("anthropic", "claude-3-5-opus-latest"),
]


@dataclass
class CorridaBenchmark:
    """Una ejecución de un modelo sobre el conjunto de requisitos."""

    proveedor: str
    modelo: str
    resultados: list[ResultadoDiagnostico] = field(default_factory=list)
    error: str | None = None
    segundos: float = 0.0

    @property
    def etiqueta(self) -> str:
        return f"{self.proveedor}/{self.modelo}"

    def resumen(self) -> dict:
        from mvp_sig.evaluation.metrics import evaluar_diagnostico

        if not self.resultados:
            return {
                "proveedor": self.proveedor,
                "modelo": self.modelo,
                "estado": "error",
                "error": self.error or "sin resultados",
            }
        m = evaluar_diagnostico(self.resultados)
        m.update(
            {
                "proveedor": self.proveedor,
                "modelo": self.modelo,
                "estado": "ok",
                "segundos_total": round(self.segundos, 2),
                "segundos_por_requisito": round(self.segundos / len(self.resultados), 2),
                "tokens_promedio_entrada": m.get("tokens_entrada", 0) / len(self.resultados),
                "tokens_promedio_salida": m.get("tokens_salida", 0) / len(self.resultados),
                "costo_usd_total": round(
                    sum(r.costo_usd if hasattr(r, "costo_usd") else 0.0 for r in self.resultados), 6
                ),
            }
        )
        return m


def motivo_no_disponible(proveedor: str, modelo: str) -> str:
    """Explica por qué un modelo de la comparativa no puede ejecutarse aquí.

    Distingue las tres causas reales (modelo no instalado, clave de API
    ausente y proveedor caído) para que el informe no presente como un
    fallo del sistema lo que es una limitación del entorno.
    """
    from mvp_sig.settings import ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY

    claves = {
        "openai": OPENAI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "openrouter": OPENROUTER_API_KEY,
    }
    if proveedor in claves:
        if not claves[proveedor]:
            return f"falta la clave de API ({proveedor.upper()}_API_KEY)"
        return f"la API de {proveedor} no responde para el modelo '{modelo}'"
    if proveedor == "ollama":
        return f"el modelo '{modelo}' no está instalado en Ollama"
    return f"el proveedor '{proveedor}' no está operativo"


def ejecutar_benchmark(
    store: VectorStore,
    requisitos: list[Requisito],
    modelos: list[tuple[str, str]] | None = None,
    *,
    top_k: int = 5,
    progreso=None,
) -> list[CorridaBenchmark]:
    """Ejecuta el diagnóstico con cada modelo y devuelve las corridas."""
    modelos = modelos or MODELOS_PROPUESTOS
    corridas: list[CorridaBenchmark] = []
    import time

    for proveedor, modelo in modelos:
        print(f"\n=== Benchmark: {proveedor}/{modelo} ===", flush=True)
        corrida = CorridaBenchmark(proveedor=proveedor, modelo=modelo)
        try:
            llm = crear_proveedor(proveedor, modelo)
            if not llm.disponible():
                corrida.error = motivo_no_disponible(proveedor, modelo)
                print(f"  [skip] {corrida.error}", flush=True)
                corridas.append(corrida)
                continue
            motor = MotorDiagnostico(store, llm, top_k=top_k)
            inicio = time.perf_counter()
            for i, req in enumerate(requisitos, start=1):
                res = motor.evaluar_requisito(req)
                corrida.resultados.append(res)
                if progreso:
                    progreso(proveedor, modelo, i, len(requisitos), res)
                else:
                    print(
                        f"  [{i:>3}/{len(requisitos)}] {req.id:<22} {res.veredicto:<14}"
                        f"traza={'S' if res.traza_verificada else 'N'} ({res.latencia_s:.1f}s)",
                        flush=True,
                    )
            corrida.segundos = time.perf_counter() - inicio
        except Exception as exc:  # noqa: BLE001
            corrida.error = f"{type(exc).__name__}: {exc}"
        corridas.append(corrida)
    return corridas


# --------------------------------------------------------------------------- #
# Informes
# --------------------------------------------------------------------------- #
COLUMNAS_BENCH = [
    "proveedor",
    "modelo",
    "estado",
    "requisitos_evaluados",
    "tasa_cumplimiento",
    "tasa_no_cumplimiento",
    "tasa_trazabilidad_verificada",
    "tasa_citas_verificadas",
    "confianza_media",
    "latencia_media_s",
    "segundos_por_requisito",
    "tokens_promedio_entrada",
    "tokens_promedio_salida",
    "costo_usd_total",
    "acuerdo_con_otros",
]


def exportar_benchmark_csv(corridas: list[CorridaBenchmark], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    filas = []
    for c in corridas:
        r = c.resumen()
        filas.append({col: r.get(col, "") for col in COLUMNAS_BENCH})
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNAS_BENCH)
        writer.writeheader()
        writer.writerows(filas)
    return ruta


def exportar_benchmark_markdown(corridas: list[CorridaBenchmark], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = [
        "# Benchmarking de modelos de lenguaje",
        "",
        "Comparación de motores sobre el mismo conjunto de requisitos normativos.",
        "Métricas de costo-efectividad exigidas por el objetivo específico 3.3.c.",
        "",
        "| Proveedor | Modelo | Estado | Requisitos | Cumplim. | No cumplim. | Trazab. | "
        "Citas verif. | Latencia prom. | Tokens in | Tokens out | Coste USD |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in corridas:
        r = c.resumen()
        lineas.append(
            "| {proveedor} | {modelo} | {estado} | {req} | {cump} | {nocump} | {traz} | "
            "{citas} | {lat}s | {tin} | {tout} | {coste} |".format(
                proveedor=r.get("proveedor", "-"),
                modelo=r.get("modelo", "-"),
                estado=r.get("estado", "-"),
                req=r.get("requisitos_evaluados", "-"),
                cump=_pct(r.get("tasa_cumplimiento")),
                nocump=_pct(r.get("tasa_no_cumplimiento")),
                traz=_pct(r.get("tasa_trazabilidad_verificada")),
                citas=_pct(r.get("tasa_citas_verificadas")),
                lat=r.get("latencia_media_s", "-"),
                tin=int(r.get("tokens_promedio_entrada", 0) or 0),
                tout=int(r.get("tokens_promedio_salida", 0) or 0),
                coste=r.get("costo_usd_total", 0),
            )
        )
    lineas += ["", "## Ranking por costo-efectividad", ""]
    lineas.append(
        "Índice = trazabilidad verificada / (latencia × (1 + coste USD de la corrida)). "
        "Como los modelos ejecutados en local tienen coste de API nulo, el factor de "
        "coste no altera el orden entre ellos: el ranking mide trazabilidad por "
        "segundo de cómputo."
    )
    lineas.append("")
    ranking = []
    for c in corridas:
        r = c.resumen()
        if r.get("estado") != "ok":
            continue
        traz = r.get("tasa_trazabilidad_verificada", 0) or 0
        lat = r.get("latencia_media_s", 1) or 1
        coste = r.get("costo_usd_total", 0) or 0
        # Índice: trazabilidad por segundo de cómputo, penalizado por el coste.
        ranking.append((traz / lat / (1.0 + coste), c.etiqueta, traz, lat))
    ranking.sort(reverse=True)
    lineas.append("| # | Modelo | Índice costo-efectividad | Trazabilidad | Latencia (s) |")
    lineas.append("|---|---|---|---|---|")
    for i, (idx, etiqueta, traz, lat) in enumerate(ranking, start=1):
        lineas.append(f"| {i} | {etiqueta} | {idx:.4f} | {_pct(traz)} | {lat} |")
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


def exportar_benchmark_json(corridas: list[CorridaBenchmark], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        "carridas": [
            {
                "proveedor": c.proveedor,
                "modelo": c.modelo,
                "error": c.error,
                "resumen": c.resumen(),
                "resultados": [r.to_dict() for r in c.resultados],
            }
            for c in corridas
        ]
    }
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def exportar_costo_efectividad(
    corridas: list[CorridaBenchmark],
    ruta: str | Path,
    *,
    requisitos_totales: int = 154,
) -> Path:
    """Escribe el informe de costo-efectividad (pregunta de investigación nº 4).

    Incluye tanto los modelos ejecutados (medición) como los que no pudieron
    ejecutarse en este entorno (coste estimado con el mismo consumo de tokens).
    """
    from mvp_sig.evaluation.costos import filas_costo_efectividad, informe_markdown

    filas = filas_costo_efectividad(corridas, requisitos_totales=requisitos_totales)
    tokens_ref = None
    consumos = [
        (c.resumen().get("tokens_promedio_entrada", 0), c.resumen().get("tokens_promedio_salida", 0))
        for c in corridas
        if c.resumen().get("estado") == "ok"
    ]
    if consumos:
        tokens_ref = (
            sum(t[0] for t in consumos) / len(consumos),
            sum(t[1] for t in consumos) / len(consumos),
        )
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        informe_markdown(filas, requisitos_totales=requisitos_totales, tokens_referencia=tokens_ref),
        encoding="utf-8",
    )
    return ruta


def _pct(valor) -> str:
    if valor in (None, ""):
        return "-"
    try:
        return f"{float(valor) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def inventario_proveedores() -> list[dict]:
    return proveedores_disponibles()


def latencia_mediana(valores: list[float]) -> float:
    return statistics.median(valores) if valores else 0.0
