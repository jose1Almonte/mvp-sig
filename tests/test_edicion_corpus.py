"""Pruebas de la edición del corpus desde la interfaz.

El corpus indexado no es sólo material de lectura: el auditor necesita poder

* corregir la clasificación de un documento (ámbito, tipo documental,
  organización, código) sin rehacer la ingesta completa,
* reindexar un documento cuyo archivo original ha cambiado,
* retirar un documento del diagnóstico **sin borrarlo**, de forma que la
  decisión persista aunque se vuelva a procesar el corpus entero.

El corpus CIL ONG contiene 17 pares de documentos homónimos, así que todas
las operaciones se resuelven por un identificador inequívoco y no por el
nombre.

Las pruebas usan un catálogo, una carpeta de manuales y un corpus temporales:
el corpus real nunca se toca.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mvp_sig.ingestion import manual
from mvp_sig.ingestion.catalog import RegistroEvidencia, clave_documento, id_documento
from mvp_sig.knowledge.vectorstore import VectorStore
from mvp_sig.pipeline import Pipeline

TEXTO_CALIDAD = (
    "Procedimiento de control de documentos y registros. "
    "La organización debe establecer un listado maestro de documentos, "
    "revisarlos periódicamente y controlarlos. "
    "El responsable del control de documentos es el Analista SIG."
)

TEXTO_AMBIENTE = (
    "Procedimiento de gestión ambiental. Se identifican los aspectos "
    "ambientales, se evalúan sus impactos y se fijan objetivos de reducción "
    "del consumo de energía y de las emisiones directas."
)

TEXTO_SEGURIDAD = (
    "Procedimiento de gestión de riesgos laborales. La organización debe "
    "identificar los peligros, evaluar los riesgos y planificar acciones "
    "para tratarlos, con seguimiento del Analista SIG."
)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
@pytest.fixture
def pipeline_edicion(tmp_path, store, llm) -> Pipeline:
    """Pipeline con catálogo, manuales y corpus temporales."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "Control de Documentos.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")
    (corpus / "Gestion Ambiental.txt").write_text(TEXTO_AMBIENTE, encoding="utf-8")
    (corpus / "Gestion de Riesgos.txt").write_text(TEXTO_SEGURIDAD, encoding="utf-8")
    return Pipeline(
        store=store,
        llm=llm,
        catalogo_dir=tmp_path / "catalogo",
        manuales_dir=tmp_path / "manuales",
    )


def _catalogo(pipeline: Pipeline) -> dict:
    return json.loads((pipeline.catalogo_dir / "catalogo_evidencias.json").read_text("utf-8"))


def _ruta(*partes: str) -> str:
    """Ruta con los separadores del sistema, como las guarda el catálogo."""
    return str(Path("/corpus", *partes))


def _registro_falso(documento: str, ruta: str, **extra) -> RegistroEvidencia:
    """Construye un `RegistroEvidencia` mínimo para simular el corpus."""
    datos = dict(
        documento=documento,
        ruta=str(Path(ruta)),
        tipo="docx",
        tipo_documento="procedimiento",
        ambitos=["integral"],
        ambito_principal="integral",
        paginas=1,
        bloques=1,
        chunks=1,
        caracteres=100,
        sha256="0" * 64,
        modificado="0",
        indexado="2026-01-01T00:00:00",
        estado="indexado",
        notas=[],
    )
    datos.update(extra)
    return RegistroEvidencia(**datos)


def _documentos_indexados(pipeline: Pipeline) -> set[str]:
    return {
        m["metadatos"]["documento"]
        for m in pipeline.store.listar(VectorStore.EVIDENCIAS)
    }


