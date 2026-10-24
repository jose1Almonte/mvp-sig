"""Pruebas de la integración con el orquestador n8n.

La integración es *best-effort*: un orquestador caído nunca debe invalidar
el diagnóstico.  Estas pruebas verifican tanto el contrato del payload como
la robustez del envío.
"""
from __future__ import annotations

import json

import pytest

from mvp_sig.integrations import n8n


class InformeFalso:
    """Informe mínimo con la misma forma que `InformeDiagnostico`."""

    def __init__(self) -> None:
        self.datos = {
            "generado": "2026-10-21T10:00:00Z",
            "proveedor": "ollama",
            "modelo": "llama3.1:8b",
            "organizacion": "METUNIMET",
            "resumen_ejecutivo": "Cumplimiento parcial del SIG.",
            "advertencias": [],
            "metricas": {"cumplimiento_pct": 66.7},
            "resultados": [
                {"veredicto": "CUMPLE", "traza_verificada": True},
                {"veredicto": "NO_CUMPLE", "traza_verificada": True},
                {"veredicto": "NO_CUMPLE", "traza_verificada": False},
            ],
        }

    def to_dict(self) -> dict:
        return self.datos


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
class TestConfiguracion:
    def test_sin_webhook_no_hay_que_notificar(self):
        assert n8n.webhook_configurado("") is False
        assert n8n.webhook_configurado("   ") is False

    def test_con_webhook_hay_que_notificar(self):
        assert n8n.webhook_configurado("http://127.0.0.1:5678/webhook/x") is True


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #
class TestPayload:
    def test_el_payload_lleva_el_informe_y_el_resumen(self):
        p = n8n.payload_diagnostico(InformeFalso())
        assert p["evento"] == "diagnostico.sig"
        assert p["informe"]["organizacion"] == "METUNIMET"
        assert len(p["informe"]["resultados"]) == 3

    def test_el_resumen_agrega_los_veredictos(self):
        p = n8n.payload_diagnostico(InformeFalso())
        r = p["resumen"]
        assert r["veredictos"] == {"CUMPLE": 1, "NO_CUMPLE": 2}
        assert r["total_requisitos"] == 3
        assert r["organizacion"] == "METUNIMET"

    def test_el_resumen_calcula_el_porcentaje_de_trazabilidad(self):
        p = n8n.payload_diagnostico(InformeFalso())
        # 2 de 3 verificaciones de trazabilidad correctas.
        assert p["resumen"]["trazabilidad_verificada_pct"] == pytest.approx(66.67, abs=0.01)

    def test_el_payload_es_serializable(self):
        p = n8n.payload_diagnostico(InformeFalso())
        json.dumps(p)  # no debe lanzar


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #
class TestEnvio:
    def test_sin_url_no_intenta_nada(self):
        r = n8n.notificar(InformeFalso(), url="")
        assert r.enviado is False
        assert "webhook" in r.detalle.lower()

    def test_un_orquestador_inalcanzable_no_rompe_el_diagnostico(self):
        # Puerto cerrado: el error debe capturarse y devolverse.
        r = n8n.notificar(InformeFalso(), url="http://127.0.0.1:9/webhook/x", timeout=2)
        assert r.enviado is False
        assert r.codigo is None
        assert r.detalle

    def test_una_url_mal_formada_no_rompe_el_diagnostico(self):
        r = n8n.notificar(InformeFalso(), url="no-es-una-url", timeout=2)
        assert r.enviado is False
        assert r.detalle


# --------------------------------------------------------------------------- #
# Flujo exportable
# --------------------------------------------------------------------------- #
class TestFlujoExportable:
    def test_el_flujo_existe_y_es_json_valido(self):
        assert n8n.ruta_flujo().exists(), "Falta workflows/diagnostico_sig_n8n.json"
        datos = json.loads(n8n.ruta_flujo().read_text(encoding="utf-8"))
        assert datos["nodes"]
        assert datos["connections"]

    def test_la_validacion_del_flujo_es_correcta(self):
        r = n8n.validar_flujo()
        assert r["ok"] is True, r.get("detalle")
        assert r["nodos"]

    def test_el_flujo_tiene_webhook_para_recibir_la_orden(self):
        datos = json.loads(n8n.ruta_flujo().read_text(encoding="utf-8"))
        tipos = [n["type"] for n in datos["nodes"]]
        assert "n8n-nodes-base.webhook" in tipos
        assert "n8n-nodes-base.httpRequest" in tipos

    def test_el_flujo_llama_al_endpoint_de_diagnostico(self):
        datos = json.loads(n8n.ruta_flujo().read_text(encoding="utf-8"))
        urls = [
            n["parameters"].get("url", "")
            for n in datos["nodes"]
            if n["type"] == "n8n-nodes-base.httpRequest"
        ]
        assert any("/diagnostico" in u for u in urls)

    def test_todas_las_conexiones_apuntan_a_nodos_existentes(self):
        datos = json.loads(n8n.ruta_flujo().read_text(encoding="utf-8"))
        nombres = {n["name"] for n in datos["nodes"]}
        for origen, salidas in datos["connections"].items():
            assert origen in nombres, f"origen inexistente: {origen}"
            for rama in salidas.get("main", []):
                for enlace in rama:
                    assert enlace["node"] in nombres, f"destino inexistente: {enlace['node']}"


# --------------------------------------------------------------------------- #
# Integración con el pipeline
# --------------------------------------------------------------------------- #
class TestPipeline:
    def test_el_pipeline_avisa_cuando_no_hay_webhook(self, store, llm):
        from mvp_sig.pipeline import Pipeline

        p = Pipeline(store=store, llm=llm)
        resultado = p.notificar_n8n(InformeFalso())
        assert resultado["enviado"] is False
        assert any("N8N_WEBHOOK" in w for w in p.runtime.warnings)
