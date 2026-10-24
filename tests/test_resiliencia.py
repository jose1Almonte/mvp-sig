"""Pruebas de la capa de resiliencia HTTP y del volcado incremental.

Estas pruebas protegen dos comportamientos que hicieron que la corrida de
ingesta del corpus completo pareciera "muerta" sin llegar a producir error:

* la resolución de ``localhost`` a IPv6 loopback (``::1``), que en Windows
  deja el socket colgado en ``SYN_SENT`` cuando el servidor sólo escucha en
  ``127.0.0.1``;
* el volcado por lotes, que antes podía saltarse un límite de lote y dejar
  documentos sin indexar en la base vectorial.
"""
from __future__ import annotations

import pytest

from mvp_sig.utils.http import (
    crear_sesion,
    normalizar_url,
    pedir,
    timeout_conectivo,
)


class TestNormalizacionDeUrl:
    def test_localhost_pasa_a_ipv4(self):
        assert normalizar_url("http://localhost:11434") == "http://127.0.0.1:11434"

    def test_localhost_sin_puerto(self):
        assert normalizar_url("http://localhost") == "http://127.0.0.1"

    def test_conserva_el_puerto_y_la_ruta(self):
        assert (
            normalizar_url("http://localhost:11434/api/embed")
            == "http://127.0.0.1:11434/api/embed"
        )

    def test_no_toca_otros_hosts(self):
        assert normalizar_url("http://ollama:11434") == "http://ollama:11434"
        assert (
            normalizar_url("https://api.openai.com/v1")
            == "https://api.openai.com/v1"
        )

    def test_no_toca_una_ip_literal(self):
        assert normalizar_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"

    def test_url_vacia(self):
        assert normalizar_url("") == ""


class TestSesion:
    def test_la_sesion_normaliza_la_url_base(self):
        sesion = crear_sesion("http://localhost:11434")
        assert sesion.normalized_base_url == "http://127.0.0.1:11434"

    def test_timeout_diferenciado(self):
        assert timeout_conectivo(5, 60) == (5, 60)


class TestPeticionConReintentos:
    def test_reintenta_y_termina_con_error_explicito(self, monkeypatch):
        """Un servicio caído debe fallar rápido y con la URL en el mensaje."""
        import requests

        sesion = crear_sesion("http://127.0.0.1:11434", reintentos=3, backoff=0.0)
        intentos = {"n": 0}

        class RespuestaFalsa:
            status_code = 500

            def raise_for_status(self):
                raise requests.exceptions.HTTPError("500 Server Error")

        def request_falso(*args, **kwargs):
            intentos["n"] += 1
            return RespuestaFalsa()

        monkeypatch.setattr(sesion, "request", request_falso)
        monkeypatch.setattr("mvp_sig.utils.http.time.sleep", lambda _s: None)

        with pytest.raises(RuntimeError) as exc:
            pedir(sesion, "POST", "/api/embed", json={"model": "x"})
        assert intentos["n"] == 3
        assert "127.0.0.1:11434" in str(exc.value)

    def test_devuelve_la_respuesta_si_funciona(self, monkeypatch):
        sesion = crear_sesion("http://127.0.0.1:11434")

        class RespuestaOk:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"embeddings": [[0.1, 0.2]]}

        monkeypatch.setattr(sesion, "request", lambda *a, **k: RespuestaOk())
        r = pedir(sesion, "POST", "/api/embed", json={"model": "x"})
        assert r.json()["embeddings"] == [[0.1, 0.2]]


class TestVolcadoIncremental:
    """El volcado por lotes no debe dejar documentos sin indexar."""

    def test_lote_menor_al_umbral_tambien_se_vuelca(self, tmp_path, store, llm):
        from mvp_sig.pipeline import Pipeline

        docx = pytest.importorskip("docx")
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        for i in range(3):
            d = docx.Document()
            d.add_paragraph(f"Procedimiento numero {i} del sistema integrado de gestion.")
            d.save(str(corpus / f"proc{i}.docx"))

        pipeline = Pipeline(store=store, llm=llm, catalogo_dir=tmp_path / "catalogo")
        resultado = pipeline.ingerir(corpus, verbose=False, lote_documentos=2)

        # 3 documentos -> muy por debajo de 200 fragmentos: aun así deben
        # quedar indexados en la colección.
        assert resultado.documentos_ok == 3
        assert resultado.chunks > 0
        assert store.contar(store.EVIDENCIAS) == resultado.chunks

    def test_todos_los_fragmentos_acaban_en_la_coleccion(self, tmp_path, store, llm):
        from mvp_sig.pipeline import Pipeline

        docx = pytest.importorskip("docx")
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        for i in range(5):
            d = docx.Document()
            d.add_paragraph(f"Manual de operacion numero {i} con procedimiento detallado.")
            d.save(str(corpus / f"manual{i}.docx"))

        pipeline = Pipeline(store=store, llm=llm, catalogo_dir=tmp_path / "catalogo")
        resultado = pipeline.ingerir(corpus, verbose=False, lote_documentos=3)

        assert store.contar(store.EVIDENCIAS) == resultado.chunks
        assert store.contar(store.EVIDENCIAS) > 0


class TestAislamientoDelCatalogo:
    """Las pruebas no deben sobrescribir el catálogo del corpus real.

    El catálogo documental (`data/catalog/catalogo_evidencias.json`) es el
    inventario de lo ingerido.  Si una prueba lo reemplaza por el de su
    corpus de mentira, se pierde el registro de la ingesta real y las
    métricas de evaluación dejan de tener sentido.
    """

    def test_el_catalogo_se_escribe_en_el_directorio_configurado(self, tmp_path, store, llm):
        from mvp_sig.pipeline import Pipeline

        docx = pytest.importorskip("docx")
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        d = docx.Document()
        d.add_paragraph("Manual del sistema integrado de gestion con politicas.")
        d.save(str(corpus / "manual.docx"))

        destino = tmp_path / "catalogo"
        pipeline = Pipeline(store=store, llm=llm, catalogo_dir=destino)
        pipeline.ingerir(corpus, verbose=False)

        assert (destino / "catalogo_evidencias.json").exists()
        assert pipeline.cargar_catalogo()["documentos_ok"] == 1

    def test_el_catalogo_real_no_se_toca(self, tmp_path, store, llm):
        from mvp_sig.pipeline import Pipeline
        from mvp_sig.settings import PATHS

        docx = pytest.importorskip("docx")
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        d = docx.Document()
        d.add_paragraph("Manual del sistema integrado de gestion con politicas.")
        d.save(str(corpus / "manual.docx"))

        real = PATHS.catalog / "catalogo_evidencias.json"
        antes = real.read_bytes() if real.exists() else None

        pipeline = Pipeline(store=store, llm=llm, catalogo_dir=tmp_path / "catalogo")
        pipeline.ingerir(corpus, verbose=False)

        despues = real.read_bytes() if real.exists() else None
        assert antes == despues, "La prueba sobrescribió el catálogo real"
