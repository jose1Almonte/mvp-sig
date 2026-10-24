"""Embeddings: proveedor local (Ollama) con degradación controlada."""
from __future__ import annotations

from typing import Sequence

from mvp_sig.settings import MODELS
from mvp_sig.utils.http import crear_sesion, normalizar_url, pedir


class EmbeddingProvider:
    """Interfaz de embeddings."""

    nombre: str = "base"

    def embed_documents(self, textos: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, texto: str) -> list[float]:
        raise NotImplementedError

    def disponible(self) -> bool:
        raise NotImplementedError


class OllamaEmbeddings(EmbeddingProvider):
    """Embeddings servidos por Ollama (mxbai-embed-large por defecto).

    Se usa la API HTTP nativa de Ollama en lugar del SDK de langchain para
    controlar el lote y evitar dependencias extra en el MVP.
    """

    nombre = "ollama"

    def __init__(
        self,
        modelo: str | None = None,
        url: str | None = None,
        dim: int | None = None,
        batch_size: int = 16,
        timeout: int = 600,
        timeout_conexion: int = 10,
        reintentos: int = 3,
    ) -> None:
        self.modelo = modelo or MODELS.embedding_model
        self.url = (url or MODELS.ollama_url).rstrip("/")
        self.dim = dim or MODELS.embedding_dim
        self.batch_size = batch_size
        self.timeout = timeout
        self.timeout_conexion = timeout_conexion
        self.reintentos = reintentos
        # Sesión persistente: la ingesta emite cientos de lotes de embeddings
        # y una conexión por petición sería innecesariamente costosa (y
        # expondría al penalizable handshake IPv6 described in utils.http).
        self._sesion = crear_sesion(
            self.url,
            timeout_conexion=timeout_conexion,
            timeout_lectura=timeout,
            reintentos=reintentos,
        )

    # -- interno ---------------------------------------------------------- #
    def _embed(self, textos: Sequence[str]) -> list[list[float]]:
        respuesta = pedir(
            self._sesion,
            "POST",
            "/api/embed",
            json={"model": self.modelo, "input": list(textos)},
        )
        datos = respuesta.json()
        vectores = datos.get("embeddings")
        if not vectores:
            raise RuntimeError(f"Ollama no devolvió embeddings: {datos}")
        return vectores

    # -- interfaz --------------------------------------------------------- #
    def embed_documents(self, textos: Sequence[str]) -> list[list[float]]:
        salida: list[list[float]] = []
        lote = list(textos)
        for i in range(0, len(lote), self.batch_size):
            trozo = lote[i : i + self.batch_size]
            salida.extend(self._embed(trozo))
        return salida

    def embed_query(self, texto: str) -> list[float]:
        return self._embed([texto])[0]

    def disponible(self) -> bool:
        try:
            r = pedir(self._sesion, "GET", "/api/tags", timeout=(5, 15))
            if r.status_code != 200:
                return False
            modelos = [m.get("name", "") for m in r.json().get("models", [])]
            return any(m.split(":")[0] == self.modelo.split(":")[0] for m in modelos)
        except Exception:  # noqa: BLE001
            return False


class HashEmbeddings(EmbeddingProvider):
    """Embeddings deterministas de respaldo (sin red ni GPU).

    Usa hashing de n-gramas + proyección dispersa. No tiene sentido semántico,
    pero permite que el pipeline se ejecute y se mida extremo a extremo cuando
    Ollama no está disponible. Se marca explícitamente en el reporte.
    """

    nombre = "hash-fallback"
    dim = 256

    def _vector(self, texto: str) -> list[float]:
        import hashlib
        import math

        vec = [0.0] * self.dim
        palabras = texto.lower().split()
        for i, palabra in enumerate(palabras):
            for ngram in (palabra, f"{palabra} {palabras[i + 1]}" if i + 1 < len(palabras) else palabra):
                h = int(hashlib.md5(ngram.encode("utf-8")).hexdigest(), 16)
                idx = h % self.dim
                signo = 1.0 if (h >> 8) % 2 == 0 else -1.0
                vec[idx] += signo
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, textos: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in textos]

    def embed_query(self, texto: str) -> list[float]:
        return self._vector(texto)

    def disponible(self) -> bool:
        return True


def obtener_embeddings(permitir_fallback: bool = True) -> EmbeddingProvider:
    """Devuelve el proveedor de embeddings activo, con fallback opcional."""
    prov = OllamaEmbeddings()
    if prov.disponible():
        return prov
    if permitir_fallback:
        print(
            "  [aviso] Ollama no disponible para embeddings; "
            "se usa el proveedor de respaldo determinista (hash).",
            flush=True,
        )
        return HashEmbeddings()
    raise RuntimeError(
        "Ollama no está disponible. Levanta `ollama serve` y descarga el modelo "
        f"de embeddings: ollama pull {MODELS.embedding_model}"
    )
