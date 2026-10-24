"""Pruebas de la construcción del corpus de requisitos normativos."""
from __future__ import annotations

import pytest

from mvp_sig.knowledge.coherencia import medir_coherencia
from mvp_sig.knowledge.requirements import (
    construir_corpus_requisitos,
    construir_requisitos,
    detectar_clausula,
    escanear_encabezados,
    resumen_corpus,
    segmentar_por_clausula,
    texto_continuo,
)
from mvp_sig.settings import NORMAS


class TestDetectarClausula:
    def test_encabezado_al_inicio(self):
        texto = "7.5 Información documentada\n7.5.1 La organización debe establecer."
        assert detectar_clausula(texto) == "7.5"

    def test_numeral_en_primera_linea_util(self):
        texto = (
            "Esta es una linea introductoria suficientemente larga para ser util.\n"
            "8.1 La organización debe planificar y hacer frente a los procesos."
        )
        assert detectar_clausula(texto) == "8.1"

    def test_anexo(self):
        assert detectar_clausula("ANEXO A\nContenido del anexo") == "Anexo A"

    def test_texto_sin_clausula_devuelve_defecto(self):
        assert detectar_clausula("Texto sin numeracion alguna", "0") == "0"


class TestCasosLimite:
    """Casos reales extraídos del texto de las normas.

    Regresan sobre errores concretos del detector: cada caso reproduce un
    fragmento tal como lo entrega el extractor de PDF.
    """

    def test_subnumero_no_se_participa(self):
        """«8.2.3.2» debe leerse como la cláusula completa, no como «2.3.2»."""
        texto = "8.2.3.2 Preparación de la información para la revisión"
        assert detectar_clausula(texto) == "8.2.3.2"

    def test_referencia_cruzada_se_descarta(self):
        """«véase el apartado 8.2» es una referencia, no un encabezado."""
        texto = "véase el apartado 8.2 Requisitos para productos y servicios"
        assert detectar_clausula(texto) == "0"

    def test_encabezado_de_anexo(self):
        """«A.4.2» pertenece al Anexo A, no a la cláusula 4.2."""
        texto = "A.4.2 Pensamiento basado en riesgos"
        assert detectar_clausula(texto) == "Anexo A.4.2"

    def test_acronimo_no_genera_anexo(self):
        """La «T» final de «SST» no es la letra de un anexo."""
        texto = "de la SST.4.2 Comprensión de las necesidades"
        assert detectar_clausula(texto) == "4.2"

    def test_encabezado_pegado_a_enumeracion(self):
        """El extractor glosa la referencia y el encabezado: «4.2» + «5 Liderazgo».

        El detector debe reanclar el encabezado en su último componente y
        devolver la cláusula 5, no la referencia «4.2».
        """
        texto = "apartados 4.1 y 4.2.5 Liderazgo"
        assert detectar_clausula(texto) == "5"

    def test_encabezado_anunciado_por_dos_puntos(self):
        """«...definiciones siguientes: 3.1 Términos...» anuncia un encabezado."""
        texto = "los términos y definiciones siguientes: 3.1 Términos y definiciones"
        assert detectar_clausula(texto) == "3.1"

    def test_palabra_partida_por_el_pdf(self):
        """El extractor parte palabras: «acción correctiv a. 10.3 Mejora»."""
        texto = "acción correctiv a. 10.3 Mejora continua"
        assert detectar_clausula(texto) == "10.3"

    def test_lista_numerada_no_es_encabezado(self):
        """«véanse 6.1.4, 6.2, 7, 8 y 9.1» es una enumeración de referencias."""
        texto = "véanse 6.1.4, 6.2, 7, 8 y 9.1 Requisitos"
        assert detectar_clausula(texto) == "0"

    def test_nota_numerada_no_es_encabezado(self):
        """«NOTA 1» es un bloque informativo, no la cláusula 1."""
        texto = "NOTA 1 En esta Norma Internacional se puede interpretar el término"
        assert detectar_clausula(texto) == "0"

    def test_motivos_de_rechazo_se_registran(self):
        """El detector deja constancia de por qué descartó cada candidato."""
        diagnostico: list = []
        escanear_encabezados(
            "véase el apartado 8.2 Requisitos para productos y servicios",
            diagnostico=diagnostico,
        )
        assert diagnostico, "No se registró ningún rechazo"
        motivos = {m for _pos, _dato, _tipo, m in diagnostico}
        assert any("referencia cruzada" in m for m in motivos)


