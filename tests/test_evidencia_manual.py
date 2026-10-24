"""Pruebas del registro manual de evidencia.

El escenario que se cubre es el del auditor que recibe evidencia fuera del
expediente (un acta pegada desde un correo, un reporte exportado del sistema)
y necesita incorporarla al corpus **sin rehacer la ingesta completa**.

Las pruebas usan un catálogo y una carpeta de manuales temporales, de modo que
el catálogo real del corpus nunca se toca.
"""
from __future__ import annotations

import json

import pytest

from mvp_sig.ingestion import manual
from mvp_sig.knowledge.vectorstore import VectorStore
from mvp_sig.pipeline import Pipeline

# El pre-procesamiento descarta los bloques de menos de 20 caracteres, así que
# una evidencia de prueba debe tener texto con contenido real.
TEXTO_ACTA = (
    "Acta de revisión por la dirección. La dirección revisó el sistema integrado "
    "de gestión y comprobó la consecución de los objetivos del sistema. "
    "Se detectaron dos acciones correctivas sobre el control de la información "
    "documentada."
)

TEXTO_INFORME = (
    "Informe trimestral de gestión ambiental. Se monitorizaron el consumo de energía, "
    "las emisiones directas y la gestión de residuos, con un cumplimiento del "
    "plan de gestión ambiental del 92 %."
)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
@pytest.fixture
def pipeline_manual(tmp_path, store, llm) -> Pipeline:
    """Pipeline con catálogo y carpeta de manuales temporales."""
    return Pipeline(
        store=store,
        llm=llm,
        catalogo_dir=tmp_path / "catalogo",
        manuales_dir=tmp_path / "manuales",
    )


def _catalogo(pipeline: Pipeline) -> dict:
    return json.loads((pipeline.catalogo_dir / "catalogo_evidencias.json").read_text("utf-8"))


