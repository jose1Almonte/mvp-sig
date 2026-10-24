"""Pruebas de humo de la interfaz Streamlit y de los prompts.

No se levanta el servidor de Streamlit: se verifica que el módulo es importable
y que el contrato de prompts es consistente.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mvp_sig.diagnosis.prompts import (
    SISTEMA_AUDITOR,
    VERDICTOS,
    construir_prompt_requisito,
    construir_prompt_sintesis,
)

RAIZ = Path(__file__).resolve().parent.parent
APP_UI = RAIZ / "mvp_sig" / "ui" / "app.py"


class TestPrompts:
    def test_sistema_auditor_no_vacio(self):
        assert SISTEMA_AUDITOR.strip()
        assert len(SISTEMA_AUDITOR) > 100

    def test_veredictos_conocidos(self):
        assert "CUMPLE" in VERDICTOS
        assert "NO_CUMPLE" in VERDICTOS

    def test_prompt_incluye_requisito_y_evidencias(self, requisitos_ejemplo):
        evidencia = {
            "id": "doc1#ab#bloque#0",
            "texto": "La organización debe controlar la información documentada.",
            "puntaje": 0.8,
            "metadatos": {"documento": "Procedimiento_CIL ONG.docx", "pagina": 4},
        }
        prompt = construir_prompt_requisito(
            requisito_texto=requisitos_ejemplo[0].texto,
            requisito_id=requisitos_ejemplo[0].id,
            norma=requisitos_ejemplo[0].norma,
            clausula=requisitos_ejemplo[0].clausula,
            ambito=requisitos_ejemplo[0].ambito,
            evidencias=[evidencia],
        )
        assert requisitos_ejemplo[0].texto in prompt
        assert "E1" in prompt
        assert "Procedimiento_CIL ONG.docx" in prompt
        # El contrato de salida debe pedir JSON.
        assert "JSON" in prompt.upper()

    def test_prompt_de_sintesis(self, requisitos_ejemplo):
        from mvp_sig.diagnosis.engine import ResultadoDiagnostico

        r = ResultadoDiagnostico(
            requisito_id=requisitos_ejemplo[0].id,
            norma=requisitos_ejemplo[0].norma,
            clausula=requisitos_ejemplo[0].clausula,
            ambito=requisitos_ejemplo[0].ambito,
            requisito_texto=requisitos_ejemplo[0].texto,
            veredicto="CUMPLE",
            confianza=0.8,
            confianza_evidence=0.8,
            justificacion="",
            hallazgo="Documentación controlada.",
        )
        prompt = construir_prompt_sintesis([r.to_dict()])
        assert r.requisito_id in prompt
        assert "CUMPLE" in prompt


class TestInterfaz:
    def test_app_existe(self):
        assert APP_UI.exists()

    def test_app_es_sintacticamente_valido(self):
        ast.parse(APP_UI.read_text(encoding="utf-8"))

    def test_app_tiene_las_cinco_pestanas(self):
        contenido = APP_UI.read_text(encoding="utf-8")
        for etiqueta in ("Diagnóstico", "Matriz de trazabilidad", "Indicadores (KPI)", "Evaluación", "Ingesta"):
            assert etiqueta in contenido
