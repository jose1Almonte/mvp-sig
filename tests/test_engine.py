"""Pruebas del motor de diagnóstico y, sobre todo, de la verificación de
trazabilidad (*grounding*): la contribución metodológica central del MVP.

La regla que se protege aquí es: **una cita que el modelo declara pero que no
existe en el fragmento recuperado invalida el veredicto de cumplimiento**.
"""
from __future__ import annotations

import json

import pytest

from mvp_sig.diagnosis.engine import (
    EvidenciaCitada,
    InformeDiagnostico,
    MotorDiagnostico,
    ResultadoDiagnostico,
    calcular_metricas,
)
from mvp_sig.knowledge.vectorstore import VectorStore
from tests.conftest import LLMFalso

# Cita que SÍ existe en el fragmento de evidencia cargado en el fixture.
CITA_VALIDA = "debe establecer un listado maestro de documentos"
# Cita que NO existe en ningún fragmento recuperado.
CITA_FALSA = "el gerente general firmo el acta de aprobacion presupuestaria"


def _motor(store, llm) -> MotorDiagnostico:
    return MotorDiagnostico(store, llm, top_k=5, score_min=0.0)


class TestVerificacionDeCitas:
    def test_cita_literal_se_marca_verificada(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.9,
                "confianza_evidence": 0.85,
                "justificacion": "Existe procedimiento de control documental.",
                "hallazgo": "Documentación controlada.",
                "severidad": "leve",
                "recomendacion": "Mantener el listado maestro actualizado.",
                "evidencias": [
                    {
                        "ref": "E1",
                        "documento": "Control de Documentos_CIL ONG.docx",
                        "cita": CITA_VALIDA,
                    }
                ],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])

        assert res.veredicto == "CUMPLE"
        assert len(res.evidencia) == 1
        assert res.evidencia[0].verificada is True
        assert res.traza_verificada is True

    def test_cita_inventada_se_marca_no_verificada(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.95,
                "confianza_evidence": 0.9,
                "justificacion": "La organización lo cumple.",
                "evidencias": [
                    {"ref": "E1", "documento": "Inventado.docx", "cita": CITA_FALSA}
                ],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])

        assert res.evidencia[0].verificada is False
        assert res.evidencia[0].motivo_fallo
        assert res.traza_verificada is False

    def test_cita_inventada_degrada_el_veredicto(self, store_con_evidencias, requisitos_ejemplo):
        """Éste es el comportamiento metodológico clave."""
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.95,
                "confianza_evidence": 0.9,
                "justificacion": "La organización lo cumple.",
                "evidencias": [
                    {"ref": "E1", "documento": "Inventado.docx", "cita": CITA_FALSA}
                ],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])

        assert res.veredicto == "CUMPLE_PARCIAL"
        assert res.confianza <= 0.4
        assert "trazabilidad" in res.justificacion.lower()

    def test_referencia_inexistente_es_no_verificada(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.9,
                "justificacion": "Cita a evidencia que no se recuperó.",
                "evidencias": [{"ref": "E9", "documento": "x.docx", "cita": "texto"}],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])

        assert res.evidencia[0].verificada is False
        assert res.evidencia[0].fragmento_id == ""
        assert res.veredicto == "CUMPLE_PARCIAL"

    def test_sin_evidencias_un_cumple_se_degrada(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.9,
                "justificacion": "Afirma cumplimiento sin citar nada.",
                "evidencias": [],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])

        assert res.veredicto == "NO_CUMPLE"
        assert res.confianza <= 0.4

    def test_una_cita_valida_entre_inventadas_sostiene_el_veredicto(
        self, store_con_evidencias, requisitos_ejemplo
    ):
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.9,
                "justificacion": "Una cita real y otra inventada.",
                "evidencias": [
                    {"ref": "E1", "documento": "Control de Documentos_CIL ONG.docx", "cita": CITA_VALIDA},
                    {"ref": "E2", "documento": "Inventado.docx", "cita": CITA_FALSA},
                ],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])

        assert any(e.verificada for e in res.evidencia)
        assert res.traza_verificada is True
        assert res.veredicto == "CUMPLE"


