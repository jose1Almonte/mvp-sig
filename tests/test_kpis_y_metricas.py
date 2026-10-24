"""Pruebas de la matriz de indicadores (KPI) y de las métricas de evaluación."""
from __future__ import annotations

import csv
import json

import pytest

from mvp_sig.diagnosis.kpis import (
    CATALOGO_CURADO,
    analizar_consistencia,
    construir_matriz_kpis,
    derivar_kpis_normativos,
    exportar_kpis,
    exportar_kpis_json,
)
from mvp_sig.evaluation.goldset import CASOS, CasoGold
from mvp_sig.evaluation.metrics import comparar_modelos, evaluar_caso, evaluar_recuperacion
from mvp_sig.knowledge.requirements import construir_corpus_requisitos


class TestCatalogoKpis:
    def test_catalogo_no_vacio(self):
        assert len(CATALOGO_CURADO) >= 15

    def test_cada_kpi_tiene_los_campos_obligatorios(self):
        for k in CATALOGO_CURADO:
            for campo in ("id", "nombre", "ambito", "norma", "clausula_fuente", "formula"):
                assert k.get(campo), f"El KPI {k.get('id')} no tiene '{campo}'"

    def test_identificadores_unicos(self):
        ids = [k["id"] for k in CATALOGO_CURADO]
        assert len(ids) == len(set(ids))

    def test_cubre_los_tres_ambitos(self):
        ambitos = {k["ambito"] for k in CATALOGO_CURADO}
        assert {"calidad", "ambiente", "seguridad"} <= ambitos

    def test_formulas_sin_placeholders_rotos(self):
        """Ninguna fórmula puede quedar con un marcador de plantilla sin sustituir."""
        for k in CATALOGO_CURADO:
            formula = k["formula"]
            assert "{" not in formula, f"Fórmula con plantilla sin resolver en {k['id']}"
            assert formula.count("(") == formula.count(")"), f"Paréntesis desbalanceados en {k['id']}"


class TestMatrizKpis:
    def test_construye_indicadores(self):
        kpis = construir_matriz_kpis(construir_corpus_requisitos())
        assert kpis
        analisis = analizar_consistencia(kpis)
        assert isinstance(analisis, dict)

    def test_incluye_catalogo_y_derivados(self):
        kpis = construir_matriz_kpis(construir_corpus_requisitos())
        origenes = {k.origen for k in kpis}
        assert "catalogo" in origenes

    def test_analisis_de_consistencia(self):
        kpis = construir_matriz_kpis(construir_corpus_requisitos())
        analisis = analizar_consistencia(kpis)
        assert isinstance(analisis, dict)
        assert analisis.get("total_kpis", 0) == len(kpis)

    def test_exportar_csv(self, tmp_path):
        kpis = construir_matriz_kpis(construir_corpus_requisitos())
        ruta = exportar_kpis(kpis, tmp_path / "kpis.csv")
        with ruta.open(encoding="utf-8-sig") as fh:
            filas = list(csv.DictReader(fh))
        assert len(filas) == len(kpis)

    def test_exportar_json(self, tmp_path):
        kpis = construir_matriz_kpis(construir_corpus_requisitos())
        analisis = analizar_consistencia(kpis)
        ruta = exportar_kpis_json(kpis, analisis, tmp_path / "kpis.json")
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert "kpis" in datos
        assert len(datos["kpis"]) == len(kpis)


class TestGoldSet:
    def test_tiene_20_casos(self):
        assert len(CASOS) == 20

    def test_casos_consistentes(self):
        for c in CASOS:
            assert c.id
            assert c.consulta
            assert c.documentos_esperados
            assert c.norma in {"ISO9001", "ISO14001", "ISO45001"}

    def test_identificadores_unicos(self):
        ids = [c.id for c in CASOS]
        assert len(ids) == len(set(ids))

    def test_coincidencia_exacta(self):
        caso = CasoGold(
            id="T", consulta="q", norma="ISO9001", clausula="7.5", ambito="calidad",
            documentos_esperados=["Control de Documentos"],
        )
        assert caso.coincide("Control de Documentos.docx")
        assert not caso.coincide("Algo completamente distinto")

    def test_coincidencia_tolerante_a_acentos(self):
        caso = CasoGold(
            id="T", consulta="q", norma="ISO14001", clausula="6.1.2", ambito="ambiente",
            documentos_esperados=["Identificación de Aspectos"],
        )
        assert caso.coincide("Identificacion de Aspectos Ambientales.xlsx")

    def test_cubre_los_tres_ambitos(self):
        ambitos = {c.ambito for c in CASOS}
        assert {"calidad", "ambiente", "seguridad"} <= ambitos

    def test_la_extension_no_rompe_el_match_por_tokens(self):
        """La extensión se descarta antes de comparar por tokens.

        Sin este tratamiento, "gestion.docx" y "gestion" son tokens
        distintos y el solapamiento cae por debajo del umbral.
        """
        caso = CasoGold(
            id="T", consulta="q", norma="ISO9001", clausula="4.3", ambito="integral",
            documentos_esperados=["Alcance del Sistema Integrado de Gestion"],
        )
        assert caso.coincide("2. Manual del Sistema Integrado de Gestión.docx")
        assert caso.coincide("Alcance del Sistema Integrado de Gestion.pdf")
        assert not caso.coincide("Perfil del Cargo Auxiliar Contable.docx")

    def test_los_documentos_esperados_existen_en_el_corpus_real(self):
        """Ningún caso del gold set puede ser inrespondible."""
        import json

        from mvp_sig.settings import PATHS
        from mvp_sig.utils.text import normalizar

        ruta = PATHS.catalog / "catalogo_evidencias.json"
        if not ruta.exists():
            pytest.skip("El corpus real no ha sido ingerido en este entorno")
        cat = json.loads(ruta.read_text(encoding="utf-8"))
        corpus = {normalizar(r["documento"]) for r in cat["registros"]}

        for caso in CASOS:
            for esperado in caso.documentos_esperados:
                e = normalizar(esperado)
                assert any(e in c or c in e for c in corpus), (
                    f"{caso.id}: '{esperado}' no está en el corpus ingerido"
                )


