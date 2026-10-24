"""Pruebas de la ingesta: extractores, clasificación y catálogo."""
from __future__ import annotations

from pathlib import Path

import pytest

from mvp_sig.ingestion.catalog import (
    RegistroEvidencia,
    ahora_iso,
    clasificar_ambitos,
    inferir_tipo_documento,
    metadatos_responsable,
    sha256_archivo,
)
from mvp_sig.ingestion.extractors import (
    EXTRACTORES,
    Bloque,
    DocumentoExtraido,
    extract_documento,
    sniff_mime,
)


class TestExtractores:
    def test_formato_no_soportado(self, tmp_path):
        ruta = tmp_path / "programa.exe"
        ruta.write_bytes(b"MZ")
        doc = extract_documento(ruta)
        assert not doc.ok
        assert "no soportado" in doc.error.lower()

    def test_txt_plano_soportado(self, tmp_path):
        """El texto plano es el formato en que se materializa la evidencia manual."""
        ruta = tmp_path / "acta.txt"
        ruta.write_text(
            "Acta de revisión por la dirección.\n\nSe revisaron los objetivos del sistema.",
            encoding="utf-8",
        )
        doc = extract_documento(ruta)
        assert doc.ok
        assert doc.tipo == "txt"
        assert len(doc.bloques) == 2
        assert doc.bloques[0].seccion == "párrafo 1"

    def test_docx_real(self, tmp_path):
        docx = pytest.importorskip("docx")
        ruta = tmp_path / "proc.docx"
        d = docx.Document()
        d.add_heading("Objetivo", level=1)
        d.add_paragraph("Establecer el control de los documentos del sistema.")
        d.save(str(ruta))

        doc = extract_documento(ruta)
        assert doc.ok
        assert doc.tipo == "docx"
        assert any("control de los documentos" in b.texto for b in doc.bloques)
        # La sección (encabezado) debe quedar registrada para la trazabilidad.
        assert any(b.seccion == "Objetivo" for b in doc.bloques)

    def test_xlsx_real(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        ruta = tmp_path / "matriz.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Hoja1"
        ws.append(["Riesgo", "Control"])
        ws.append(["Caída", "Barandal"])
        wb.save(str(ruta))

        doc = extract_documento(ruta)
        assert doc.ok
        assert doc.tipo == "xlsx"
        texto = doc.texto_completo()
        assert "Caída" in texto
        assert "Barandal" in texto
        # La hoja se conserva como referencia de ubicación.
        assert doc.bloques[0].seccion == "Hoja1"

    def test_docx_vacio_es_error_usable(self, tmp_path):
        docx = pytest.importorskip("docx")
        ruta = tmp_path / "vacio.docx"
        docx.Document().save(str(ruta))
        doc = extract_documento(ruta)
        # No debe lanzar excepción; simplemente no hay contenido.
        assert isinstance(doc, DocumentoExtraido)


class TestSniffMime:
    def test_pdf(self, tmp_path):
        ruta = tmp_path / "a.pdf"
        ruta.write_bytes(b"%PDF-1.7\n...")
        assert sniff_mime(ruta) == "pdf"

    def test_ooxml(self, tmp_path):
        ruta = tmp_path / "a.docx"
        ruta.write_bytes(b"PK\x03\x04resto")
        assert sniff_mime(ruta) == "docx"

    def test_ole(self, tmp_path):
        ruta = tmp_path / "a.xls"
        ruta.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        assert sniff_mime(ruta) == "ole"

    def test_desconocido(self, tmp_path):
        ruta = tmp_path / "a.bin"
        ruta.write_bytes(b"lo que sea")
        assert sniff_mime(ruta) == "desconocido"


# --------------------------------------------------------------------------- #
# Formato binario heredado: Excel 97-2003 (.xls)
# --------------------------------------------------------------------------- #
class TestExtractorXls:
    def test_xls_esta_registrado(self):
        assert ".xls" in EXTRACTORES

    def test_lee_hojas_y_celda(self, tmp_path):
        xlwt = pytest.importorskip("xlwt")
        ruta = tmp_path / "matriz.xls"
        libro = xlwt.Workbook()
        hoja = libro.add_sheet("RIESGOS")
        hoja.write(0, 0, "PELIGRO")
        hoja.write(0, 1, "CONTROL")
        hoja.write(1, 0, "Caida desde altura")
        hoja.write(1, 1, "Barandal de seguridad")
        libro.save(str(ruta))

        doc = extract_documento(ruta)
        assert doc.ok
        assert doc.tipo == "xls"
        assert doc.paginas == 1
        assert doc.bloques[0].seccion == "RIESGOS"
        texto = doc.texto_completo()
        assert "PELIGRO" in texto and "Caida desde altura" in texto

    def test_varias_hojas(self, tmp_path):
        xlwt = pytest.importorskip("xlwt")
        ruta = tmp_path / "varias.xls"
        libro = xlwt.Workbook()
        for nombre in ("HOJA1", "HOJA2"):
            hoja = libro.add_sheet(nombre)
            hoja.write(0, 0, f"contenido de {nombre}")
        libro.save(str(ruta))

        doc = extract_documento(ruta)
        assert doc.ok
        assert doc.paginas == 2
        assert {b.seccion for b in doc.bloques} == {"HOJA1", "HOJA2"}


# --------------------------------------------------------------------------- #
# Diagnóstico de contenedores OLE2 con extensión engañosa
# --------------------------------------------------------------------------- #
class TestDiagnosticoOle:
    def test_clase_ole_detecta_cifrado(self, monkeypatch, tmp_path):
        from mvp_sig.ingestion.extractors import _clase_ole

        class OleFalso:
            def __init__(self, *_a, **_k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def listdir(self):
                return [["Root Entry"], ["EncryptedPackage"]]

        monkeypatch.setattr("olefile.OleFileIO", OleFalso)
        ruta = tmp_path / "a.docx"
        ruta.write_bytes(b"\xd0\xcf\x11\xe0")
        assert _clase_ole(ruta) == "cifrado"

    def test_clase_ole_detecta_word_y_excel(self, monkeypatch, tmp_path):
        from mvp_sig.ingestion.extractors import _clase_ole

        ruta = tmp_path / "a.docx"
        ruta.write_bytes(b"\xd0\xcf\x11\xe0")

        def _fake(nombres):
            class OleFalso:
                def __init__(self, *_a, **_k):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

                def listdir(self):
                    return nombres

            return OleFalso

        monkeypatch.setattr("olefile.OleFileIO", _fake([["Root Entry"], ["WordDocument"]]))
        assert _clase_ole(ruta) == "word"

        monkeypatch.setattr("olefile.OleFileIO", _fake([["Root Entry"], ["Workbook"]]))
        assert _clase_ole(ruta) == "excel"

    def test_error_claro_para_documento_cifrado(self, monkeypatch, tmp_path):
        """Un .docx que en realidad está cifrado debe decirlo con precisión."""
        from mvp_sig.ingestion import extractors

        monkeypatch.setattr(extractors, "sniff_mime", lambda _r: "ole")
        monkeypatch.setattr(extractors, "_clase_ole", lambda _r: "cifrado")
        monkeypatch.setattr(
            extractors,
            "extraer_docx",
            lambda r: extractors.DocumentoExtraido(
                ruta=r, nombre=r.name, tipo="docx", bloques=[], error="DOCX ilegible: boom"
            ),
        )
        ruta = tmp_path / "secreto.docx"
        ruta.write_bytes(b"irrelevante")
        doc = extract_documento(ruta)
        assert not doc.ok
        assert "cifrado con contraseña" in doc.error


class TestClasificacion:
    def test_detecta_ambito_por_nombre(self):
        ambitos, principal = clasificar_ambitos(
            "Identificación de Peligros, Evaluación y Valoración de Riesgos_CIL ONG.docx", ""
        )
        assert principal in {"seguridad", "integral"}
        assert "seguridad" in ambitos

    def test_detecta_ambito_por_contenido(self):
        ambitos, principal = clasificar_ambitos(
            "procedimiento.docx",
            "Se identifican los aspectos e impactos ambientales y su valoracion.",
        )
        assert "ambiente" in ambitos

    def test_sin_palabras_clave_devuelve_integral(self):
        ambitos, principal = clasificar_ambitos("documento generico.docx", "texto sin tema claro")
        assert principal == "integral"

    def test_inferir_tipo_documento(self):
        assert inferir_tipo_documento("Procedimiento de X.docx") != ""
        assert inferir_tipo_documento("matriz.xlsx") != ""

    def test_metadatos_responsable(self):
        extras = metadatos_responsable("documento.docx")
        assert "organizacion" in extras
        assert "codigo" in extras


class TestCatalogos:
    def test_sha256_estable(self, tmp_path):
        ruta = tmp_path / "a.txt"
        ruta.write_bytes(b"contenido")
        assert sha256_archivo(ruta) == sha256_archivo(ruta)

    def test_ahora_iso(self):
        assert ahora_iso().endswith("+00:00") or "T" in ahora_iso()

    def test_registro_a_dict(self):
        r = RegistroEvidencia(
            documento="a.docx", ruta="/tmp/a.docx", tipo="docx",
            tipo_documento="procedimiento", ambitos=["calidad"],
            ambito_principal="calidad", paginas=1, bloques=1, chunks=1,
            caracteres=100, sha256="abc", modificado="0", indexado="2026-01-01",
            estado="indexado", notas=[],
        )
        d = r.to_dict()
        assert d["documento"] == "a.docx"
        assert d["estado"] == "indexado"