# --------------------------------------------------------------------------- #
# Identificadores
# --------------------------------------------------------------------------- #
class TestIdentificadores:
    def test_los_homonimos_tienen_claves_distintas(self):
        a = clave_documento("Revisión por la Dirección.docx", "/corpus/a/Revisión.docx")
        b = clave_documento("Revisión por la Dirección.docx", "/corpus/b/Revisión.docx")
        assert a != b
        assert a.startswith("Revisión por la Dirección.docx#")

    def test_el_id_es_corto_y_seguro_para_una_url(self):
        identificador = id_documento("/corpus/Mapa de Procesos.docx")
        assert len(identificador) == 12
        assert all(c in "0123456789abcdef" for c in identificador)

    def test_el_registro_calcula_clave_e_id(self):
        registro = _registro_falso("Acta.txt", _ruta("Acta.txt"))
        assert registro.clave == clave_documento("Acta.txt", _ruta("Acta.txt"))
        assert registro.id == id_documento(_ruta("Acta.txt"))

    def test_el_id_se_persiste_en_el_catalogo(self):
        assert "id" in _registro_falso("Acta.txt", _ruta("Acta.txt")).to_dict()


# --------------------------------------------------------------------------- #
# Resolución de referencias
# --------------------------------------------------------------------------- #
class TestResolucion:
    def test_resuelve_por_id(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(_registro_falso("Acta.txt", _ruta("Acta.txt")))
        entrada, error = pipeline_edicion._resolver(
            referencia=id_documento(_ruta("Acta.txt"))
        )
        assert error == ""
        assert entrada["documento"] == "Acta.txt"

    def test_resuelve_por_nombre_unico(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(_registro_falso("Acta.txt", _ruta("Acta.txt")))
        entrada, error = pipeline_edicion._resolver(referencia="Acta.txt")
        assert entrada is not None
        assert error == ""

    def test_avisa_de_los_homonimos_en_lugar_de_elegir_uno(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("a", "Acta.txt"))
        )
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("b", "Acta.txt"))
        )
        entrada, error = pipeline_edicion._resolver(referencia="Acta.txt")
        assert entrada is None
        assert "2 documentos" in error

    def test_informa_de_un_documento_inexistente(self, pipeline_edicion):
        entrada, error = pipeline_edicion._resolver(referencia="No existe.txt")
        assert entrada is None
        assert "no está en el catálogo" in error