class TestMetricasRecuperacion:
    def test_evaluar_recuperacion_sobre_gold_set(self, store_con_evidencias):
        m = evaluar_recuperacion(store_con_evidencias, CASOS, k=5)
        assert m["casos"] == len(CASOS)
        for clave in ("precision@k", "recall@k", "mrr", "ndcg@k"):
            assert clave in m
            assert 0.0 <= m[clave] <= 1.0

    def test_evaluar_caso_sin_fragmentos(self, store_con_evidencias):
        resultado = evaluar_caso(CASOS[0], [], k=5)
        assert resultado.precision == 0.0
        assert resultado.recall == 0.0
        assert resultado.mrr == 0.0

    def test_se_reportan_los_dos_niveles(self, store_con_evidencias):
        m = evaluar_recuperacion(store_con_evidencias, CASOS, k=5)
        for clave in (
            "precision@k", "recall@k", "mrr", "ndcg@k",
            "precision@k_documento", "recall@k_documento",
            "mrr_documento", "ndcg@k_documento",
        ):
            assert clave in m
            assert 0.0 <= m[clave] <= 1.0

    def test_el_nivel_documento_agrega_los_fragmentos(self, store_con_evidencias):
        """El mismo documento troceado en varios fragmentos cuenta una vez."""
        from mvp_sig.evaluation.metrics import evaluar_caso_documento
        from mvp_sig.knowledge.vectorstore import FragmentoRecuperado

        caso = CasoGold(
            id="T", consulta="q", norma="ISO9001", clausula="7.5", ambito="calidad",
            documentos_esperados=["Control de Documentos"],
        )
        frags = [
            FragmentoRecuperado(
                id=f"f{i}", texto="texto", puntaje=0.9,
                metadatos={"documento": "Control de Documentos.docx"},
                coleccion="evidencias",
            )
            for i in range(4)
        ]
        r = evaluar_caso_documento(caso, frags, k=5)
        assert r.precision == 1.0
        assert r.recall == 1.0
        assert r.documentos_obtenidos == ["Control de Documentos.docx"]

    def test_el_nivel_fragmento_y_el_documento_difieren(self, store_con_evidencias):
        """El nivel de fragmento cuenta trozos; el de documento, documentos.

        Con 3 trozos del documento relevante y 2 de uno irrelevante:
        a nivel de fragmento la precisión es 3/5; a nivel de documento, 1/2.
        """
        from mvp_sig.evaluation.metrics import evaluar_caso, evaluar_caso_documento
        from mvp_sig.knowledge.vectorstore import FragmentoRecuperado

        caso = CasoGold(
            id="T", consulta="q", norma="ISO9001", clausula="7.5", ambito="calidad",
            documentos_esperados=["Control de Documentos"],
        )

        def frag(i: int, doc: str) -> FragmentoRecuperado:
            return FragmentoRecuperado(
                id=f"f{i}", texto="texto", puntaje=0.9,
                metadatos={"documento": doc}, coleccion="evidencias",
            )

        frags = [
            frag(0, "Control de Documentos.docx"),
            frag(1, "Control de Documentos.docx"),
            frag(2, "Control de Documentos.docx"),
            frag(3, "Perfil del Cargo.docx"),
            frag(4, "Perfil del Cargo.docx"),
        ]
        r_frag = evaluar_caso(caso, frags, k=5)
        r_doc = evaluar_caso_documento(caso, frags, k=5)

        assert r_frag.precision == 0.6      # 3 de 5 trozos son del documento útil
        assert r_doc.precision == 0.5       # 1 de 2 documentos
        assert r_frag.recall == r_doc.recall == 1.0


class TestCompararModelos:
    def test_requiere_dos_modelos(self):
        assert comparar_modelos({"a": []}) == {}

    def test_acuerdo_entre_modelos(self):
        from mvp_sig.diagnosis.engine import ResultadoDiagnostico

        def mk(rid, veredicto):
            return ResultadoDiagnostico(
                requisito_id=rid, norma="ISO9001", clausula="7.5", ambito="calidad",
                requisito_texto="x", veredicto=veredicto, confianza=0.5,
                confianza_evidence=0.5, justificacion="",
            )

        datos = {
            "m1": [mk("A", "CUMPLE"), mk("B", "NO_CUMPLE")],
            "m2": [mk("A", "CUMPLE"), mk("B", "CUMPLE")],
        }
        r = comparar_modelos(datos)
        assert r["requisitos_comparados"] == 2
        assert r["resumen"]["m1"]["acuerdo_con_otros"] == 0.5