def _registro_falso(documento: str, ruta: str):
    """Construye un `RegistroEvidencia` mínimo para simular el corpus."""
    from mvp_sig.ingestion.catalog import RegistroEvidencia

    return RegistroEvidencia(
        documento=documento,
        ruta=ruta,
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


# --------------------------------------------------------------------------- #
# Nombres
# --------------------------------------------------------------------------- #
def test_sanear_nombre_quita_caracteres_invalidos():
    assert manual.sanear_nombre("Acta: revisión/2026?.txt") == "Acta_ revisión_2026_.txt"


def test_sanear_nombre_no_trunca_en_la_ruta():
    """El nombre se trata como texto plano: un «/» no indica una carpeta."""
    assert manual.sanear_nombre("Acta/2026") == "Acta_2026"


def test_sanear_nombre_añade_extension_por_defecto():
    assert manual.sanear_nombre("Acta de revisión", ".txt") == "Acta de revisión.txt"


def test_sanear_nombre_respeta_la_extension_ya_presente():
    assert manual.sanear_nombre("Acta de revisión.docx", ".txt") == "Acta de revisión.docx"


def test_nombre_disponible_renombra_si_choca_con_el_corpus(pipeline_manual):
    pipeline_manual.actualizar_catalogo(
        _registro_falso("Mapa de Procesos.docx", "/corpus/Mapa de Procesos.docx")
    )
    nombre, avisos = manual.nombre_disponible(pipeline_manual, "Mapa de Procesos.docx")
    assert nombre == "Mapa de Procesos (manual).docx"
    assert avisos and "corpus" in avisos[0]


def test_nombre_disponible_reutiliza_el_nombre_de_otra_evidencia_manual(pipeline_manual):
    pipeline_manual.actualizar_catalogo(
        _registro_falso("Acta.txt", str(pipeline_manual.manuales_dir / "Acta.txt"))
    )
    nombre, avisos = manual.nombre_disponible(pipeline_manual, "Acta.txt")
    assert nombre == "Acta.txt"
    assert avisos and "actualizó" in avisos[0]


# --------------------------------------------------------------------------- #
# Registro de texto pegado
# --------------------------------------------------------------------------- #
def test_registrar_texto_materializa_el_archivo(pipeline_manual):
    resultado = manual.registrar_texto(
        pipeline_manual, TEXTO_ACTA, "Acta de revisión", ambitos=["calidad"]
    )
    assert resultado.ok
    assert resultado.documento == "Acta de revisión.txt"
    assert (pipeline_manual.manuales_dir / "Acta de revisión.txt").exists()
    assert (pipeline_manual.manuales_dir / "Acta de revisión.txt").read_text("utf-8") == TEXTO_ACTA


def test_registrar_texto_rechaza_texto_vacio(pipeline_manual):
    resultado = manual.registrar_texto(pipeline_manual, "   ", "Vacía")
    assert not resultado.ok
    assert "vacío" in resultado.mensaje.lower()


def test_registrar_texto_rechaza_texto_demasiado_corto(pipeline_manual):
    """Un texto sin contenido real no puede indexarse; el aviso debe decirlo."""
    resultado = manual.registrar_texto(pipeline_manual, "corto", "Corta")
    assert not resultado.ok
    assert "limpieza" in resultado.mensaje.lower()


def test_un_registro_fallido_no_deja_archivos_huerfanos(pipeline_manual):
    """Si el texto no se puede indexar, el archivo no debe quedar en disco."""
    manual.registrar_texto(pipeline_manual, "corto", "Corta")
    assert not (pipeline_manual.manuales_dir / "Corta.txt").exists()
    assert list(pipeline_manual.manuales_dir.glob("*")) == []


def test_un_registro_fallido_no_corrompe_la_evidencia_previa(pipeline_manual):
    """Actualizar con un texto inválido debe dejar intacta la evidencia anterior."""
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Acta")
    ruta = pipeline_manual.manuales_dir / "Acta.txt"

    resultado = manual.registrar_texto(pipeline_manual, "corto", "Acta")
    assert not resultado.ok

    # El archivo conserva el contenido bueno y el índice sigue coherente.
    assert ruta.read_text("utf-8") == TEXTO_ACTA
    encontrados = pipeline_manual.store.listar(
        VectorStore.EVIDENCIAS, donde={"documento": "Acta.txt"}
    )
    assert len(encontrados) == 1
    assert "dirección" in encontrados[0]["texto"]


def test_registrar_texto_indexa_los_fragmentos(pipeline_manual):
    resultado = manual.registrar_texto(
        pipeline_manual,
        "La organización debe establecer los objetivos del sistema integrado de gestión.",
        "Objetivos",
        ambitos=["integral"],
    )
    assert resultado.ok
    assert resultado.chunks >= 1

    encontrados = pipeline_manual.store.listar(
        VectorStore.EVIDENCIAS, donde={"documento": "Objetivos.txt"}
    )
    assert len(encontrados) == resultado.chunks
    assert encontrados[0]["metadatos"]["origen"] == "manual"


def test_registrar_texto_acepta_acentos_sin_codificacion_rota(pipeline_manual):
    manual.registrar_texto(pipeline_manual, "Ámbito: gestión ambiental y seguridad", "Acentos")
    contenido = (pipeline_manual.manuales_dir / "Acentos.txt").read_text("utf-8")
    assert "gestión" in contenido
    assert "Ã" not in contenido


def test_registrar_texto_es_idempotente(pipeline_manual):
    primero = manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Acta")
    segundo = manual.registrar_texto(pipeline_manual, TEXTO_INFORME, "Acta")

    assert primero.ok and segundo.ok
    assert primero.documento == segundo.documento == "Acta.txt"

    total = pipeline_manual.store.contar(VectorStore.EVIDENCIAS)
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Acta")
    assert pipeline_manual.store.contar(VectorStore.EVIDENCIAS) == total

    registros = [r for r in _catalogo(pipeline_manual)["registros"] if r["documento"] == "Acta.txt"]
    assert len(registros) == 1


def test_registrar_texto_actualiza_el_catalogo(pipeline_manual):
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Acta", ambitos=["seguridad"])
    catalogo = _catalogo(pipeline_manual)
    assert catalogo["documentos_ok"] == 1
    assert catalogo["chunks"] >= 1
    registro = catalogo["registros"][0]
    assert registro["documento"] == "Acta.txt"
    assert registro["ambito_principal"] == "seguridad"


def test_registrar_texto_no_toca_el_catalogo_del_corpus(pipeline_manual):
    """El catálogo de una evidencia manual no debe pisar el catálogo del corpus."""
    pipeline_manual.actualizar_catalogo(
        _registro_falso("Manual Corporativo.docx", "/corpus/Manual Corporativo.docx")
    )
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Otra")

    documentos = {r["documento"] for r in _catalogo(pipeline_manual)["registros"]}
    assert documentos == {"Manual Corporativo.docx", "Otra.txt"}


# --------------------------------------------------------------------------- #
# Registro de archivo
# --------------------------------------------------------------------------- #
def test_registrar_archivo_desde_ruta(tmp_path, pipeline_manual):
    origen = tmp_path / "reporte.txt"
    origen.write_text(TEXTO_INFORME, encoding="utf-8")
    resultado = manual.registrar_archivo(pipeline_manual, origen, "Reporte mensual")
    assert resultado.ok
    assert resultado.documento == "Reporte mensual.txt"
    assert (pipeline_manual.manuales_dir / "Reporte mensual.txt").exists()


def test_registrar_archivo_desde_bytes(pipeline_manual):
    resultado = manual.registrar_archivo(
        pipeline_manual,
        TEXTO_INFORME.encode("utf-8"),
        "Reporte mensual",
        extension=".txt",
    )
    assert resultado.ok
    assert (pipeline_manual.manuales_dir / "Reporte mensual.txt").exists()


def test_registrar_archivo_rechaza_formato_no_admitido(tmp_path, pipeline_manual):
    origen = tmp_path / "malware.exe"
    origen.write_bytes(b"MZ")
    resultado = manual.registrar_archivo(pipeline_manual, origen)
    assert not resultado.ok
    assert "no admitido" in resultado.mensaje.lower()


def test_registrar_archivo_rechaza_archivo_inexistente(pipeline_manual):
    resultado = manual.registrar_archivo(pipeline_manual, "no/existe.pdf")
    assert not resultado.ok
    assert "no existe" in resultado.mensaje.lower()


def test_registrar_archivo_supera_el_limite_de_tamano(pipeline_manual, monkeypatch):
    monkeypatch.setattr(manual, "MAX_BYTES", 10)
    resultado = manual.registrar_archivo(pipeline_manual, b"x" * 100, "Grande.txt")
    assert not resultado.ok
    assert "límite" in resultado.mensaje.lower()


# --------------------------------------------------------------------------- #
# Listado y baja
# --------------------------------------------------------------------------- #
def test_listar_manuales_solo_devuelve_las_manuales(pipeline_manual):
    pipeline_manual.actualizar_catalogo(
        _registro_falso("Del Corpus.txt", "/corpus/Del Corpus.txt")
    )
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Del Corpus")  # choca -> (manual)

    listado = manual.listar_manuales(pipeline_manual)
    assert len(listado) == 1
    assert listado[0]["documento"] == "Del Corpus (manual).txt"
    assert listado[0]["estado"] == "indexado"


def test_eliminar_evidencia_borra_fragmentos_y_catalogo(pipeline_manual):
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Temporal")
    assert pipeline_manual.store.contar(VectorStore.EVIDENCIAS) >= 1

    resultado = pipeline_manual.eliminar_evidencia("Temporal.txt")
    assert resultado["ok"]
    assert resultado["fragmentos_eliminados"] >= 1

    assert pipeline_manual.store.contar(VectorStore.EVIDENCIAS) == 0
    assert not (pipeline_manual.manuales_dir / "Temporal.txt").exists()
    assert _catalogo(pipeline_manual)["registros"] == []


def test_eliminar_evidencia_no_permite_borrar_el_corpus(pipeline_manual):
    pipeline_manual.actualizar_catalogo(
        _registro_falso("Del Corpus.docx", "/corpus/Del Corpus.docx")
    )
    resultado = pipeline_manual.eliminar_evidencia("Del Corpus.docx")
    assert not resultado["ok"]
    assert "corpus" in resultado["motivo"].lower()


def test_eliminar_evidencia_inexistente(pipeline_manual):
    resultado = pipeline_manual.eliminar_evidencia("No existe.txt")
    assert not resultado["ok"]
    assert "no está en el catálogo" in resultado["motivo"]


# --------------------------------------------------------------------------- #
# Aislamiento del corpus indexado
# --------------------------------------------------------------------------- #
def test_registrar_evidencia_no_recrea_la_coleccion(pipeline_manual):
    """Registrar evidencia manual no debe eliminar el corpus ya indexado."""
    pipeline_manual.store.indexar(
        VectorStore.EVIDENCIAS,
        ["doc1#hash#b#0"],
        ["Fragmento del corpus que debe sobrevivir"],
        [
            {
                "documento": "Corpus.docx",
                "ruta": "/corpus/Corpus.docx",
                "tipo": "docx",
                "ambito": "integral",
                "ambitos": "integral",
                "posicion": 0,
            }
        ],
        verbose=False,
    )
    total_previo = pipeline_manual.store.contar(VectorStore.EVIDENCIAS)

    resultado = manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Añadida")
    assert resultado.ok

    assert pipeline_manual.store.contar(VectorStore.EVIDENCIAS) > total_previo
    assert len(pipeline_manual.store.listar(VectorStore.EVIDENCIAS)) > total_previo


def test_los_fragmentos_manuales_no_chocan_con_los_del_corpus(pipeline_manual):
    """Dos documentos con el mismo nombre pero distinto origen no colisionan."""
    pipeline_manual.store.indexar(
        VectorStore.EVIDENCIAS,
        ["Acta.txt#abc123#b#0"],
        ["Fragmento del corpus"],
        [
            {
                "documento": "Acta.txt",
                "ruta": "/corpus/Acta.txt",
                "tipo": "txt",
                "ambito": "integral",
                "ambitos": "integral",
                "posicion": 0,
            }
        ],
        verbose=False,
    )
    pipeline_manual.actualizar_catalogo(_registro_falso("Acta.txt", "/corpus/Acta.txt"))
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Acta")

    documentos = {
        m["metadatos"]["documento"] for m in pipeline_manual.store.listar(VectorStore.EVIDENCIAS)
    }
    assert documentos == {"Acta.txt", "Acta (manual).txt"}


def test_el_borrado_de_un_manual_no_toca_el_homonimo_del_corpus(pipeline_manual):
    """Dar de baja la copia manual no puede borrar el documento del corpus."""
    pipeline_manual.store.indexar(
        VectorStore.EVIDENCIAS,
        ["Acta.txt#abc123#b#0"],
        ["Fragmento del corpus"],
        [
            {
                "documento": "Acta.txt",
                "ruta": "/corpus/Acta.txt",
                "tipo": "txt",
                "ambito": "integral",
                "ambitos": "integral",
                "posicion": 0,
            }
        ],
        verbose=False,
    )
    pipeline_manual.actualizar_catalogo(_registro_falso("Acta.txt", "/corpus/Acta.txt"))
    manual.registrar_texto(pipeline_manual, TEXTO_ACTA, "Acta")

    pipeline_manual.eliminar_evidencia("Acta (manual).txt")

    documentos = {
        m["metadatos"]["documento"] for m in pipeline_manual.store.listar(VectorStore.EVIDENCIAS)
    }
    assert documentos == {"Acta.txt"}


def test_la_ingesta_completa_conserva_la_evidencia_manual(tmp_path, store, llm):
    """La ingesta recrea la colección: la evidencia manual debe reindexarse."""
    pipeline = Pipeline(
        store=store,
        llm=llm,
        catalogo_dir=tmp_path / "catalogo",
        manuales_dir=tmp_path / "manuales",
    )
    manual.registrar_texto(pipeline, TEXTO_ACTA, "Acta", ambitos=["calidad"])

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "Procedimiento.txt").write_text(TEXTO_INFORME, encoding="utf-8")

    pipeline.ingerir(corpus, extensiones=(".txt",), verbose=False)

    documentos = {
        m["metadatos"]["documento"] for m in pipeline.store.listar(VectorStore.EVIDENCIAS)
    }
    assert documentos == {"Procedimiento.txt", "Acta.txt"}

    catalogo = {r["documento"] for r in _catalogo(pipeline)["registros"]}
    assert catalogo == {"Procedimiento.txt", "Acta.txt"}

    # La evidencia manual conserva sus metadatos decididos por el usuario.
    entrada = next(r for r in _catalogo(pipeline)["registros"] if r["documento"] == "Acta.txt")
    assert entrada["ambito_principal"] == "calidad"


