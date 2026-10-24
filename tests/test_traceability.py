"""Pruebas de la matriz de trazabilidad y sus exportaciones."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from mvp_sig.diagnosis.engine import EvidenciaCitada, InformeDiagnostico, ResultadoDiagnostico
from mvp_sig.diagnosis.traceability import (
    COLUMNAS,
    construir_filas,
    exportar_csv,
    exportar_html,
    exportar_json,
    exportar_todo,
)


@pytest.fixture
def informe() -> InformeDiagnostico:
    r1 = ResultadoDiagnostico(
        requisito_id="ISO9001-7.5",
        norma="ISO9001",
        clausula="7.5",
        ambito="calidad",
        requisito_texto="7.5.1 La organización debe controlar la información documentada.",
        veredicto="CUMPLE",
        confianza=0.9,
        confianza_evidence=0.85,
        justificacion="Existe procedimiento de control documental.",
        hallazgo="Documentación controlada.",
        severidad="leve",
        recomendacion="Mantener el listado maestro.",
        modelo="llama3.1:8b",
        proveedor="ollama",
        evidencia=[
            EvidenciaCitada(
                ref="E1",
                fragmento_id="Control de Documentos_CIL ONG.docx#ab12cd#s4#0",
                documento="Control de Documentos_CIL ONG.docx",
                pagina=3,
                seccion="4. Objetivo",
                cita="debe establecer un listado maestro de documentos",
                verificada=True,
                puntaje=0.72,
            ),
            EvidenciaCitada(
                ref="E2",
                fragmento_id="Inventado#ffff#s1#0",
                documento="Inventado.docx",
                pagina=None,
                seccion="",
                cita="cita que no existe en ningun fragmento",
                verificada=False,
                puntaje=0.31,
                motivo_fallo="La cita declarada no aparece textualmente en el fragmento recuperado.",
            ),
        ],
    )
    r2 = ResultadoDiagnostico(
        requisito_id="ISO45001-6.1.2",
        norma="ISO45001",
        clausula="6.1.2",
        ambito="seguridad",
        requisito_texto="6.1.2 La organización debe identificar peligros.",
        veredicto="NO_CUMPLE",
        confianza=0.2,
        confianza_evidence=0.1,
        justificacion="No se encontró matriz de peligros.",
        hallazgo="Falta la identificación de peligros.",
        severidad="grave",
        recomendacion="Elaborar la matriz de peligros.",
        modelo="llama3.1:8b",
        proveedor="ollama",
    )
    return InformeDiagnostico(
        generado="2026-01-15T10:00:00-04:00",
        proveedor="ollama",
        modelo="llama3.1:8b",
        organizacion="METUNIMET",
        resultados=[r1, r2],
        metricas={"requisitos_evaluados": 2, "tasa_cumplimiento": 0.5},
    )


class TestFilas:
    def test_una_fila_por_requisito(self, informe):
        assert len(construir_filas(informe)) == 2

    def test_columnas_completas(self, informe):
        fila = construir_filas(informe)[0]
        assert set(fila) == set(COLUMNAS)

    def test_usa_la_primera_evidencia(self, informe):
        fila = construir_filas(informe)[0]
        assert fila["evidencia_documento"] == "Control de Documentos_CIL ONG.docx"
        assert fila["evidencia_pagina"] == 3

    def test_requisito_sin_evidencia_no_rompe(self, informe):
        fila = construir_filas(informe)[1]
        assert fila["evidencia_documento"] == ""
        assert fila["traza_verificada"] == "NO"


class TestExportaciones:
    def test_exportar_csv(self, informe, tmp_path):
        ruta = exportar_csv(informe, tmp_path / "m.csv")
        assert ruta.exists()
        with ruta.open(encoding="utf-8-sig") as fh:
            filas = list(csv.DictReader(fh))
        assert len(filas) == 2
        assert filas[0]["veredicto"] == "CUMPLE"
        assert filas[0]["traza_verificada"] == "SI"

    def test_exportar_json(self, informe, tmp_path):
        ruta = exportar_json(informe, tmp_path / "m.json")
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["organizacion"] == "METUNIMET"
        assert len(datos["resultados"]) == 2
        assert datos["resultados"][0]["evidencias"][0]["verificada"] is True

    def test_exportar_html(self, informe, tmp_path):
        ruta = exportar_html(informe, tmp_path / "m.html")
        contenido = ruta.read_text(encoding="utf-8")
        assert "<html" in contenido
        assert "METUNIMET" in contenido
        assert "Control de Documentos_CIL ONG.docx" in contenido
        # Las citas deben estar escapadas y presentes.
        assert "listado maestro" in contenido

    def test_exportar_html_escapa_contenido(self, tmp_path):
        r = ResultadoDiagnostico(
            requisito_id="X", norma="ISO9001", clausula="1", ambito="calidad",
            requisito_texto="x", veredicto="NO_CUMPLE", confianza=0.0,
            confianza_evidence=0.0, justificacion="<script>alert(1)</script>",
        )
        informe = InformeDiagnostico(
            generado="2026-01-15T10:00:00-04:00", proveedor="ollama",
            modelo="m", organizacion="Org", resultados=[r],
        )
        ruta = exportar_html(informe, tmp_path / "x.html")
        contenido = ruta.read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in contenido
        assert "&lt;script&gt;" in contenido

    def test_exportar_todo(self, informe, tmp_path):
        rutas = exportar_todo(informe, tmp_path)
        assert set(rutas) == {"csv", "json", "html"}
        for ruta in rutas.values():
            assert Path(ruta).exists()
