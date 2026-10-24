"""Pruebas de la limpieza, segmentación y verificación de citas."""
from __future__ import annotations

from pathlib import Path

import pytest

from mvp_sig.ingestion.cleaner import (
    Chunk,
    limpiar_documento,
    pre_limpiar_cita,
    segmentar_bloque,
    sufijo_ruta,
    verificar_cita,
)
from mvp_sig.ingestion.extractors import Bloque, DocumentoExtraido


def _bloque(texto: str, **kw) -> Bloque:
    return Bloque(texto=texto, **kw)


class TestLimpiarDocumento:
    def test_descarta_bloques_muy_cortos(self):
        doc = DocumentoExtraido(
            ruta=Path("x.pdf"),
            nombre="x.pdf",
            tipo="pdf",
            bloques=[_bloque("texto suficiente para pasar el filtro"), _bloque("corto")],
        )
        bloques = limpiar_documento(doc)
        assert len(bloques) == 1

    def test_conserva_referencia_de_pagina(self):
        doc = DocumentoExtraido(
            ruta=Path("x.pdf"),
            nombre="x.pdf",
            tipo="pdf",
            bloques=[_bloque("contenido valido del bloque de prueba", pagina=7)],
        )
        bloques = limpiar_documento(doc)
        assert bloques[0].pagina == 7

    def test_elimina_encabezado_repetido_en_pdf(self):
        bloques = [
            _bloque("ENCABEZADO COMUN\ncontenido de la pagina uno", pagina=1),
            _bloque("ENCABEZADO COMUN\ncontenido de la pagina dos", pagina=2),
            _bloque("ENCABEZADO COMUN\ncontenido de la pagina tres", pagina=3),
        ]
        doc = DocumentoExtraido(
            ruta=Path("x.pdf"), nombre="x.pdf", tipo="pdf", bloques=bloques
        )
        salida = limpiar_documento(doc)
        for b in salida:
            assert "ENCABEZADO COMUN" not in b.texto
        assert len(salida) == 3


class TestSegmentarBloque:
    def test_texto_corto_genera_un_chunk(self):
        chunks = segmentar_bloque(
            "Texto breve del bloque.", _bloque("Texto breve del bloque."),
            documento="doc.docx", ruta="/tmp/doc.docx",
        )
        assert len(chunks) == 1
        assert chunks[0].documento == "doc.docx"

    def test_texto_largo_genera_varios_chunks(self):
        texto = "\n".join(f"Parrafo numero {i} con contenido suficiente." for i in range(200))
        chunks = segmentar_bloque(
            texto, _bloque(texto), documento="doc.docx", ruta="/tmp/doc.docx"
        )
        assert len(chunks) > 1

    def test_identificadores_unicos_dentro_del_documento(self):
        texto = "\n".join(f"Parrafo {i} con texto holgado para segmentar." for i in range(60))
        chunks = []
        for i in range(3):
            chunks.extend(
                segmentar_bloque(
                    texto, _bloque(texto, seccion="Misma seccion"),
                    documento="doc.docx", ruta="/tmp/doc.docx",
                    offset=len(chunks),
                )
            )
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids)), "Los identificadores de fragmento deben ser únicos"

    def test_offset_produce_identificadores_distintos(self):
        texto = "Contenido del bloque para la segmentación."
        a = segmentar_bloque(
            texto, _bloque(texto), documento="d.docx", ruta="/tmp/d.docx", offset=0
        )[0]
        b = segmentar_bloque(
            texto, _bloque(texto), documento="d.docx", ruta="/tmp/d.docx", offset=1
        )[0]
        assert a.id != b.id

    def test_rutas_distintas_generan_sufijos_distintos(self):
        assert sufijo_ruta("/a/doc.docx") != sufijo_ruta("/b/doc.docx")

    def test_mismo_nombre_rutas_distintas_no_colisiona(self):
        """El corpus CIL ONG tiene 17 nombres de archivo repetidos."""
        texto = "Contenido del bloque para la segmentación."
        a = segmentar_bloque(
            texto, _bloque(texto), documento="Igual.docx", ruta="/grupo1/Igual.docx"
        )[0]
        b = segmentar_bloque(
            texto, _bloque(texto), documento="Igual.docx", ruta="/grupo2/Igual.docx"
        )[0]
        assert a.id != b.id

    def test_posicion_es_creciente(self):
        texto = "\n".join(f"Linea {i} con texto suficiente para el bloque." for i in range(40))
        chunks = segmentar_bloque(
            texto, _bloque(texto), documento="d.docx", ruta="/tmp/d.docx"
        )
        posiciones = [c.posicion for c in chunks]
        assert posiciones == sorted(posiciones)
        assert len(set(posiciones)) == len(posiciones)

    def test_metadatos_incluyen_ambito_y_documento(self):
        chunks = segmentar_bloque(
            "Contenido del bloque para la segmentación.",
            _bloque("Contenido del bloque para la segmentación.", pagina=3),
            documento="d.docx", ruta="/tmp/d.docx", tipo="docx",
            ambitos=["calidad", "integral"], ambito_principal="calidad",
        )
        meta = chunks[0].to_metadata()
        assert meta["documento"] == "d.docx"
        assert meta["ambito"] == "calidad"
        assert meta["ambitos"] == "calidad|integral"
        assert meta["pagina"] == 3


class TestVerificacionCitas:
    def test_cita_literal_se_verifica(self):
        fragmentos = {"f1": "La organización debe establecer un listado maestro."}
        assert verificar_cita(fragmentos, "establecer un listado maestro")

    def test_cita_inexistente_no_se_verifica(self):
        fragmentos = {"f1": "La organización debe establecer un listado maestro."}
        assert not verificar_cita(fragmentos, "el comite auditorfro approvesa el presupuesto")

    def test_cita_vacia_no_se_verifica(self):
        assert not verificar_cita({"f1": "texto"}, "")


class TestPreLimpiarCita:
    def test_quita_comillas(self):
        assert pre_limpiar_cita('"texto citado"') == "texto citado"

    def test_quita_vinetas(self):
        assert pre_limpiar_cita("- texto citado") == "texto citado"

    def test_quita_numeracion(self):
        assert pre_limpiar_cita("[E1] texto citado") == "texto citado"
