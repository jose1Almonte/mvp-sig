"""Pruebas del modelo de costes y del cuadro de costo-efectividad.

La pregunta de investigación nº 4 del anteproyecto («¿cuál es el modelo de
lenguaje más costo-efectivo?») sólo tiene respuesta si el coste se calcula de
forma explícita y reproducible.  Estas pruebas comprueban el aritmética del
modelo y que los modelos no ejecutados queden declarados como tales, no como
mediciones.
"""
from __future__ import annotations

import pytest

from mvp_sig.evaluation import costos
from mvp_sig.evaluation.benchmark import CorridaBenchmark, motivo_no_disponible


# --------------------------------------------------------------------------- #
# Catálogo de modelos
# --------------------------------------------------------------------------- #
class TestCatalogo:
    def test_los_siete_modelos_del_anteproyecto_estan_declarados(self):
        for clave in costos.CLAVES_ANTEPROYECTO:
            ref = costos.por_clave(clave)
            assert ref is not None, f"falta el modelo {clave}"

    def test_los_modelos_comerciales_tienen_precio(self):
        for clave in ("gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet", "claude-3-5-opus"):
            ref = costos.por_clave(clave)
            assert ref.precio_entrada > 0
            assert ref.precio_salida > 0

    def test_los_modelos_abiertos_locales_no_cuestan_api(self):
        ref = costos.por_clave("llama3.2")
        assert ref.precio_entrada == 0.0
        assert ref.precio_salida == 0.0
        assert ref.disponible_local is True

    def test_opus_es_mas_caro_que_sonnet(self):
        opus = costos.por_clave("claude-3-5-opus")
        sonnet = costos.por_clave("claude-3-5-sonnet")
        assert opus.coste_por_millon > sonnet.coste_por_millon

    def test_buscar_por_varias_formas(self):
        assert costos.buscar("gpt-4o-mini").clave == "gpt-4o-mini"
        assert costos.buscar("gpt-4o-mini").clave == "gpt-4o-mini"
        assert costos.buscar("Claude 3.5 Sonnet").clave == "claude-3-5-sonnet"
        assert costos.buscar("no-existe") is None

    def test_buscar_tolera_la_etiqueta_de_ollama(self):
        # Así es como Ollama nombra los modelos en las corridas reales.
        assert costos.buscar("llama3.2:latest").clave == "llama3.2"
        assert costos.buscar("llama3.1:8b").clave == "llama3.1:8b"
        assert costos.buscar("gpt-oss:120b-cloud").clave == "gpt-oss-120b"
        assert costos.buscar("claude-3-5-sonnet-latest").clave == "claude-3-5-sonnet"
        assert costos.buscar("mistral-large").clave == "mistral-large-2"

    def test_la_lista_de_ejecucion_cubre_los_siete(self):
        lista = costos.ejecutar_modelos_anteproyecto()
        assert len(lista) == 7


# --------------------------------------------------------------------------- #
# Aritmética del coste
# --------------------------------------------------------------------------- #
class TestCalculoDeCoste:
    def test_el_coste_es_lineal_con_los_tokens(self):
        ref = costos.por_clave("gpt-4o-mini")
        # 1M de entrada + 1M de salida = 0.15 + 0.60 = 0.75 USD
        assert costos.estimar_coste(1_000_000, 1_000_000, ref) == pytest.approx(0.75)

    def test_el_coste_de_un_modelo_gratuito_es_cero(self):
        ref = costos.por_clave("llama3.2")
        assert costos.estimar_coste(2_000, 500, ref) == 0.0

    def test_el_coste_es_menor_para_el_modelo_mas_barato(self):
        mini = costos.por_clave("gpt-4o-mini")
        opus = costos.por_clave("claude-3-5-opus")
        assert costos.estimar_coste(2000, 500, mini) < costos.estimar_coste(2000, 500, opus)

    def test_un_modelo_desconocido_falla_explicitamente(self):
        with pytest.raises(KeyError):
            costos.estimar_coste(100, 100, "modelo-inventado")

    def test_el_coste_del_diagnostico_completo_es_consistente(self):
        ref = costos.por_clave("gpt-4o-mini")
        r = costos.coste_diagnosis_completo(2000, 500, 154, ref)
        # 154 * (2000*0.15 + 500*0.60) / 1e6 = 154 * 0.0006 = 0.0924 USD
        assert r["coste_usd"] == pytest.approx(0.0924, abs=0.0002)
        assert r["requisitos"] == 154
        assert r["tokens_entrada"] == 154 * 2000

    def test_el_coste_por_mil_es_consistente(self):
        ref = costos.por_clave("gpt-4o-mini")
        r = costos.coste_diagnosis_completo(2000, 500, 154, ref)
        assert r["coste_usd_por_mil_requisitos"] == pytest.approx(
            r["coste_usd"] / 154 * 1000, abs=0.001
        )


