"""Configuración compartida de la suite de pruebas.

Las pruebas corren **sin Ollama ni LLM**: usan embeddings deterministas de
respaldo y un proveedor de lenguaje simulado, de modo que el suite sea
reproducible, rápido y no dependa de la red.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from mvp_sig.knowledge.embeddings import HashEmbeddings  # noqa: E402
from mvp_sig.knowledge.vectorstore import VectorStore  # noqa: E402
from mvp_sig.llm.provider import LLMProvider, LLMResponse  # noqa: E402


# --------------------------------------------------------------------------- #
# Proveedor de lenguaje simulado
# --------------------------------------------------------------------------- #
class LLMFalso(LLMProvider):
    """Devuelve respuestas JSON predefinidas, en cola."""

    nombre = "falso"

    def __init__(self, respuestas: list[dict] | dict | None = None) -> None:
        super().__init__(modelo="llama-falso", temperatura=0.0, max_tokens=1200)
        if isinstance(respuestas, dict):
            respuestas = [respuestas]
        self.respuestas = list(respuestas or [{"veredicto": "NO_CUMPLE"}])
        self.llamadas: list[dict] = []

    def _chat(self, sistema: str, usuario: str, json_modo: bool) -> LLMResponse:
        self.llamadas.append({"sistema": sistema, "usuario": usuario})
        if not self.respuestas:
            return LLMResponse(texto="", modelo=self.modelo, proveedor=self.nombre)
        if len(self.respuestas) == 1:
            datos = self.respuestas[0]
        else:
            datos = self.respuestas.pop(0)
        return LLMResponse(
            texto=json.dumps(datos, ensure_ascii=False),
            modelo=self.modelo,
            proveedor=self.nombre,
            latencia_s=0.01,
            tokens_entrada=len(usuario.split()),
            tokens_salida=len(json.dumps(datos).split()),
        )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def embeddings() -> HashEmbeddings:
    return HashEmbeddings()


@pytest.fixture
def store(tmp_path, embeddings) -> VectorStore:
    """Base vectorial temporal (ChromaDB en disco, con embeddings hash)."""
    return VectorStore(ruta=str(tmp_path / "chroma"), embeddings=embeddings)


@pytest.fixture
def llm() -> LLMFalso:
    return LLMFalso()


# --------------------------------------------------------------------------- #
# Documentos de prueba
# --------------------------------------------------------------------------- #
DOCUMENTO_EVIDENCIA = (
    "Procedimiento de control de documentos y registros. "
    "La organización debe establecer un listado maestro de documentos, "
    "revisarlos periódicamente y controlarlos. "
    "El responsable del control de documentos es el Analista SIG."
)

OTRO_DOCUMENTO = (
    "Procedimiento de gestión de riesgos y oportunidades. "
    "La organización debe identificar los riesgos y oportunidades del sistema "
    "integrado de gestión y planificar acciones para tratarlos."
)


@pytest.fixture
def store_con_evidencias(store) -> VectorStore:
    """Base vectorial con dos documentos de evidencia y sus fragmentos."""
    textos = [DOCUMENTO_EVIDENCIA, OTRO_DOCUMENTO]
    ids = [f"doc{i}#hash#bloque#0" for i in range(len(textos))]
    metas = [
        {
            "documento": "Control de Documentos_CIL ONG.docx",
            "ruta": "/corpus/Control de Documentos_CIL ONG.docx",
            "tipo": "docx",
            "ambito": "calidad",
            "ambitos": "calidad|integral",
            "posicion": 0,
            "seccion": "4. Objetivo",
        },
        {
            "documento": "Gestion de Riesgos_CIL ONG.docx",
            "ruta": "/corpus/Gestion de Riesgos_CIL ONG.docx",
            "tipo": "docx",
            "ambito": "integral",
            "ambitos": "integral|calidad|ambiente|seguridad",
            "posicion": 0,
            "seccion": "5. Procedimiento",
        },
    ]
    store.indexar(VectorStore.EVIDENCIAS, ids, textos, metas, recrear=True, verbose=False)
    return store


@pytest.fixture
def requisitos_ejemplo():
    """Dos requisitos normativos sintéticos."""
    from mvp_sig.knowledge.requirements import Requisito

    return [
        Requisito(
            id="ISO9001-7.5",
            norma="ISO9001",
            ambito="calidad",
            clausula="7.5",
            texto=(
                "7.5.1 La organización debe establecer, implementar y mantener "
                "un proceso para la gestión de la información documentada."
            ),
            pagina=30,
            fuente="UNE-EN ISO 9001 2015 (pág. 30)",
            metadatos={"ambito_transversal": False, "clausula_sig": True},
        ),
        Requisito(
            id="ISO9001-6.1",
            norma="ISO9001",
            ambito="integral",
            clausula="6.1",
            texto=(
                "6.1 La organización debe determinar los riesgos y oportunidades "
                "del sistema integrado de gestión."
            ),
            pagina=22,
            fuente="UNE-EN ISO 9001 2015 (pág. 22)",
            metadatos={"ambito_transversal": True, "clausula_sig": True},
        ),
    ]
