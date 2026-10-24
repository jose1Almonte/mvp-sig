"""Modelos Pydantic de la API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Veredicto = Literal["CUMPLE", "CUMPLE_PARCIAL", "NO_CUMPLE", "NO_APLICA"]


class DiagnosticoRequest(BaseModel):
    """Parámetros de una corrida de diagnóstico."""

    normas: list[str] | None = Field(
        default=None, description="ISO9001 | ISO14001 | ISO45001 (vacío = todas)"
    )
    ambitos: list[str] | None = Field(
        default=None, description="calidad | ambiente | seguridad (vacío = todos)"
    )
    clausulas: list[str] | None = Field(default=None, description="Filtro por cláusula")
    limite: int | None = Field(default=None, ge=1, le=500, description="Máximo de requisitos")
    top_k: int | None = Field(default=None, ge=1, le=20)
    organizacion: str = Field(default="Organización evaluada", max_length=200)
    contexto_extra: str = Field(default="", max_length=4000)
    con_resumen: bool = True
    proveedor: str | None = None
    modelo: str | None = None


class IngestaRequest(BaseModel):
    """Parámetros de la ingesta de evidencias."""

    raiz: str | None = Field(default=None, description="Carpeta del corpus de evidencias")
    extensiones: list[str] = Field(default_factory=lambda: [".pdf", ".docx", ".xlsx", ".xls"])
    limite: int | None = Field(default=None, ge=1, le=2000)
    reindexar_requisitos: bool = True


class EvidenciaRequest(BaseModel):
    """Registro manual de evidencia a partir de un texto pegado."""

    texto: str = Field(..., min_length=1, description="Texto de la evidencia")
    nombre: str = Field(default="", max_length=200, description="Nombre con el que se registra")
    ambitos: list[str] | None = Field(
        default=None, description="calidad | ambiente | seguridad | integral"
    )
    ambito_principal: str | None = None
    tipo_documento: str | None = Field(default=None, max_length=60)
    organizacion: str | None = Field(default=None, max_length=200)
    codigo: str | None = Field(default=None, max_length=120)


class MetadatosRequest(BaseModel):
    """Corrección de la clasificación de un documento del corpus.

    Los campos que se omiten conservan su valor actual: la corrección es
    quirúrgica y no obliga a reescribir la ficha completa.
    """

    ambitos: list[str] | None = Field(
        default=None, description="calidad | ambiente | seguridad | integral"
    )
    ambito_principal: str | None = None
    tipo_documento: str | None = Field(default=None, max_length=60)
    organizacion: str | None = Field(default=None, max_length=200)
    codigo: str | None = Field(default=None, max_length=120)


class ExclusionRequest(BaseModel):
    """Retirada de un documento del diagnóstico."""

    motivo: str = Field(default="", max_length=300, description="Motivo de la exclusión")


class BenchmarkRequest(BaseModel):
    """Parámetros del benchmarking de modelos."""

    modelos: list[dict] | None = Field(
        default=None,
        description='Lista de {"proveedor": "...", "modelo": "..."}. Vacío = configuración por defecto.',
    )
    limite_requisitos: int = Field(default=6, ge=1, le=100)
    normas: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class RequisitoOut(BaseModel):
    id: str
    norma: str
    ambito: str
    clausula: str
    texto: str
    pagina: int | None = None


class EvidenciaOut(BaseModel):
    ref: str
    fragmento_id: str = ""
    documento: str
    pagina: int | None = None
    seccion: str = ""
    cita: str = ""
    verificada: bool = False
    puntaje: float = 0.0
    motivo_fallo: str = ""


class ResultadoOut(BaseModel):
    requisito_id: str
    norma: str
    clausula: str
    ambito: str
    requisito_texto: str
    veredicto: Veredicto
    confianza: float
    confianza_evidence: float = 0.0
    justificacion: str
    evidencias: list[EvidenciaOut] = Field(default_factory=list)
    hallazgo: str = ""
    severidad: str = ""
    recomendacion: str = ""
    fragmentos_recuperados: list[str] = Field(default_factory=list)
    traza_verificada: bool = False
    mejor_puntaje: float = 0.0
    latencia_s: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    modelo: str = ""
    proveedor: str = ""
    error: str | None = None


class DiagnosticoResponse(BaseModel):
    generado: str
    proveedor: str
    modelo: str
    organizacion: str
    resumen_ejecutivo: str = ""
    metricas: dict = Field(default_factory=dict)
    advertencias: list[str] = Field(default_factory=list)
    resultados: list[ResultadoOut] = Field(default_factory=list)


class EstadoResponse(BaseModel):
    base_vectorial: dict
    llm: dict
    catalogo: int
    pasos: list[str] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
