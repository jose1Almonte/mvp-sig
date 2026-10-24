"""Utilidades de texto: normalización, limpieza de ruido normativo y similitud."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #
_WS = re.compile(r"[ \t\u00a0\u2007\u202f]+")
_NL3 = re.compile(r"\n{3,}")
_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]")


def strip_accents(text: str) -> str:
    """Quita diacríticos manteniendo la ñ como 'n'."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(text: str) -> str:
    """Minusúsculas, sin acentos, espacios colapsados. Para comparar textos."""
    text = strip_accents(text.lower())
    text = _WS.sub(" ", text)
    return text.strip()


def colapsar_espacios(text: str) -> str:
    text = _CONTROL.sub(" ", text)
    text = _WS.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text


def limpiar_pies_de_pagina(text: str) -> str:
    """Elimina números de página sueltos y guiones típicos de PDF."""
    text = re.sub(r"(?m)^\s*[-–—]?\s*\d{1,3}\s*[-–—]?\s*$", "", text)
    text = re.sub(r"\(\)\s*\d+\s*//", "", text)
    text = re.sub(r"\(\)\s*//\s*\d+", "", text)
    return text


# --------------------------------------------------------------------------- #
# Ruido característico de las ISO (heredado de la fase 3.1 del proyecto)
# --------------------------------------------------------------------------- #
RUIDO_ISO: list[str] = [
    # Número de página al pie de las páginas pares (p. ej. "- 13 -").
    r"(?m)^\s*[-–—]\s*\d{1,3}\s*[-–—]\s*$",
    r"(?m)^\s*[-–—]\s*\d{1,3}\s*[-–—]\s+",
    r"Traducci[oó]n oficial",
    r"Official translation",
    r"Traduction officielle",
    r"Requirements with guidance for use",
    r"Publicado por la Secretar[ií]a Central.*",
    r"Ginebra, Suiza",
    r"N[uú]mero de referencia",
    r"[©®]\s*ISO\s*\d{4}.{0,40}Todos los derechos reservados",
    r"Este documento (?:ha sido adquirido por|forma parte de la biblioteca de) UNIVERSIDAD.*",
    r"Para uso en red interna se requiere de autorizaci[oó]n previa de AENOR\.",
    r"ISO\s*(?:9001|14001|45001):201\d\s*-\s*\d+\s*-",
    r"\(\)\s*\d+\s*//",
    r"\(\)\s*//\s*\d+",
    r"UNE-EN ISO (?:9001|14001|45001):\d{4}",
    r"(?:AENOR|UNE)\s+(?:9001|14001|45001)[^\n]{0,30}",
]

_COMPILED_RUIDO = [re.compile(p, re.IGNORECASE) for p in RUIDO_ISO]


def limpiar_ruido_iso(text: str) -> str:
    """Quita marcas de agua, cabeceras editoriales y pies de página de las ISO."""
    for patron in _COMPILED_RUIDO:
        text = patron.sub(" ", text)
    return colapsar_espacios(text)


# --------------------------------------------------------------------------- #
# Detección de encabezados/pies repetidos (frecuencia entre páginas)
# --------------------------------------------------------------------------- #
def lineas_candidatas(texto: str) -> list[str]:
    return [ln.strip() for ln in texto.splitlines() if 3 <= len(ln.strip()) <= 160]


def detectar_lineas_repetidas(
    paginas: list[str], ratio_minimo: float = 0.35, min_paginas: int = 3
) -> set[str]:
    """Devuelve las líneas que se repiten en muchas páginas (encabezado/pie)."""
    if len(paginas) < min_paginas:
        return set()
    conteo: dict[str, int] = {}
    for pagina in paginas:
        for linea in set(lineas_candidatas(pagina)):
            conteo[linea] = conteo.get(linea, 0) + 1
    umbral = max(min_paginas, int(len(paginas) * ratio_minimo))
    return {ln for ln, n in conteo.items() if n >= umbral}


def eliminar_lineas_repetidas(texto: str, repetidas: set[str]) -> str:
    if not repetidas:
        return texto
    salida = [ln for ln in texto.splitlines() if ln.strip() not in repetidas]
    return colapsar_espacios("\n".join(salida))


