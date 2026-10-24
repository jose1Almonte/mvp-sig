"""Pruebas de los proveedores de LLM y del parseo de JSON."""
from __future__ import annotations

import json

import pytest

from mvp_sig.llm.provider import (
    LLMProvider,
    LLMResponse,
    crear_proveedor,
    parsear_json,
    proveedores_disponibles,
)


class TestParsearJson:
    def test_json_puro(self):
        assert parsear_json('{"a": 1}') == {"a": 1}

    def test_cercas_markdown(self):
        assert parsear_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_cercas_sin_lenguaje(self):
        assert parsear_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_texto_antes_del_json(self):
        assert parsear_json('Aqui tienes el resultado:\n{"a": 1}') == {"a": 1}

    def test_texto_despues_del_json(self):
        assert parsear_json('{"a": 1}\nEspero que sea util.') == {"a": 1}

    def test_json_anidado(self):
        assert parsear_json('{"a": {"b": [1, 2, 3]}}') == {"a": {"b": [1, 2, 3]}}

    def test_lista(self):
        assert parsear_json('[{"a": 1}]') == [{"a": 1}]

    def test_texto_invalido(self):
        assert parsear_json("no es json en absoluto") is None

    def test_vacio(self):
        assert parsear_json("") is None

    def test_json_con_acentos(self):
        assert parsear_json('{"a": "gestión"}') == {"a": "gestión"}


class TestLLMResponse:
    def test_ok_true(self):
        assert LLMResponse(texto='{"a": 1}', modelo="m", proveedor="p").ok

    def test_ok_false_con_error(self):
        assert not LLMResponse(texto="x", modelo="m", proveedor="p", error="boom").ok

    def test_ok_false_sin_texto(self):
        assert not LLMResponse(texto="  ", modelo="m", proveedor="p").ok

    def test_json_delegates_en_parsear_json(self):
        r = LLMResponse(texto='```json\n{"a": 1}\n```', modelo="m", proveedor="p")
        assert r.json() == {"a": 1}


class TestProveedores:
    def test_crear_ollama(self):
        p = crear_proveedor("ollama", "llama3.1:8b")
        assert isinstance(p, LLMProvider)
        assert p.nombre == "ollama"
        assert p.modelo == "llama3.1:8b"

    def test_crear_openai(self):
        p = crear_proveedor("openai", "gpt-4o-mini")
        assert p.nombre == "openai"

    def test_crear_anthropic(self):
        p = crear_proveedor("anthropic", "claude-3-5-sonnet-latest")
        assert p.nombre == "anthropic"

    def test_crear_openrouter(self):
        p = crear_proveedor("openrouter", "openai/gpt-4o-mini")
        assert p.nombre == "openrouter"

    def test_proveedor_desconocido_falla_con_mensaje_claro(self):
        with pytest.raises(ValueError) as exc:
            crear_proveedor("inexistente", "x")
        assert "Proveedor desconocido" in str(exc.value)

    def test_info(self):
        info = crear_proveedor("ollama", "llama3.1:8b").info()
        assert info["proveedor"] == "ollama"
        assert info["modelo"] == "llama3.1:8b"

    def test_inventario_de_proveedores(self):
        items = proveedores_disponibles()
        assert isinstance(items, list)
        assert items
        for item in items:
            assert "nombre" in item or "proveedor" in item