class TestSegmentacion:
    def test_cada_segmento_pertenece_a_una_sola_clausula(self):
        for key in NORMAS:
            texto, _ = texto_continuo(key)
            segmentos = segmentar_por_clausula(texto)
            assert segmentos
            for seg in segmentos:
                assert seg.clausula
                assert seg.texto.strip()
                assert seg.fin > seg.inicio

    def test_el_encabezado_abre_el_segmento(self):
        for key in NORMAS:
            texto, _ = texto_continuo(key)
            for seg in segmentar_por_clausula(texto):
                if not seg.encabezado:
                    continue
                assert seg.texto.lstrip().lower().startswith(
                    seg.encabezado.strip().lower()
                ), f"{key} {seg.clausula}: {seg.texto[:60]!r}"

    def test_las_clausulas_raiz_1_a_10_existen(self):
        for key in NORMAS:
            texto, _ = texto_continuo(key)
            detectadas = {e.clausula for e in escanear_encabezados(texto)}
            for raiz in range(1, 11):
                assert str(raiz) in detectadas, f"{key} no tiene la cláusula {raiz}"


class TestCorpusRequisitos:
    def test_cada_norma_produce_requisitos(self):
        for key in NORMAS:
            requisitos = construir_requisitos(key)
            assert requisitos, f"{key} no produjo requisitos"
            for r in requisitos:
                assert r.norma == key
                assert r.ambito == NORMAS[key].ambito
                assert r.texto.strip()
                assert r.clausula

    def test_identificadores_unicos(self):
        requisitos = construir_corpus_requisitos()
        ids = [r.id for r in requisitos]
        duplicados = {i for i in ids if ids.count(i) > 1}
        assert not duplicados, f"Identificadores duplicados: {sorted(duplicados)[:10]}"

    def test_filtro_por_norma(self):
        requisitos = construir_corpus_requisitos(["ISO45001"])
        assert requisitos
        assert all(r.norma == "ISO45001" for r in requisitos)

    def test_clausulas_sig_marcadas_como_transversales(self):
        requisitos = construir_corpus_requisitos()
        sig = [r for r in requisitos if r.metadatos.get("clausula_sig")]
        assert sig, "No se detectaron cláusulas estructurales del SIG"
        assert all(r.metadatos.get("ambito_transversal") for r in sig)

    def test_resumen_corpus(self):
        resumen = resumen_corpus(construir_corpus_requisitos())
        assert resumen["total"] > 0
        assert set(resumen["por_norma"]) == set(NORMAS)
        assert resumen["caracteres"] > 0

    def test_filtro_solo_normativos(self):
        completo = construir_corpus_requisitos()
        normativos = construir_corpus_requisitos(solo_normativos=True)
        assert 0 < len(normativos) < len(completo)
        assert all(r.metadatos.get("normativo") for r in normativos)
        assert all(r.tipo == "requisito" for r in normativos)
        # El catálogo completo conserva también el contenido informativo.
        assert any(r.tipo == "informativo" for r in completo)

    def test_la_introduccion_no_es_requisito(self):
        """La cláusula 0 es informativa por definición (Directivas ISO/IEC 2)."""
        for r in construir_corpus_requisitos():
            assert not r.clausula.startswith("0"), f"{r.id} procede de la introducción"


class TestCoherencia:
    """La atribución de cláusulas se verifica contra el documento original."""

    @pytest.fixture(scope="class")
    def medicion(self):
        return medir_coherencia()

    def test_no_hay_identificadores_duplicados(self, medicion):
        assert not medicion["duplicados"]

    def test_todo_requisito_se_reancla_en_su_clausula(self, medicion):
        """Cada requisito se localiza en el documento dentro de su cláusula."""
        for item in medicion["por_norma"]:
            a = item["reanclaje"]
            assert a["no_localizados"] == 0, f"{item['norma']}: requisitos no localizados"
            assert not a["desalineados"], (
                f"{item['norma']}: {[r.id for r, _ in a['desalineados']][:5]}"
            )
            assert a["porcentaje"] >= 95.0

    def test_cada_tramo_abre_con_su_encabezado(self, medicion):
        for item in medicion["por_norma"]:
            b = item["encabezados_segmento"]
            assert not b["fallos"], f"{item['norma']}: {len(b['fallos'])} tramos sin encabezado"
            assert b["porcentaje"] >= 95.0

    def test_ninguna_subclausula_esta_hoiuda(self, medicion):
        for item in medicion["por_norma"]:
            assert not item["huerfanos"], f"{item['norma']}: {item['huerfanos']}"

    def test_indice_global(self, medicion):
        assert medicion["indice_global"] >= 95.0