class TestRobustezDelMotor:
    def test_salida_no_json_no_rompe(self, store_con_evidencias, requisitos_ejemplo):
        from mvp_sig.llm.provider import LLMResponse

        class LLMQuebrado(LLMFalso):
            def _chat(self, sistema, usuario, json_modo):
                return LLMResponse(
                    texto="lo siento, no puedo responder",
                    modelo="x",
                    proveedor="falso",
                )

        motor = _motor(store_con_evidencias, LLMQuebrado())
        res = motor.evaluar_requisito(requisitos_ejemplo[0])
        assert res.veredicto == "NO_CUMPLE"
        assert res.justificacion

    def test_error_del_proveedor_se_registra(self, store_con_evidencias, requisitos_ejemplo):
        from mvp_sig.llm.provider import LLMResponse

        class LLMErrado(LLMFalso):
            def _chat(self, sistema, usuario, json_modo):
                raise RuntimeError("servidor caído")

        motor = _motor(store_con_evidencias, LLMErrado())
        res = motor.evaluar_requisito(requisitos_ejemplo[0])
        assert res.error is not None
        assert "servidor caído" in res.error

    def test_veredicto_desconocido_se_normaliza(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso({"veredicto": "inventado", "confianza": 0.5, "justificacion": "x"})
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])
        assert res.veredicto == "NO_CUMPLE"

    def test_veredicto_con_espacios_se_normaliza(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso({"veredicto": "cumple parcial", "confianza": 0.5, "justificacion": "x"})
        motor = _motor(store_con_evidencias, llm)
        res = motor.evaluar_requisito(requisitos_ejemplo[0])
        assert res.veredicto == "CUMPLE_PARCIAL"


class TestCorridaCompleta:
    def test_diagnosticar_produce_informe_con_metricas(
        self, store_con_evidencias, requisitos_ejemplo
    ):
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.8,
                "confianza_evidence": 0.8,
                "justificacion": "Procedimiento disponible.",
                "evidencias": [
                    {
                        "ref": "E1",
                        "documento": "Control de Documentos_CIL ONG.docx",
                        "cita": CITA_VALIDA,
                    }
                ],
            }
        )
        motor = _motor(store_con_evidencias, llm)
        informe = motor.diagnosticar(requisitos_ejemplo, con_resumen=False)

        assert isinstance(informe, InformeDiagnostico)
        assert len(informe.resultados) == 2
        m = informe.metricas
        assert m["requisitos_evaluados"] == 2
        assert 0.0 <= m["tasa_cumplimiento"] <= 1.0
        assert "por_norma" in m and "por_ambito" in m

    def test_serializacion_a_dict(self, store_con_evidencias, requisitos_ejemplo):
        llm = LLMFalso({"veredicto": "NO_CUMPLE", "confianza": 0.3, "justificacion": "x"})
        motor = _motor(store_con_evidencias, llm)
        informe = motor.diagnosticar(requisitos_ejemplo, con_resumen=False)
        # Debe ser serializable a JSON (lo exige la API y la exportación).
        json.dumps(informe.to_dict(), ensure_ascii=False)


class TestMetricas:
    def test_metricas_de_lista_vacia(self):
        assert calcular_metricas([]) == {}

    def test_tasa_de_cumplimiento(self):
        r1 = ResultadoDiagnostico(
            requisito_id="A", norma="ISO9001", clausula="7.5", ambito="calidad",
            requisito_texto="x", veredicto="CUMPLE", confianza=0.9,
            confianza_evidence=0.9, justificacion="",
        )
        r2 = ResultadoDiagnostico(
            requisito_id="B", norma="ISO9001", clausula="7.5", ambito="calidad",
            requisito_texto="x", veredicto="NO_CUMPLE", confianza=0.2,
            confianza_evidence=0.2, justificacion="",
        )
        m = calcular_metricas([r1, r2])
        assert m["requisitos_evaluados"] == 2
        assert m["tasa_cumplimiento"] == 0.5
        assert m["tasa_no_cumplimiento"] == 0.5
        assert m["distribucion_veredictos"]["CUMPLE"] == 1
