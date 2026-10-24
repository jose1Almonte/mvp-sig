"""Limpieza y segmentación de la documentación (normas + evidencias).

Cierra la fase 3.1 del anteproyecto: de un PDF/DOCX/XLSX crudo a bloques de
texto aptos para el modelo de lenguaje, conservando la referencia de origen.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from mvp_sig.ingestion.extractors import Bloque, DocumentoExtraido
from mvp_sig.settings import INGEST
from mvp_sig.utils.text import (
    colapsar_espacios,
    contiene_frase,
    detectar_lineas_repetidas,
    eliminar_lineas_repetidas,
    limpiar_pies_de_pagina,
    limpiar_ruido_iso,
    normalizar,
    truncar,
)


@dataclass
class Chunk:
    """Fragmento indexable con metadatos de trazabilidad."""

    id: str
    texto: str
    documento: str
    ruta: str
    tipo: str
    ambitos: list[str]
    ambito_principal: str
    pagina: int | None = None
    seccion: str | None = None
    tabla: str | None = None
    posicion: int = 0
    metadatos: dict = field(default_factory=dict)

    def to_metadata(self) -> dict:
        meta = {
            "documento": self.documento,
            "ruta": self.ruta,
            "tipo": self.tipo,
            "ambito": self.ambito_principal,
            "ambitos": "|".join(self.ambitos),
            "posicion": self.posicion,
        }
        if self.pagina is not None:
            meta["pagina"] = self.pagina
        if self.seccion:
            meta["seccion"] = truncar(self.seccion, 200)
        if self.tabla:
            meta["tabla"] = truncar(self.tabla, 200)
        meta.update(self.metadatos)
        return meta


# --------------------------------------------------------------------------- #
# Limpieza
# --------------------------------------------------------------------------- #
def limpiar_bloque(texto: str, es_norma: bool = False) -> str:
    texto = colapsar_espacios(texto)
    texto = limpiar_pies_de_pagina(texto)
    if es_norma:
        texto = limpiar_ruido_iso(texto)
    return texto.strip()


def limpiar_documento(
    doc: DocumentoExtraido, es_norma: bool = False
) -> list[Bloque]:
    """Limpia un documento completo y descarta encabezados/pies repetidos."""
    if doc.tipo == "pdf":
        repetidas = detectar_lineas_repetidas(
            [b.texto for b in doc.bloques], INGEST.header_footer_ratio
        )
    else:
        repetidas = set()

    salida: list[Bloque] = []
    for bloque in doc.bloques:
        texto = limpiar_bloque(bloque.texto, es_norma)
        if repetidas:
            texto = eliminar_lineas_repetidas(texto, repetidas)
            texto = colapsar_espacios(texto)
        if len(texto) < 20:
            continue
        salida.append(
            Bloque(
                texto=texto,
                pagina=bloque.pagina,
                seccion=bloque.seccion,
                tabla=bloque.tabla,
                extras=dict(bloque.extras),
            )
        )
    return salida


# --------------------------------------------------------------------------- #
# Segmentación
# --------------------------------------------------------------------------- #
_SALTOS = ["\n\n", "\n", ". ", "; ", ", ", " "]


def sufijo_ruta(ruta: str) -> str:
    """Huella corta de la ruta del documento.

    El corpus CIL ONG contiene nombres de archivo repetidos en carpetas
    distintas (17 duplicados). Sin esta huella, dos documentos homónimos
    generarían identificadores de fragmento idénticos.
    """
    return hashlib.sha1(str(ruta).encode("utf-8")).hexdigest()[:6]


def segmentar_bloque(
    texto: str,
    bloque: Bloque,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    documento: str = "",
    ruta: str = "",
    tipo: str = "",
    ambitos: list[str] | None = None,
    ambito_principal: str = "integral",
    offset: int = 0,
) -> list[Chunk]:
    """Divide un bloque en chunks con solapamiento, conservando la referencia.

    `offset` es el número de chunks ya generados para el documento: garantiza
    que el identificador sea único dentro del documento (varios bloques pueden
    compartir la misma clave de sección o página).
    """
    chunk_size = chunk_size or INGEST.chunk_size
    chunk_overlap = chunk_overlap or INGEST.chunk_overlap
    ambitos = ambitos or []

    texto = texto.strip()
    if len(texto) <= chunk_size:
        unidades = [texto]
    else:
        unidades: list[str] = []
        actual = ""
        for parrafo in texto.split("\n"):
            parrafo = parrafo.strip()
            if not parrafo:
                continue
            if len(actual) + len(parrafo) + 1 <= chunk_size:
                actual = f"{actual}\n{parrafo}" if actual else parrafo
                continue
            if actual:
                unidades.append(actual)
            # Un párrafo mayor que el chunk se parte por oraciones.
            if len(parrafo) > chunk_size:
                from mvp_sig.utils.text import dividir_oraciones

                buffer = ""
                for oracion in dividir_oraciones(parrafo):
                    if len(buffer) + len(oracion) + 1 > chunk_size and buffer:
                        unidades.append(buffer)
                        # Solapamiento por la última oración.
                        buffer = buffer[-chunk_overlap:] if chunk_overlap else ""
                    buffer = f"{buffer} {oracion}".strip()
                if buffer:
                    unidades.append(buffer)
            else:
                actual = parrafo
        if actual:
            unidades.append(actual)

    chunks: list[Chunk] = []
    sufijo = sufijo_ruta(ruta)
    for i, unidad in enumerate(unidades):
        unidad = unidad.strip()
        if len(unidad) < INGEST.min_chunk_chars and chunks:
            # Se fusiona con el chunk anterior para no fragmentar de más.
            chunks[-1].texto = f"{chunks[-1].texto}\n{unidad}".strip()
            continue
        if len(unidad) < 20:
            continue
        n = offset + len(chunks)
        cid = f"{documento}#{sufijo}#{bloque.clave()}#{n}"
        chunks.append(
            Chunk(
                id=cid,
                texto=unidad,
                documento=documento,
                ruta=ruta,
                tipo=tipo,
                ambitos=ambitos,
                ambito_principal=ambito_principal,
                pagina=bloque.pagina,
                seccion=bloque.seccion,
                tabla=bloque.tabla,
                posicion=n,
            )
        )
    return chunks


# --------------------------------------------------------------------------- #
# Verificación de citas (grounding)
# --------------------------------------------------------------------------- #
def verificar_cita(fragmentos: dict[str, str], cita: str, umbral: float = 0.80) -> bool:
    """True si la cita del LLM se puede localizar dentro del fragmento citado."""
    if not cita:
        return False
    for texto in fragmentos.values():
        if contiene_frase(texto, cita, umbral):
            return True
    return False


def pre_limpiar_cita(cita: str) -> str:
    """Quita comillas, viñetas y prefijos que los modelos añaden a las citas."""
    cita = cita.strip()
    # Prefijos de referencia tipo "[E1]", "[E1] " o "1." / "1)" al inicio.
    cita = re.sub(r"^\[[^\]]{0,20}\]\s*", "", cita)
    cita = re.sub(r"^\d{1,2}[.)]\s+", "", cita)
    cita = re.sub(r"^[\"'\u201c\u201d`\[\(\-\*\s]+", "", cita)
    cita = re.sub(r"[\"'\u201c\u201d`\]\)\*\s]+$", "", cita)
    return cita.strip()


def normalizar_para_grounding(texto: str) -> str:
    return normalizar(texto)