# --------------------------------------------------------------------------- #
# Inventario
# --------------------------------------------------------------------------- #
class TestInventario:
    def test_agrega_el_corpus_y_la_evidencia_manual(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        manual.registrar_texto(pipeline_edicion, TEXTO_CALIDAD, "Acta manual")

        inventario = pipeline_edicion.inventario()
        origenes = {f["documento"]: f["origen"] for f in inventario}
        assert origenes["Acta.txt"] == "corpus"
        assert origenes["Acta manual.txt"] == "manual"

    def test_incluye_los_documentos_excluidos(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        pipeline_edicion.excluir_evidencia("Acta.txt")

        inventario = pipeline_edicion.inventario()
        fila = next(f for f in inventario if f["documento"] == "Acta.txt")
        assert fila["excluido"] is True
        assert fila["estado"] == "excluido"

    def test_cada_fila_lleva_su_identificador(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        fila = next(f for f in pipeline_edicion.inventario() if f["documento"] == "Acta.txt")
        assert fila["id"] == id_documento(_ruta("Acta.txt"))

    def test_una_fila_excluida_no_aporta_fragmentos(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"), chunks=7)
        )
        pipeline_edicion.excluir_evidencia("Acta.txt")

        fila = next(f for f in pipeline_edicion.inventario() if f["documento"] == "Acta.txt")
        assert fila["chunks"] == 0
        assert fila["chunks_historicos"] == 7
        assert sum(f["chunks"] for f in pipeline_edicion.inventario()) == 0


# --------------------------------------------------------------------------- #
# Exclusión
# --------------------------------------------------------------------------- #
class TestExclusion:
    def test_retira_los_fragmentos_del_indice(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        pipeline_edicion.store.indexar(
            VectorStore.EVIDENCIAS,
            ["Acta.txt#abc123#b#0"],
            ["Fragmento del documento"],
            [
                {
                    "documento": "Acta.txt",
                    "ruta": _ruta("Acta.txt"),
                    "tipo": "txt",
                    "ambito": "integral",
                    "ambitos": "integral",
                    "posicion": 0,
                }
            ],
            verbose=False,
        )

        resultado = pipeline_edicion.excluir_evidencia("Acta.txt")

        assert resultado["ok"]
        assert resultado["fragmentos_eliminados"] == 1
        assert pipeline_edicion.store.contar(VectorStore.EVIDENCIAS) == 0

    def test_quita_el_documento_del_catalogo(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        pipeline_edicion.excluir_evidencia("Acta.txt")
        documentos = {r["documento"] for r in _catalogo(pipeline_edicion)["registros"]}
        assert documentos == set()

    def test_conserva_el_archivo_original(self, pipeline_edicion):
        corpus = pipeline_edicion.catalogo_dir.parent / "corpus" / "Acta.txt"
        corpus.write_text(TEXTO_CALIDAD, encoding="utf-8")
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", str(corpus))
        )

        pipeline_edicion.excluir_evidencia("Acta.txt")

        assert corpus.is_file()

    def test_deja_constancia_de_la_exclusion(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        pipeline_edicion.excluir_evidencia("Acta.txt", motivo="documento duplicado")

        exclusiones = pipeline_edicion.cargar_exclusiones()
        assert len(exclusiones) == 1
        assert exclusiones[0]["documento"] == "Acta.txt"
        assert exclusiones[0]["motivo"] == "documento duplicado"
        assert exclusiones[0]["metadatos"]["tipo_documento"] == "procedimiento"

    def test_rechaza_un_documento_inexistente(self, pipeline_edicion):
        resultado = pipeline_edicion.excluir_evidencia("No existe.txt")
        assert resultado["ok"] is False
        assert "no está en el catálogo" in resultado["motivo"]

    def test_no_afecta_al_homonimo(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("a", "Acta.txt"))
        )
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("b", "Acta.txt"))
        )

        pipeline_edicion.excluir_evidencia(id_documento(_ruta("a", "Acta.txt")))

        documentos = {r["documento"] for r in _catalogo(pipeline_edicion)["registros"]}
        assert documentos == {"Acta.txt"}
        rutas = {r["ruta"] for r in _catalogo(pipeline_edicion)["registros"]}
        assert rutas == {_ruta("b", "Acta.txt")}


# --------------------------------------------------------------------------- #
# Persistencia de la exclusión frente a la ingesta completa
# --------------------------------------------------------------------------- #
class TestPersistencia:
    def test_la_ingesta_no_reindexa_los_documentos_excluidos(
        self, tmp_path, store, llm
    ):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")
        (corpus / "Otro.txt").write_text(TEXTO_SEGURIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        pipeline.excluir_evidencia("Acta.txt")

        resultado = pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)

        assert resultado.excluidos == 1
        assert _documentos_indexados(pipeline) == {"Otro.txt"}

    def test_la_reincorporacion_devuelve_el_documento(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        pipeline.excluir_evidencia("Acta.txt")

        resultado = pipeline.reincorporar_evidencia("Acta.txt")

        assert resultado["ok"]
        assert resultado["reindexado"] is True
        assert "Acta.txt" in _documentos_indexados(pipeline)
        assert pipeline.cargar_exclusiones() == []

    def test_la_reincorporacion_conserva_los_metadatos_corregidos(
        self, tmp_path, store, llm
    ):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        pipeline.actualizar_metadatos(
            "Acta.txt", ambitos=["calidad"], codigo="SIG-ACTA-01"
        )
        pipeline.excluir_evidencia("Acta.txt")

        pipeline.reincorporar_evidencia("Acta.txt")

        entrada = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        assert entrada["ambito_principal"] == "calidad"
        assert entrada["codigo"] == "SIG-ACTA-01"

    def test_avisa_si_el_archivo_ya_no_existe(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        pipeline.excluir_evidencia("Acta.txt")
        (corpus / "Acta.txt").unlink()

        resultado = pipeline.reincorporar_evidencia("Acta.txt")

        assert resultado["ok"] is True
        assert resultado["reindexado"] is False
        assert "no se encuentra" in resultado["mensaje"]


# --------------------------------------------------------------------------- #
# Edición de metadatos
# --------------------------------------------------------------------------- #
class TestEdicionMetadatos:
    def test_cambia_el_ambito_y_reindexa(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)

        resultado = pipeline.actualizar_metadatos("Acta.txt", ambitos=["calidad"])

        assert resultado["ok"]
        entrada = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        assert entrada["ambito_principal"] == "calidad"
        assert "calidad" in entrada["ambitos"]

    def test_los_campos_no_indicados_conservan_su_valor(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        antes = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        pipeline.actualizar_metadatos("Acta.txt", codigo="SIG-ACTA-01")

        despues = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        assert despues["codigo"] == "SIG-ACTA-01"
        # La clasificación que no se tocó sigue siendo la misma.
        assert despues["ambito_principal"] == antes["ambito_principal"]
        assert despues["ambitos"] == antes["ambitos"]
        assert despues["tipo_documento"] == antes["tipo_documento"]

    def test_el_reindexado_conserva_la_clasificacion(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        pipeline.actualizar_metadatos("Acta.txt", ambitos=["calidad"])

        resultado = pipeline.reindexar_documento("Acta.txt")

        assert resultado["ok"]
        entrada = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        assert entrada["ambito_principal"] == "calidad"

    def test_reindexa_un_archivo_modificado(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        antes = pipeline.store.contar(VectorStore.EVIDENCIAS)

        texto_nuevo = (
            TEXTO_CALIDAD + " " + TEXTO_AMBIENTE + " " + TEXTO_SEGURIDAD
        )
        (corpus / "Acta.txt").write_text(texto_nuevo, encoding="utf-8")
        sha_previo = next(
            r["sha256"] for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        pipeline.reindexar_documento("Acta.txt")

        # El reindexado recoge el contenido nuevo y no duplica los fragmentos.
        fragmentos = pipeline.store.listar(VectorStore.EVIDENCIAS)
        assert pipeline.store.contar(VectorStore.EVIDENCIAS) == len(fragmentos)
        assert pipeline.store.contar(VectorStore.EVIDENCIAS) >= antes
        assert all(m["metadatos"]["documento"] == "Acta.txt" for m in fragmentos)
        entrada = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        assert entrada["sha256"] != sha_previo

    def test_informa_de_un_archivo_que_ya_no_existe(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        resultado = pipeline_edicion.actualizar_metadatos("Acta.txt")
        assert resultado["ok"] is False
        assert "No se encuentra el archivo" in resultado["motivo"]

    def test_la_edicion_no_toca_los_otros_documentos(self, tmp_path, store, llm):
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")
        (corpus / "Otro.txt").write_text(TEXTO_SEGURIDAD, encoding="utf-8")

        pipeline = Pipeline(
            store=store,
            llm=llm,
            catalogo_dir=tmp_path / "catalogo",
            manuales_dir=tmp_path / "manuales",
        )
        pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
        antes = {
            r["documento"]: r["sha256"] for r in _catalogo(pipeline)["registros"]
        }

        pipeline.actualizar_metadatos("Acta.txt", ambitos=["calidad"])

        despues = {
            r["documento"]: r["sha256"] for r in _catalogo(pipeline)["registros"]
        }
        assert despues["Otro.txt"] == antes["Otro.txt"]


# --------------------------------------------------------------------------- #
# La baja (eliminación) sigue reservada a la evidencia manual
# --------------------------------------------------------------------------- #
class TestBaja:
    def test_no_permite_borrar_un_documento_del_corpus(self, pipeline_edicion):
        pipeline_edicion.actualizar_catalogo(
            _registro_falso("Acta.txt", _ruta("Acta.txt"))
        )
        resultado = pipeline_edicion.eliminar_evidencia("Acta.txt")
        assert resultado["ok"] is False
        assert "exclusión" in resultado["motivo"]

    def test_sigue_permitiendo_borrar_una_evidencia_manual(self, pipeline_edicion):
        manual.registrar_texto(pipeline_edicion, TEXTO_CALIDAD, "Acta manual")
        resultado = pipeline_edicion.eliminar_evidencia("Acta manual.txt")
        assert resultado["ok"] is True
        assert "Acta manual.txt" not in _documentos_indexados(pipeline_edicion)


# --------------------------------------------------------------------------- #
# API REST
# --------------------------------------------------------------------------- #
@pytest.fixture
def cliente_aislado(tmp_path, store, llm, monkeypatch):
    """Cliente HTTP con un pipeline aislado del corpus real."""
    from fastapi.testclient import TestClient

    from mvp_sig.api import main as api_main

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "Acta.txt").write_text(TEXTO_CALIDAD, encoding="utf-8")

    pipeline = Pipeline(
        store=store,
        llm=llm,
        catalogo_dir=tmp_path / "catalogo",
        manuales_dir=tmp_path / "manuales",
    )
    # Se indexa de verdad para que las operaciones de edición encuentren el
    # archivo en disco, como en el corpus real.
    pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)
    monkeypatch.setattr(api_main, "_PIPELINE", pipeline)
    return TestClient(api_main.app), pipeline


class TestApiEdicion:
    def test_el_inventario_devuelve_el_corpus(self, cliente_aislado):
        cliente, _ = cliente_aislado

        respuesta = cliente.get("/evidencias")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["total"] == 1
        assert datos["evidencias"][0]["origen"] == "corpus"

    def test_el_inventario_filtra_por_origen(self, cliente_aislado):
        cliente, pipeline = cliente_aislado
        manual.registrar_texto(pipeline, TEXTO_CALIDAD, "Acta manual")

        respuesta = cliente.get("/evidencias", params={"origen": "manual"})

        datos = respuesta.json()
        assert datos["total"] == 1
        assert datos["evidencias"][0]["origen"] == "manual"

    def test_actualiza_los_metadatos(self, cliente_aislado):
        cliente, pipeline = cliente_aislado
        identificador = pipeline.inventario()[0]["id"]

        respuesta = cliente.put(
            f"/evidencias/{identificador}",
            json={"ambitos": ["calidad"], "codigo": "SIG-ACTA-01"},
        )

        assert respuesta.status_code == 200
        entrada = next(
            r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt"
        )
        assert entrada["ambito_principal"] == "calidad"
        assert entrada["codigo"] == "SIG-ACTA-01"

    def test_excluye_un_documento(self, cliente_aislado):
        cliente, pipeline = cliente_aislado
        identificador = pipeline.inventario()[0]["id"]

        respuesta = cliente.post(
            f"/evidencias/{identificador}/excluir", json={"motivo": "duplicado"}
        )

        assert respuesta.status_code == 200
        assert respuesta.json()["ok"] is True
        assert len(pipeline.cargar_exclusiones()) == 1

    def test_reincorpora_un_documento(self, cliente_aislado):
        cliente, pipeline = cliente_aislado
        identificador = pipeline.inventario()[0]["id"]
        cliente.post(f"/evidencias/{identificador}/excluir", json={})

        respuesta = cliente.post(f"/evidencias/{identificador}/reincorporar")

        assert respuesta.status_code == 200
        assert respuesta.json()["ok"] is True
        assert pipeline.cargar_exclusiones() == []

    def test_un_documento_inexistente_da_404(self, cliente_aislado):
        cliente, _ = cliente_aislado
        respuesta = cliente.post("/evidencias/noexiste/excluir", json={})
        assert respuesta.status_code == 404
