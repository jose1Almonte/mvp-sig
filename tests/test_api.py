"""Pruebas de la API REST y de la base vectorial."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mvp_sig.api.main import app
from mvp_sig.api.schemas import (
    DiagnosticoResponse,
    EvidenciaOut,
    ResultadoOut,
)
from mvp_sig.diagnosis.engine import InformeDiagnostico, ResultadoDiagnostico
from mvp_sig.knowledge.vectorstore import VectorStore, filtro_ambito
from tests.conftest import LLMFalso


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(app)


class TestEndpointsBasicos:
    def test_health(self, cliente):
        r = cliente.get("/health")
        assert r.status_code == 200
        assert r.json()["estado"] == "ok"

    def test_normas(self, cliente):
        r = cliente.get("/normas")
        assert r.status_code == 200
        datos = r.json()
        assert len(datos) == 3
        assert {n["key"] for n in datos} == {"ISO9001", "ISO14001", "ISO45001"}

    def test_proveedores(self, cliente):
        r = cliente.get("/proveedores")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_estado(self, cliente):
        r = cliente.get("/estado")
        assert r.status_code == 200
        datos = r.json()
        assert "base_vectorial" in datos
        assert "llm" in datos

    def test_requisitos(self, cliente):
        r = cliente.get("/requisitos", params={"limite": 5})
        assert r.status_code == 200
        datos = r.json()
        assert "requisitos" in datos
        assert len(datos["requisitos"]) <= 5

    def test_requisitos_filtrados_por_norma(self, cliente):
        r = cliente.get("/requisitos", params={"norma": "ISO45001", "limite": 20})
        assert r.status_code == 200
        for req in r.json()["requisitos"]:
            assert req["norma"] == "ISO45001"

    def test_matriz_csv_sin_diagnostico_da_404(self, cliente):
        r = cliente.get("/diagnostico/matriz.csv")
        assert r.status_code == 404

    def test_informe_html_sin_diagnostico_da_404(self, cliente):
        r = cliente.get("/diagnostico/informe.html")
        assert r.status_code == 404

    def test_ingesta_con_ruta_inexistente(self, cliente):
        r = cliente.post("/ingesta", json={"raiz": "C:/no/existe/este/path"})
        assert r.status_code == 400

    def test_openapi_es_valido(self, cliente):
        r = cliente.get("/openapi.json")
        assert r.status_code == 200
        assert "paths" in r.json()


class TestVectorStore:
    def test_indexar_y_contar(self, store):
        n = store.indexar(
            VectorStore.EVIDENCIAS,
            ["a#1", "b#2"],
            ["primer documento", "segundo documento"],
            [
                {"documento": "a.docx", "ambito": "calidad", "ambitos": "calidad"},
                {"documento": "b.docx", "ambito": "ambiente", "ambitos": "ambiente"},
            ],
            recrear=True,
            verbose=False,
        )
        assert n == 2
        assert store.contar(VectorStore.EVIDENCIAS) == 2

    def test_buscar_devuelve_fragmentos(self, store_con_evidencias):
        frags = store_con_evidencias.buscar(
            VectorStore.EVIDENCIAS, "listado maestro de documentos", k=3
        )
        assert frags
        assert all(f.texto for f in frags)
        assert all(0.0 <= f.puntaje <= 1.0 for f in frags)

    def test_buscar_coleccion_vacia(self, store):
        assert store.buscar(VectorStore.EVIDENCIAS, "cualquier cosa", k=3) == []

    def test_filtro_por_ambito(self, store):
        store.indexar(
            VectorStore.EVIDENCIAS,
            ["a#1", "b#2"],
            ["documento de calidad", "documento ambiental"],
            [
                {"documento": "a.docx", "ambito": "calidad", "ambitos": "calidad"},
                {"documento": "b.docx", "ambito": "ambiente", "ambitos": "ambiente"},
            ],
            recrear=True,
            verbose=False,
        )
        frags = store.buscar(
            VectorStore.EVIDENCIAS, "documento", k=5, where=filtro_ambito(["calidad"])
        )
        assert frags
        assert all(f.metadatos["ambito"] == "calidad" for f in frags)

    def test_filtro_ambitos_aceptados(self, store):
        store.indexar(
            VectorStore.EVIDENCIAS,
            ["a#1", "b#2"],
            ["documento integral", "documento de seguridad"],
            [
                {"documento": "a.docx", "ambito": "integral", "ambitos": "integral|calidad"},
                {"documento": "b.docx", "ambito": "seguridad", "ambitos": "seguridad"},
            ],
            recrear=True,
            verbose=False,
        )
        frags = store.buscar(
            VectorStore.EVIDENCIAS,
            "documento",
            k=5,
            ambitos_aceptados={"integral", "calidad"},
        )
        assert frags
        assert all("seguridad" not in f.metadatos["ambitos"] for f in frags)

    def test_listar(self, store_con_evidencias):
        filas = store_con_evidencias.listar(VectorStore.EVIDENCIAS)
        assert len(filas) == 2
        assert all("id" in f and "metadatos" in f for f in filas)

    def test_reiniciar(self, store):
        store.indexar(
            VectorStore.EVIDENCIAS, ["a#1"], ["texto"], [{"documento": "a"}],
            recrear=True, verbose=False,
        )
        assert store.contar(VectorStore.EVIDENCIAS) == 1
        store.reiniciar(VectorStore.EVIDENCIAS)
        assert store.contar(VectorStore.EVIDENCIAS) == 0


def test_filtro_ambito_un_solo_valor():
    assert filtro_ambito(["calidad"]) == {"ambito": "calidad"}


def test_filtro_ambito_varios_valores():
    assert filtro_ambito(["calidad", "ambiente"]) == {"ambito": {"$in": ["calidad", "ambiente"]}}


def test_filtro_ambito_vacio():
    assert filtro_ambito([]) is None


# --------------------------------------------------------------------------- #
# Contrato entre el motor de diagnóstico y los esquemas de la API.
#
# El motor serializa con `ResultadoDiagnostico.to_dict()`; la API valida con
# `ResultadoOut`. Si los nombres de campo divergen, FastAPI responde 500 en
# `POST /diagnostico` aunque el diagnóstico se haya ejecutado bien. Estos
# tests blindan esa frontera.
# --------------------------------------------------------------------------- #
class TestContratoEsquemaAPI:
    @staticmethod
    def _resultado_completo() -> ResultadoDiagnostico:
        return ResultadoDiagnostico(
            requisito_id="ISO9001-7.5",
            norma="ISO9001",
            clausula="7.5",
            ambito="calidad",
            requisito_texto="7.5.1 La organización debe controlar la información documentada.",
            veredicto="CUMPLE",
            confianza=0.88,
            confianza_evidence=0.81,
            justificacion="Existe procedimiento de control documental.",
            evidencia=[],
            hallazgo="Documentación controlada.",
            severidad="leve",
            recomendacion="Mantener el listado maestro actualizado.",
            fragmentos_recuperados=["doc0#hash#bloque#0"],
            mejor_puntaje=0.77,
            latencia_s=1.25,
            tokens_entrada=1234,
            tokens_salida=321,
            costo_usd=0.000123,
            modelo="llama3.1:8b",
            proveedor="ollama",
            error=None,
        )

    def test_to_dict_del_motor_valida_contra_el_esquema(self):
        datos = self._resultado_completo().to_dict()
        salida = ResultadoOut(**datos)
        assert salida.requisito_id == "ISO9001-7.5"
        assert salida.veredicto == "CUMPLE"
        assert salida.confianza_evidence == 0.81
        assert salida.tokens_entrada == 1234
        assert salida.tokens_salida == 321
        assert salida.costo_usd == 0.000123
        assert salida.fragmentos_recuperados == ["doc0#hash#bloque#0"]

    def test_el_esquema_expone_evidencias_en_plural(self):
        """`to_dict()` produce 'evidencias'; el esquema debe usar el mismo nombre."""
        datos = self._resultado_completo().to_dict()
        assert "evidencias" in datos
        assert "evidencia" not in datos
        assert "evidencias" in ResultadoOut.model_fields

    def test_evidencia_citada_valida_contra_el_esquema(self):
        from mvp_sig.diagnosis.engine import EvidenciaCitada

        ev = EvidenciaCitada(
            ref="E1",
            fragmento_id="doc0#hash#bloque#0",
            documento="Control de Documentos_CIL ONG.docx",
            pagina=3,
            seccion="4. Objetivo",
            cita="debe establecer un listado maestro de documentos",
            verificada=True,
            puntaje=0.82,
        )
        salida = EvidenciaOut(**ev.to_dict())
        assert salida.ref == "E1"
        assert salida.fragmento_id == "doc0#hash#bloque#0"
        assert salida.verificada is True

    def test_informe_completo_valida_contra_el_esquema(self):
        informe = InformeDiagnostico(
            generado="2026-10-21T00:00:00",
            proveedor="ollama",
            modelo="llama3.1:8b",
            organizacion="METUNIMET",
            resultados=[self._resultado_completo()],
            resumen_ejecutivo="Resumen.",
            advertencias=[],
            metricas={"requisitos_evaluados": 1},
        )
        salida = DiagnosticoResponse(**informe.to_dict())
        assert len(salida.resultados) == 1
        assert salida.resultados[0].evidencias == []

    def test_veredicto_fuera_de_vocabulario_es_rechazado(self):
        from pydantic import ValidationError

        datos = self._resultado_completo().to_dict()
        datos["veredicto"] = "INVENTADO"
        with pytest.raises(ValidationError):
            ResultadoOut(**datos)


class TestDiagnosticoEndToEnd:
    """El endpoint real de diagnóstico, con proveedor de lenguaje simulado."""

    @pytest.fixture
    def pipeline_falso(self, store_con_evidencias, requisitos_ejemplo, monkeypatch):
        from mvp_sig.pipeline import Pipeline

        # Se indexan los requisitos de ejemplo para no depender del catálogo real.
        store_con_evidencias.indexar(
            VectorStore.REQUISITOS,
            [r.id for r in requisitos_ejemplo],
            [r.texto for r in requisitos_ejemplo],
            [r.to_metadata() for r in requisitos_ejemplo],
            recrear=True,
            verbose=False,
        )
        llm = LLMFalso(
            {
                "veredicto": "CUMPLE",
                "confianza": 0.9,
                "confianza_evidence": 0.85,
                "justificacion": "Existe procedimiento de control documental.",
                "evidencias": [
                    {
                        "ref": "E1",
                        "documento": "Control de Documentos_CIL ONG.docx",
                        "cita": "debe establecer un listado maestro de documentos",
                    }
                ],
            }
        )
        pipeline = Pipeline(store=store_con_evidencias, llm=llm)
        monkeypatch.setattr("mvp_sig.api.main.get_pipeline", lambda: pipeline)
        return pipeline

    def test_post_diagnostico_devuelve_200(self, cliente, pipeline_falso):
        r = cliente.post("/diagnostico", json={"limite": 2, "con_resumen": False})
        assert r.status_code == 200, r.text
        datos = r.json()
        assert len(datos["resultados"]) == 2
        assert datos["resultados"][0]["evidencias"]
        assert datos["resultados"][0]["confianza_evidence"] > 0

    def test_post_diagnostico_persiste_el_ultimo_informe(self, cliente, pipeline_falso):
        cliente.post("/diagnostico", json={"limite": 2, "con_resumen": False})
        r = cliente.get("/diagnostico/ultimo")
        assert r.status_code == 200
        assert len(r.json()["resultados"]) == 2

