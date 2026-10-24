"""Pruebas de las utilidades de texto (normalización, limpieza, similitud)."""
from __future__ import annotations

import pytest

from mvp_sig.utils.text import (
    colapsar_espacios,
    contiene_frase,
    detectar_lineas_repetidas,
    dividir_oraciones,
    eliminar_lineas_repetidas,
    limpiar_pies_de_pagina,
    limpiar_ruido_iso,
    normalizar,
    similaridad,
    strip_accents,
    truncar,
)


class TestNormalizacion:
    def test_normalizar_quita_acentos_y_mayusculas(self):
        assert normalizar("Gestión de RIESGOS") == "gestion de riesgos"

    def test_normalizar_conserva_la_enie(self):
        # La ñ se convierte en 'n' (no en un separador).
        assert normalizar("España") == "espana"

    def test_strip_accents_no_altera_el_resto(self):
        assert strip_accents("acción") == "accion"

    def test_normalizar_colapsa_espacios(self):
        assert normalizar("  a   b  ") == "a b"

    def test_colapsar_espacios_conserva_saltos_de_linea(self):
        assert colapsar_espacios("a  \n  b") == "a\nb"

    def test_colapsar_espacios_elimina_caracteres_de_control(self):
        assert colapsar_espacios("a\x00b") == "a b"


class TestLimpieza:
    def test_limpiar_pies_de_pagina(self):
        assert limpiar_pies_de_pagina("texto\n- 12 -\nfin").strip() == "texto\n\nfin"

    def test_limpiar_ruido_iso_quita_marca_de_agua(self):
        sucio = "Traducción oficial UNE-EN ISO 9001:2015 Texto relevante del requisito"
        limpio = limpiar_ruido_iso(sucio)
        assert "Traducción oficial" not in limpio
        assert "Texto relevante" in limpio

    def test_detectar_lineas_repetidas(self):
        paginas = ["Encabezado comun\n" + f"contenido {i}" for i in range(10)]
        repetidas = detectar_lineas_repetidas(paginas, ratio_minimo=0.35)
        assert "Encabezado comun" in repetidas

    def test_detectar_lineas_repetidas_ignora_pocas_paginas(self):
        assert detectar_lineas_repetidas(["a", "b"], min_paginas=3) == set()

    def test_eliminar_lineas_repetidas(self):
        texto = "Encabezado comun\ncontenido útil"
        limpio = eliminar_lineas_repetidas(texto, {"Encabezado comun"})
        assert "Encabezado comun" not in limpio
        assert "contenido útil" in limpio


class TestSimilitud:
    def test_similaridad_igual(self):
        assert similaridad("hola mundo", "hola mundo") == 1.0

    def test_similaridad_texto_vacio(self):
        assert similaridad("", "hola") == 0.0

    def test_similaridad_subcadena(self):
        assert similaridad("hola", "hola mundo entero") == 1.0

    def test_similaridad_diferente(self):
        assert similaridad("pollo", "automóvil") < 0.5


class TestContieneFrase:
    def test_frase_literal(self):
        assert contiene_frase("La organización debe documentar", "debe documentar")

    def test_frase_inexistente(self):
        assert not contiene_frase("La organización debe documentar", "revisar auditos")

    def test_frase_con_acentos_diferentes(self):
        assert contiene_frase("La gestión de riesgos", "gestion de riesgos")

    def test_frase_vacia(self):
        assert not contiene_frase("texto", "")

    def test_frase_corta_no_genera_falsos_positivos(self):
        # Las frases de menos de 40 caracteres no se comparan por ventana.
        assert not contiene_frase("texto completamente distinto", "otro")


class TestOraciones:
    def test_dividir_por_punto(self):
        partes = dividir_oraciones("Uno. Dos. Tres.")
        assert partes == ["Uno.", "Dos.", "Tres."]

    def test_no_separa_por_abreviatura(self):
        partes = dividir_oraciones("Ver el cap. 3 del manual. Luego continuar.")
        assert len(partes) == 2

    def test_no_separa_por_numero_decimal(self):
        partes = dividir_oraciones("El valor 3.5 es valido. Fin.")
        assert len(partes) == 2

    def test_texto_vacio(self):
        assert dividir_oraciones("") == []


def test_truncar_no_altera_textos_cortos():
    assert truncar("hola", 100) == "hola"


def test_truncar_corta_en_palabra():
    resultado = truncar("palabra uno palabra dos palabra tres", 20)
    assert resultado.endswith("...")
    assert len(resultado) < 40
