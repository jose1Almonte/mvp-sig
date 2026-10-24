"""Pruebas del árbol canónico de cláusulas y de su conformidad.

La comprobación F valida la atribución de cláusulas contra la estructura de
las versiones oficiales de las normas.  Las pruebas comprueban tanto el
mecanismo (con texto sintético) como el resultado real sobre el corpus
semilla, que es el dato que la tesis afirma.
"""
from __future__ import annotations

import json

import pytest

from mvp_sig.knowledge.arbol_oficial import (
    RUTA_ARBOL,
    _coincide_titulo,
    cargar_arbol,
    medir_conformidad_arbol,
    titulo_de_encabezado,
)
from mvp_sig.knowledge.coherencia import medir_coherencia
from mvp_sig.knowledge.requirements import escanear_encabezados, texto_continuo

NORMAS = ("ISO9001", "ISO14001", "ISO45001")


# --------------------------------------------------------------------------- #
# El archivo de referencia
# --------------------------------------------------------------------------- #
class TestArbolOficial:
    def test_el_arbol_esta_disponible(self):
        assert RUTA_ARBOL.exists(), (
            "Falta data/seed/arbol_oficial.json; se genera con "
            "scripts/generar_arbol_oficial.py"
        )

    @pytest.mark.parametrize("norma", NORMAS)
    def test_cada_norma_tiene_arbol(self, norma):
        arbol = cargar_arbol(norma)
        assert len(arbol) >= 40, f"{norma}: sólo {len(arbol)} cláusulas oficiales"

    @pytest.mark.parametrize("norma", NORMAS)
    def test_el_arbol_cubre_las_clausulas_raiz(self, norma):
        arbol = cargar_arbol(norma)
        raices = {c for c in arbol if "." not in c and c.isdigit()}
        # 0 (Introducción) + 1..10
        assert {"1", "4", "7", "10"}.issubset(raices)

    @pytest.mark.parametrize("norma", NORMAS)
    def test_los_titulos_no_estan_vacios(self, norma):
        for clausula, titulo in cargar_arbol(norma).items():
            assert titulo.strip(), f"{norma}/{clausula}: título vacío"

    def test_el_arbol_declara_su_origen(self):
        datos = json.loads(RUTA_ARBOL.read_text(encoding="utf-8"))
        for norma in NORMAS:
            assert datos[norma]["pdf"], f"{norma}: sin referencia al PDF oficial"


# --------------------------------------------------------------------------- #
# Coincidencia de títulos
# --------------------------------------------------------------------------- #
class TestCoincidenciaDeTitulos:
    def test_titulo_identico(self):
        assert _coincide_titulo(
            "Información documentada", "Información documentada"
        )

    def test_titulo_con_conector_distinto(self):
        # "Objeto" vs "Objetivo": el resto del vocabulario coincide.
        assert _coincide_titulo(
            "Objetivo y campo de aplicación", "Objetivo y campo de aplicación"
        )

    def test_titulo_que_no_comparte_vocabulario(self):
        assert not _coincide_titulo(
            "Auditoría interna", "Planificación y control operacional"
        )

    def test_titulo_vacio_no_coincide(self):
        assert not _coincide_titulo("Auditoría interna", "")

    def test_ignora_las_palabras_vacias(self):
        assert _coincide_titulo(
            "Términos y definiciones", "Definiciones y términos"
        )


# --------------------------------------------------------------------------- #
# Extracción del título de un encabezado
# --------------------------------------------------------------------------- #
class TestTituloDeEncabezado:
    def test_la_region_comienza_por_el_titulo(self):
        texto = "7.5 Información documentada La organización debe determinar."
        encs = escanear_encabezados(texto)
        assert encs
        enc = encs[0]
        region = titulo_de_encabezado(texto, enc.posicion, enc.fin)
        assert region.startswith("Información documentada")

    def test_titulo_con_coma(self):
        texto = "10.2 Incidentes, no conformidades y acciones correctivas. Texto."
        encs = escanear_encabezados(texto)
        enc = encs[0]
        titulo = titulo_de_encabezado(texto, enc.posicion, enc.fin)
        assert titulo.startswith("Incidentes")

    def test_el_titulo_oficial_no_puede_estar_mas_adelante(self):
        # La comparación es posicional: un título que aparece a mitad del
        # enunciado no valida la cláusula.
        assert not _coincide_titulo(
            "Auditoría interna",
            "La organización debe programar una auditoría interna de su sistema.",
        )


# --------------------------------------------------------------------------- #
# Conformidad real sobre el corpus semilla
# --------------------------------------------------------------------------- #
class TestConformidadReal:
    @pytest.mark.parametrize("norma", NORMAS)
    def test_la_atribucion_coincide_con_el_arbol_oficial(self, norma):
        texto, _ = texto_continuo(norma)
        r = medir_conformidad_arbol(texto, norma)
        assert r["disponible"]
        assert r["ausentes"] == [], (
            f"{norma}: cláusulas oficiales no detectadas: {r['ausentes']}"
        )
        assert r["titulo_distinto"] == [], (
            f"{norma}: títulos que no coinciden con el oficial: "
            f"{r['titulo_distinto'][:3]}"
        )
        assert r["porcentaje_cobertura"] == 100.0
        assert r["porcentaje_titulo"] == 100.0

    def test_sin_arbol_la_comprobacion_se_omite(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "mvp_sig.knowledge.arbol_oficial.RUTA_ARBOL", tmp_path / "no-existe.json"
        )
        texto, _ = texto_continuo("ISO9001")
        r = medir_conformidad_arbol(texto, "ISO9001")
        assert r["disponible"] is False
        assert "motivo" in r


# --------------------------------------------------------------------------- #
# Integración con el índice global de coherencia
# --------------------------------------------------------------------------- #
class TestIntegracionCoherencia:
    def test_el_indice_global_incluye_la_comprobacion_f(self):
        r = medir_coherencia(["ISO9001"])
        assert "arbol_oficial" in r
        assert r["arbol_oficial"]["comprobaciones"] > 0
        assert r["arbol_oficial"]["porcentaje"] == 100.0
        # La comprobación F suma al total global.
        assert r["comprobaciones"] >= r["arbol_oficial"]["comprobaciones"]
        assert r["indice_global"] == 100.0