# --------------------------------------------------------------------------- #
# Similaridad
# --------------------------------------------------------------------------- #
def similaridad(a: str, b: str) -> float:
    """Similitud de secuencia 0..1 (usada para verificar citas)."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def contiene_frase(texto: str, frase: str, umbral: float = 0.82) -> bool:
    """True si la frase aparece (literal o con alta similitud) dentro del texto.

    Se usa para verificar que la cita generada por el LLM existe realmente
    en el fragmento recuperado (control de *grounding*).
    """
    nt, nf = normalizar(texto), normalizar(frase)
    if not nf:
        return False
    if nf in nt:
        return True
    # Coincidencia por ventanas: la cita puede estar truncada.
    if len(nf) < 40:
        return False
    paso = max(20, len(nf) // 4)
    mejor = 0.0
    for ini in range(0, max(1, len(nt) - len(nf) + 1), paso):
        ventana = nt[ini : ini + len(nf) + 40]
        ratio = SequenceMatcher(None, nf, ventana[: len(nf)]).ratio()
        mejor = max(mejor, ratio)
        if mejor >= umbral:
            return True
    return mejor >= umbral


# --------------------------------------------------------------------------- #
# Modalidad normativa (ISO/IEC Directives, Parte 2)
# --------------------------------------------------------------------------- #
# "debe" (shall) = requisito exigible.  "debería" (should) = recomendación:
# no genera una no conformidad.  La distinción es la base de un programa de
# auditoría y por eso el corpus de requisitos la aplica explícitamente.
_RE_MODAL_EXIGIBLE = re.compile(
    r"\b(debe|deben|deberá|deberán|deberemos|shall|shall\s+be)\b", re.IGNORECASE
)
_RE_MODAL_RECOMENDACION = re.compile(
    r"\b(debería|deberían|deberiamos|should|se recomienda|recomienda)\b",
    re.IGNORECASE,
)
# Bloques informativos que las ISO intercalan en el texto normativo.
_RE_BLOQUE_INFORMATIVO = re.compile(
    r"^(?:NOTA(?:\s*\d+)?|Ejemplos?|EJEMPLO)\b[:.\s-]*", re.IGNORECASE
)
# Continuación de una enumeración ("a)", "b)", "-", "–", "•").
_RE_CONTINUACION = re.compile(
    r"^\s*(?:[-–—•]|\((?:[a-z]|[ivx]+)\)|[a-z]\)|[ivx]+\))\s+", re.IGNORECASE
)


def es_exigible(texto: str) -> bool:
    """True si el texto enuncia una exigencia (modalidad 'debe'/'shall')."""
    return bool(_RE_MODAL_EXIGIBLE.search(texto))


def es_recomendacion(texto: str) -> bool:
    """True si el texto sólo recomienda (modalidad 'debería'/'should')."""
    if es_exigible(texto):
        return False
    return bool(_RE_MODAL_RECOMENDACION.search(texto))


def es_bloque_informativo(texto: str) -> bool:
    """True si el fragmento es una NOTA o un Ejemplo (contenido informativo)."""
    return bool(_RE_BLOQUE_INFORMATIVO.match(texto.strip()))


def es_continuacion(texto: str) -> bool:
    """True si el fragmento continúa una enumeración previa."""
    return bool(_RE_CONTINUACION.match(texto or ""))


# --------------------------------------------------------------------------- #
# Segmentación de oraciones (para requirements y KPI)
# --------------------------------------------------------------------------- #
_ABREVIATURAS = {
    "sr", "sra", "srta", "etc", "ej", "p", "pág", "pag", "fig", "nro", "art",
    "num", "ejem", "ver", "cap", "iso", "ong", "sig", "sst", "pve", "ppe",
}


def dividir_oraciones(texto: str) -> list[str]:
    """Divide texto en oraciones respetando abreviaturas y numeración decimal."""
    texto = colapsar_espacios(texto).replace("\n", " ")
    partes = re.split(r"(?<=[.;:])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"'(])", texto)
    salida: list[str] = []
    for parte in partes:
        parte = parte.strip()
        if not parte:
            continue
        if salida:
            prev = salida[-1]
            ultima_palabra = re.split(r"[\s(]", prev)[-1].rstrip(".,;").lower()
            if ultima_palabra in _ABREVIATURAS or re.fullmatch(r"\d+(?:\.\d+)*", ultima_palabra):
                salida[-1] = f"{prev} {parte}"
                continue
        salida.append(parte)
    return salida


def truncar(texto: str, limite: int = 300, sufijo: str = "...") -> str:
    texto = texto.strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return f"{corte}{sufijo}"