# --------------------------------------------------------------------------- #
# Cuadro de costo-efectividad
# --------------------------------------------------------------------------- #
def _corrida(etiqueta: str, estado: str = "ok", **extra) -> CorridaBenchmark:
    proveedor, _, modelo = etiqueta.partition("/")
    c = CorridaBenchmark(proveedor=proveedor, modelo=modelo)
    if estado != "ok":
        c.error = extra.get("error", "no disponible")
    else:
        c.resultados = []
        c.segundos = extra.get("segundos", 10.0)
        c._resumen_extra = extra  # type: ignore[attr-defined]
    return c


class TestCuadro:
    def test_un_modelo_no_ejecutado_aparece_como_estimacion(self, monkeypatch):
        corrida = CorridaBenchmark(proveedor="ollama", modelo="llama3.1:8b")
        monkeypatch.setattr(
            CorridaBenchmark,
            "resumen",
            lambda self: {
                "estado": "ok",
                "proveedor": self.proveedor,
                "modelo": self.modelo,
                "tasa_trazabilidad_verificada": 1.0,
                "latencia_media_s": 13.8,
                "tokens_promedio_entrada": 2324,
                "tokens_promedio_salida": 452,
                "costo_usd_total": 0.0,
            },
        )
        filas = costos.filas_costo_efectividad([corrida], requisitos_totales=154)
        etiquetas = {f.etiqueta for f in filas}
        # El modelo ejecutado aparece medido.
        assert "ollama/llama3.1:8b" in etiquetas
        # Y los comerciales que no se ejecutaron, como estimación.
        assert "openai/gpt-4o" in etiquetas
        for f in filas:
            if f.estado == "no ejecutado":
                assert "Estimado" in f.nota

    def test_el_informe_markdown_contiene_todos_los_modelos(self):
        filas = costos.filas_costo_efectividad([], requisitos_totales=154)
        md = costos.informe_markdown(filas, requisitos_totales=154)
        assert "Costo-efectividad" in md
        assert "Claude 3.5 Opus" in md
        assert "154" in md
        # La tabla tiene una línea por modelo.
        lineas = [l for l in md.splitlines() if l.startswith("| ") and "---" not in l]
        assert len(lineas) >= len(filas) + 1  # + cabecera


# --------------------------------------------------------------------------- #
# Motivo de indisponibilidad
# --------------------------------------------------------------------------- #
class TestMotivoDeIndisponibilidad:
    def test_sin_clave_de_api_lo_dice(self, monkeypatch):
        monkeypatch.setattr("mvp_sig.settings.OPENAI_API_KEY", "")
        m = motivo_no_disponible("openai", "gpt-4o")
        assert "OPENAI_API_KEY" in m

    def test_sin_modelo_instalado_lo_dice(self):
        m = motivo_no_disponible("ollama", "deepseek-v3")
        assert "deepseek-v3" in m
        assert "Ollama" in m