# --------------------------------------------------------------------------- #
# API REST
# --------------------------------------------------------------------------- #
@pytest.fixture
def cliente_aislado(tmp_path, store, llm, monkeypatch):
    """Cliente HTTP con un pipeline aislado del corpus real."""
    from fastapi.testclient import TestClient

    from mvp_sig.api import main as api_main

    pipeline = Pipeline(
        store=store,
        llm=llm,
        catalogo_dir=tmp_path / "catalogo",
        manuales_dir=tmp_path / "manuales",
    )
    monkeypatch.setattr(api_main, "_PIPELINE", pipeline)
    return TestClient(api_main.app), pipeline


class TestApiEvidencia:
    def test_registrar_texto_por_api(self, cliente_aislado):
        cliente, _ = cliente_aislado
        r = cliente.post(
            "/evidencias",
            json={
                "texto": TEXTO_ACTA,
                "nombre": "Acta de dirección",
                "ambitos": ["calidad"],
                "tipo_documento": "acta",
                "organizacion": "CIL ONG",
            },
        )
        assert r.status_code == 200, r.text
        datos = r.json()
        assert datos["ok"] is True
        assert datos["documento"] == "Acta de dirección.txt"
        assert datos["chunks"] >= 1

    def test_registrar_texto_vacio_es_rechazado(self, cliente_aislado):
        cliente, _ = cliente_aislado
        r = cliente.post("/evidencias", json={"texto": "", "nombre": "Vacía"})
        assert r.status_code == 422

    def test_listar_evidencias(self, cliente_aislado):
        cliente, _ = cliente_aislado
        cliente.post("/evidencias", json={"texto": TEXTO_ACTA, "nombre": "Acta"})
        r = cliente.get("/evidencias")
        assert r.status_code == 200
        datos = r.json()
        assert datos["total"] == 1
        assert datos["evidencias"][0]["documento"] == "Acta.txt"

    def test_registrar_archivo_por_api(self, cliente_aislado):
        cliente, _ = cliente_aislado
        r = cliente.post(
            "/evidencias/archivo",
            files={"archivo": ("informe.txt", TEXTO_INFORME.encode("utf-8"), "text/plain")},
            data={"nombre": "Informe ambiental", "ambitos": "ambiente"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["documento"] == "Informe ambiental.txt"

    def test_borrar_evidencia_por_api(self, cliente_aislado):
        cliente, pipeline = cliente_aislado
        cliente.post("/evidencias", json={"texto": TEXTO_ACTA, "nombre": "Temporal"})
        r = cliente.delete("/evidencias/Temporal.txt")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert pipeline.store.contar(VectorStore.EVIDENCIAS) == 0

    def test_borrar_evidencia_inexistente(self, cliente_aislado):
        cliente, _ = cliente_aislado
        r = cliente.delete("/evidencias/No%20existe.txt")
        assert r.status_code == 404
