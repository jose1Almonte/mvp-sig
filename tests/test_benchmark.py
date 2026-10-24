"""Pruebas del módulo de benchmarking de modelos de lenguaje."""
from __future__ import annotations

import csv
import json

import pytest

from mvp_sig.diagnosis.engine import ResultadoDiagnostico
from mvp_sig.evaluation.benchmark import (
    COLUMNAS_BENCH,
    MODELOS_PROPUESTOS,
    CorridaBenchmark,
    exportar_benchmark_csv,
    exportar_benchmark_json,
    exportar_benchmark_markdown,
)


def _resultado(rid: str, veredicto: str = "CUMPLE", costo: float = 0.0) -> ResultadoDiagnostico:
    return ResultadoDiagnostico(
        requisito_id=rid, norma="ISO9001", clausula="7.5", ambito="calidad",
        requisito_texto="x", veredicto=veredicto, confianza=0.8, confianza_evidence=0.8,
        justificacion="", latencia_s=1.5, tokens_entrada=100, tokens_salida=50, costo_usd=costo,
    )


@pytest.fixture
def corridas() -> list[CorridaBenchmark]:
    c1 = CorridaBenchmark(proveedor="ollama", modelo="llama3.1:8b")
    c1.resultados = [_resultado("A"), _resultado("B", "NO_CUMPLE")]
    c1.segundos = 3.0
    c2 = CorridaBenchmark(proveedor="ollama", modelo="llama3.2:3b")
    c2.resultados = [_resultado("A"), _resultado("B")]
    c2.segundos = 1.0
    c3 = CorridaBenchmark(proveedor="openai", modelo="gpt-4o-mini")
    c3.error = "proveedor o modelo no disponible"
    return [c1, c2, c3]


class TestCorridaBenchmark:
    def test_etiqueta(self):
        c = CorridaBenchmark(proveedor="ollama", modelo="llama3.1:8b")
        assert c.etiqueta == "ollama/llama3.1:8b"

    def test_resumen_con_resultados(self, corridas):
        r = corridas[0].resumen()
        assert r["estado"] == "ok"
        assert r["requisitos_evaluados"] == 2
        assert r["proveedor"] == "ollama"

    def test_resumen_sin_resultados_marca_error(self, corridas):
        r = corridas[2].resumen()
        assert r["estado"] == "error"
        assert r["error"]

    def test_modelos_propuestos_incluye_local_y_nube(self):
        proveedores = {p for p, _ in MODELOS_PROPUESTOS}
        assert "ollama" in proveedores
        assert len(MODELOS_PROPUESTOS) >= 4


class TestExportaciones:
    def test_exportar_csv(self, corridas, tmp_path):
        ruta = exportar_benchmark_csv(corridas, tmp_path / "b.csv")
        with ruta.open(encoding="utf-8-sig") as fh:
            filas = list(csv.DictReader(fh))
        assert len(filas) == 3
        assert list(filas[0]) == COLUMNAS_BENCH

    def test_exportar_markdown(self, corridas, tmp_path):
        ruta = exportar_benchmark_markdown(corridas, tmp_path / "b.md")
        texto = ruta.read_text(encoding="utf-8")
        assert texto.startswith("# Benchmarking")
        assert "llama3.1:8b" in texto
        assert "Ranking por costo-efectividad" in texto
        # El modelo con error no debe aparecer en el ranking.
        assert "gpt-4o-mini" not in texto.split("Ranking por costo-efectividad")[1]

    def test_exportar_json(self, corridas, tmp_path):
        ruta = exportar_benchmark_json(corridas, tmp_path / "b.json")
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert len(datos["carridas"]) == 3
        assert datos["carridas"][2]["error"]
