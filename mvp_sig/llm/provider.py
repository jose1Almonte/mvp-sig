"""Proveedores de LLM intercambiables.

La arquitectura es independiente del modelo: el diagnóstico no sabe si detrás
hay Ollama en local o una API en la nube. Eso es exactamente lo que exige el
objetivo 3.3.c del anteproyecto (selección costo-efectiva del LLM).
"""
from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from mvp_sig.utils.http import crear_sesion, normalizar_url, pedir


@dataclass
class LLMResponse:
    """Respuesta normalizada de cualquier proveedor."""

    texto: str
    modelo: str
    proveedor: str
    latencia_s: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    crudo: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.texto.strip())

    def json(self) -> dict | list | None:
        """Extrae un objeto JSON de la respuesta (tolerante a cercas markdown)."""
        return parsear_json(self.texto)


def parsear_json(texto: str) -> dict | list | None:
    """Extrae JSON de una respuesta de LLM, tolerante a texto extra y cercas."""
    if not texto:
        return None
    limpio = texto.strip()
    limpio = re.sub(r"^```(?:json)?\s*", "", limpio)
    limpio = re.sub(r"\s*```$", "", limpio).strip()
    try:
        return json.loads(limpio)
    except (json.JSONDecodeError, ValueError):
        pass
    # Extraer el primer objeto/array balanceado.
    for apertura, cierre in (("{", "}"), ("[", "]")):
        inicio = limpio.find(apertura)
        if inicio == -1:
            continue
        profundidad = 0
        en_cadena = False
        escape = False
        for i in range(inicio, len(limpio)):
            ch = limpio[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                en_cadena = not en_cadena
                continue
            if en_cadena:
                continue
            if ch == apertura:
                profundidad += 1
            elif ch == cierre:
                profundidad -= 1
                if profundidad == 0:
                    try:
                        return json.loads(limpio[inicio : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


# --------------------------------------------------------------------------- #
# Interfaz base
# --------------------------------------------------------------------------- #
class LLMProvider(ABC):
    """Contrato mínimo que debe cumplir un motor de lenguaje."""

    nombre: str = "base"

    def __init__(self, modelo: str, temperatura: float = 0.0, max_tokens: int = 1200) -> None:
        self.modelo = modelo
        self.temperatura = temperatura
        self.max_tokens = max_tokens

    @abstractmethod
    def _chat(self, sistema: str, usuario: str, json_modo: bool) -> LLMResponse:
        ...

    def chat(self, sistema: str, usuario: str, *, json_modo: bool = False) -> LLMResponse:
        try:
            return self._chat(sistema, usuario, json_modo)
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(
                texto="",
                modelo=self.modelo,
                proveedor=self.nombre,
                error=f"{type(exc).__name__}: {exc}",
            )

    def disponible(self) -> bool:
        return True

    def info(self) -> dict:
        return {
            "proveedor": self.nombre,
            "modelo": self.modelo,
            "temperatura": self.temperatura,
            "max_tokens": self.max_tokens,
        }


# --------------------------------------------------------------------------- #
# Ollama (local)
# --------------------------------------------------------------------------- #
class OllamaProvider(LLMProvider):
    """LLM local servido por Ollama. Sin coste, sin salida a internet."""

    nombre = "ollama"

    def __init__(
        self,
        modelo: str | None = None,
        url: str | None = None,
        temperatura: float = 0.0,
        max_tokens: int = 1200,
        timeout: int = 600,
        timeout_conexion: int = 10,
        reintentos: int = 3,
    ) -> None:
        from mvp_sig.settings import MODELS

        super().__init__(modelo or MODELS.chat_model, temperatura, max_tokens)
        self.url = (url or MODELS.ollama_url).rstrip("/")
        self.timeout = timeout
        self.timeout_conexion = timeout_conexion
        self.reintentos = reintentos
        self._sesion = crear_sesion(
            self.url,
            timeout_conexion=timeout_conexion,
            timeout_lectura=timeout,
            reintentos=reintentos,
        )

    def _chat(self, sistema: str, usuario: str, json_modo: bool) -> LLMResponse:
        payload: dict = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperatura,
                "num_predict": self.max_tokens,
            },
        }
        if json_modo:
            payload["format"] = "json"

        inicio = time.perf_counter()
        r = pedir(self._sesion, "POST", "/api/chat", json=payload)
        datos = r.json()
        latencia = time.perf_counter() - inicio

        texto = (datos.get("message") or {}).get("content", "")
        return LLMResponse(
            texto=texto,
            modelo=self.modelo,
            proveedor=self.nombre,
            latencia_s=latencia,
            tokens_entrada=int(datos.get("prompt_eval_count") or 0),
            tokens_salida=int(datos.get("eval_count") or 0),
            crudo={"total_duration": datos.get("total_duration")},
        )

    def disponible(self) -> bool:
        try:
            r = pedir(self._sesion, "GET", "/api/tags", timeout=(5, 15))
            if r.status_code != 200:
                return False
            nombres = [m.get("name", "") for m in r.json().get("models", [])]
            return any(n.split(":")[0] == self.modelo.split(":")[0] for n in nombres)
        except Exception:  # noqa: BLE001
            return False


# --------------------------------------------------------------------------- #
# OpenAI
# --------------------------------------------------------------------------- #
class OpenAIProvider(LLMProvider):
    """API de OpenAI (Chat Completions)."""

    nombre = "openai"

    # USD por 1M de tokens (entrada/salida). Se pueden sobrescribir por env.
    PRECIO_ENTRADA = 0.15
    PRECIO_SALIDA = 0.60

    def __init__(
        self,
        modelo: str | None = None,
        api_key: str | None = None,
        temperatura: float = 0.0,
        max_tokens: int = 1200,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 180,
    ) -> None:
        from mvp_sig.settings import OPENAI_MODEL

        super().__init__(modelo or OPENAI_MODEL, temperatura, max_tokens)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _chat(self, sistema: str, usuario: str, json_modo: bool) -> LLMResponse:
        import requests

        payload = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            "temperature": self.temperatura,
            "max_tokens": self.max_tokens,
        }
        if json_modo:
            payload["response_format"] = {"type": "json_object"}

        inicio = time.perf_counter()
        r = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        datos = r.json()
        latencia = time.perf_counter() - inicio

        texto = datos["choices"][0]["message"]["content"]
        uso = datos.get("usage") or {}
        t_in = int(uso.get("prompt_tokens") or 0)
        t_out = int(uso.get("completion_tokens") or 0)
        return LLMResponse(
            texto=texto,
            modelo=self.modelo,
            proveedor=self.nombre,
            latencia_s=latencia,
            tokens_entrada=t_in,
            tokens_salida=t_out,
            costo_usd=(t_in * self.PRECIO_ENTRADA + t_out * self.PRECIO_SALIDA) / 1_000_000,
            crudo=datos,
        )

    def disponible(self) -> bool:
        return bool(self.api_key)


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
class AnthropicProvider(LLMProvider):
    """API de Anthropic (Claude)."""

    nombre = "anthropic"
    PRECIO_ENTRADA = 3.0
    PRECIO_SALIDA = 15.0

    def __init__(
        self,
        modelo: str | None = None,
        api_key: str | None = None,
        temperatura: float = 0.0,
        max_tokens: int = 1200,
        base_url: str = "https://api.anthropic.com/v1",
        version: str = "2023-06-01",
        timeout: int = 180,
    ) -> None:
        from mvp_sig.settings import ANTHROPIC_MODEL

        super().__init__(modelo or ANTHROPIC_MODEL, temperatura, max_tokens)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.timeout = timeout

    def _chat(self, sistema: str, usuario: str, json_modo: bool) -> LLMResponse:
        import requests

        if json_modo:
            usuario = usuario + "\n\nResponde EXCLUSIVAMENTE con un objeto JSON válido, sin texto adicional."

        payload = {
            "model": self.modelo,
            "system": sistema,
            "messages": [{"role": "user", "content": usuario}],
            "temperature": self.temperatura,
            "max_tokens": self.max_tokens,
        }
        inicio = time.perf_counter()
        r = requests.post(
            f"{self.base_url}/messages",
            json=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.version,
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        datos = r.json()
        latencia = time.perf_counter() - inicio

        texto = "".join(b.get("text", "") for b in datos.get("content", []))
        uso = datos.get("usage") or {}
        t_in = int(uso.get("input_tokens") or 0)
        t_out = int(uso.get("output_tokens") or 0)
        return LLMResponse(
            texto=texto,
            modelo=self.modelo,
            proveedor=self.nombre,
            latencia_s=latencia,
            tokens_entrada=t_in,
            tokens_salida=t_out,
            costo_usd=(t_in * self.PRECIO_ENTRADA + t_out * self.PRECIO_SALIDA) / 1_000_000,
            crudo=datos,
        )

    def disponible(self) -> bool:
        return bool(self.api_key)


# --------------------------------------------------------------------------- #
# OpenRouter
# --------------------------------------------------------------------------- #
class OpenRouterProvider(LLMProvider):
    """OpenRouter: acceso a modelos abiertos y comerciales con una sola clave."""

    nombre = "openrouter"

    def __init__(
        self,
        modelo: str | None = None,
        api_key: str | None = None,
        temperatura: float = 0.0,
        max_tokens: int = 1200,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 180,
    ) -> None:
        from mvp_sig.settings import OPENROUTER_MODEL

        super().__init__(modelo or OPENROUTER_MODEL, temperatura, max_tokens)
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _chat(self, sistema: str, usuario: str, json_modo: bool) -> LLMResponse:
        import requests

        payload = {
            "model": self.modelo,
            "messages": [
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            "temperature": self.temperatura,
            "max_tokens": self.max_tokens,
        }
        if json_modo:
            payload["response_format"] = {"type": "json_object"}
        inicio = time.perf_counter()
        r = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "MVP SIG ISO",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        datos = r.json()
        latencia = time.perf_counter() - inicio
        texto = datos["choices"][0]["message"]["content"]
        uso = datos.get("usage") or {}
        return LLMResponse(
            texto=texto,
            modelo=self.modelo,
            proveedor=self.nombre,
            latencia_s=latencia,
            tokens_entrada=int(uso.get("prompt_tokens") or 0),
            tokens_salida=int(uso.get("completion_tokens") or 0),
            costo_usd=float(uso.get("cost") or 0.0),
            crudo=datos,
        )

    def disponible(self) -> bool:
        return bool(self.api_key)


# --------------------------------------------------------------------------- #
# Fábrica
# --------------------------------------------------------------------------- #
PROVEEDORES = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
}


def crear_proveedor(nombre: str | None = None, modelo: str | None = None, **kwargs) -> LLMProvider:
    """Instancia el proveedor pedido (por defecto, el de ``LLM_PROVIDER``)."""
    from mvp_sig.settings import LLM_PROVIDER

    nombre = (nombre or LLM_PROVIDER).lower().strip()
    clase = PROVEEDORES.get(nombre)
    if clase is None:
        raise ValueError(
            f"Proveedor desconocido: {nombre}. Opciones: {', '.join(PROVEEDORES)}"
        )
    if modelo:
        kwargs["modelo"] = modelo
    return clase(**kwargs)


def proveedores_disponibles() -> list[dict]:
    """Inventario de proveedores y si están operativos ahora mismo."""
    salida = []
    for nombre, clase in PROVEEDORES.items():
        try:
            prov = clase()
            salida.append(
                {
                    "proveedor": nombre,
                    "modelo": prov.modelo,
                    "disponible": prov.disponible(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            salida.append({"proveedor": nombre, "modelo": "-", "disponible": False, "error": str(exc)})
    return salida
