"""Árbol canónico de cláusulas y conformidad de la atribución.

La coherencia interna (comprobaciones A-E de `coherencia.py`) demuestra que el
pre-procesamiento es *consistente consigo mismo*.  Este módulo añade la
comprobación **F**: que la atribución coincida con la **estructura oficial**
de cada norma.

La referencia no es un árbol memorizado, sino el índice de las versiones
oficiales de las normas, extraído automáticamente a
`data/seed/arbol_oficial.json` por `scripts/generar_arbol_oficial.py`.

Para cada cláusula del árbol oficial se comprueba dos cosas:

1. que el detector localizó una encabezado con ese número de cláusula;
2. que el título oficial de la cláusula aparece en el segmento que el
   detector le asignó.

Ambas cosas son necesarias: el número sin el título puede ser una coincidencia
de digits; el título sin el número, un parecido léxico.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from mvp_sig.knowledge.requirements import escanear_encabezados
from mvp_sig.settings import NORMAS, PATHS

# Archivo con el árbol extraído de los PDF oficiales.
RUTA_ARBOL = PATHS.data / "seed" / "arbol_oficial.json"

_ESPACIOS = re.compile(r"\s+")
_NO_SIGNIFICATIVOS = {"de", "del", "la", "el", "los", "las", "y", "e", "o", "u",
                       "en", "un", "una", "para", "por", "con", "su", "sus", "al",
                       "a", "the", "of", "and", "or"}

# Palabras que triman el titulo de una clausula: la mayuscula que las sigue
# marca el comienzo del cuerpo del requisito.
_RE_FIN_TITULO = re.compile(
    r"^(?P<tit>[^.]{3,110}?)\.(?:\s|$)", re.DOTALL
)


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    ).lower()


def _tokens_significativos(texto: str) -> set[str]:
    return set(_tokens_significativos_ordenados(texto))


def _tokens_significativos_ordenados(texto: str) -> list[str]:
    """Tokens significativos (sin palabras vacías) en su orden de aparición."""
    limpio = _sin_acentos(texto)
    return [
        t
        for t in re.split(r"[^a-z0-9]+", limpio)
        if len(t) > 2 and t not in _NO_SIGNIFICATIVOS
    ]


def cargar_arbol(norma: str) -> dict[str, str]:
    """Devuelve {clausula: titulo oficial} para la norma indicada.

    Devuelve un diccionario vacío si el archivo no está disponible: la
    comprobación se omite en lugar de fallar, para que el MVP pueda ejecutarse
    sin los PDF oficiales.
    """
    if not RUTA_ARBOL.exists():
        return {}
    try:
        datos = json.loads(RUTA_ARBOL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entrada = datos.get(norma) or {}
    clausulas = entrada.get("clausulas") or {}
    return {str(k): str(v) for k, v in clausulas.items()}


def arboles_disponibles() -> dict[str, int]:
    """Número de cláusulas del árbol oficial disponible por norma."""
    if not RUTA_ARBOL.exists():
        return {}
    datos = json.loads(RUTA_ARBOL.read_text(encoding="utf-8"))
    return {
        k: len((v or {}).get("clausulas") or {})
        for k, v in datos.items()
    }


def titulo_de_encabezado(texto: str, posicion: int, fin: int, largo: int = 110) -> str:
    """Devuelve la *región de título* que sigue al número de cláusula.

    En el texto de las normas el título no está separado del cuerpo por
    puntuación ("7.5 Información documentada La organización debe..."), de modo
    que no puede delimitarse de forma exacta.  Se devuelve el comienzo del
    enunciado y la comparación con el título oficial se hace por ventanas de
    tokens (ver ``_coincide_titulo``), no por igualdad literal.
    """
    bruto = texto[fin : fin + largo]
    corte = bruto.find("\n")
    if corte >= 0:
        bruto = bruto[:corte]
    return _ESPACIOS.sub(" ", bruto).strip()


def _coincide_titulo(titulo_oficial: str, region_detectada: str) -> bool:
    """True si la región detectada comienza por el título oficial.

    La comparación es **posicional**: el título oficial debe aparecer al
    principio de la región, con una ventana de dos tokens de tolerancia
    (por los conectores: "Objetivo" / "Objeto", "Información" / "Informacion").
    Un título presente más adelante en el enunciado no cuenta: lo que se
    valida es que la cláusula *empiece* por su título oficial.

    Se exige que al menos el 80 % de los tokens significativos del título
    oficial aparezcan en esa ventana, lo queTolera las variantes morfológicas
    sin abandonar el requisito de identidad léxica.
    """
    esperados = _tokens_significativos(titulo_oficial)
    if not esperados:
        return False
    ventana = _tokens_significativos_ordenados(region_detectada)[: len(esperados) + 2]
    if not ventana:
        return False
    comunes = 0
    for e in esperados:
        if any(o == e or o.startswith(e) or e.startswith(o) for o in ventana):
            comunes += 1
    return comunes / len(esperados) >= 0.8


def medir_conformidad_arbol(texto: str, norma: str) -> dict:
    """Compara la atribución de cláusulas con el árbol oficial de la norma.

    Devuelve el detalle por cláusula y los porcentajes de cobertura y de
    coincidencia de título.
    """
    arbol = cargar_arbol(norma)
    if not arbol:
        return {
            "disponible": False,
            "norma": norma,
            "motivo": f"No se encontró el árbol oficial en {RUTA_ARBOL}",
        }

    encabezados = escanear_encabezados(texto)
    detectados: dict[str, str] = {}
    for enc in encabezados:
        if enc.tipo != "clausula":
            continue
        # La primera aparicion de cada clausula es la que manda.
        detectados.setdefault(enc.clausula, titulo_de_encabezado(texto, enc.posicion, enc.fin))

    ausentes: list[str] = []
    titulo_distinto: list[dict] = []
    coincidentes = 0
    evaluadas = 0

    for clausula, oficial in sorted(arbol.items(), key=lambda kv: _ord(kv[0])):
        # La Introduccion (clausula 0) no lleva numero en el cuerpo: se
        # comprueba por la presencia del texto, no por un encabezado.
        if clausula == "0":
            continue
        evaluadas += 1
        detectada = detectados.get(clausula)
        if detectada is None:
            ausentes.append(clausula)
            continue
        if _coincide_titulo(oficial, detectada):
            coincidentes += 1
        else:
            titulo_distinto.append(
                {"clausula": clausula, "oficial": oficial, "detectado": detectada}
            )

    oficiales = set(arbol) - {"0"}
    adicionales = sorted(set(detectados) - oficiales, key=_ord)

    return {
        "disponible": True,
        "norma": norma,
        "oficiales": len(oficiales),
        "evaluadas": evaluadas,
        "coincidentes": coincidentes,
        "ausentes": ausentes,
        "titulo_distinto": titulo_distinto,
        "adicionales": adicionales,
        "porcentaje_cobertura": 100.0 * (evaluadas - len(ausentes)) / evaluadas if evaluadas else 0.0,
        "porcentaje_titulo": 100.0 * coincidentes / evaluadas if evaluadas else 0.0,
    }


def _ord(clausula: str) -> tuple:
    partes = []
    for p in clausula.split("."):
        partes.append(int(p) if p.isdigit() else 0)
    return tuple(partes)


def resumen_arbol() -> str:
    """Resumen legible del árbol oficial disponible."""
    if not RUTA_ARBOL.exists():
        return f"No hay árbol oficial en {RUTA_ARBOL}"
    lineas = []
    for norma, n in sorted(arboles_disponibles().items()):
        nombre = NORMAS[norma].nombre_archivo if norma in NORMAS else norma
        lineas.append(f"  {norma:<10} {n:>3} cláusulas · {nombre}")
    return "\n".join(lineas)


def ruta_arbol() -> Path:
    return RUTA_ARBOL
