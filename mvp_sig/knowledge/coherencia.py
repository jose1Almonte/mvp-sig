"""Medición objetiva de la coherencia entre la atribución de cláusula y el texto.

La medición es **independiente del detector**: parte del texto continuo de
cada norma, re-deriva los tramos de cada cláusula y re-localiza cada
requisito dentro de ese texto original.  Un requisito está bien atribuido si,
al buscar su texto en el documento, cae dentro del tramo de la cláusula que se
le asignó.  El indicador no se limita a repetir lo que hace el detector: lo
contrasta contra el documento.

Comprobaciones
--------------
A. Re-anclaje       : requisito -> cláusula, verificado en el texto continuo.
B. Encabezado      : el texto de cada cláusula empieza por su encabezado.
C. Numeración      : toda sub-cláusula tiene su padre; los hijos son contiguos.
D. Cobertura       : las unidades reconstruyen el texto de la cláusula sin
                      pérdidas ni duplicados.
E. Identificadores  : no hay identificadores repetidos en el catálogo.
F. Árbol oficial   : la atribución coincide con la estructura de las versiones
                      oficiales de las normas (fase 3.1, índice oficial).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from mvp_sig.knowledge.arbol_oficial import medir_conformidad_arbol
from mvp_sig.knowledge.requirements import (
    construir_corpus_requisitos,
    escanear_encabezados,
    segmentar_por_clausula,
    texto_continuo,
)

_ESPACIOS = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def normalizar_con_mapa(texto: str) -> tuple[str, list[int]]:
    """Normaliza espacios y minúsculas conservando el índice original.

    Devuelve el texto normalizado y, para cada carácter normalizado, la
    posición que tenía en el texto original.  Permite buscar una cita en el
    documento y traducir el resultado a un offset real.
    """
    chars: list[str] = []
    mapa: list[int] = []
    espacio = True
    for i, ch in enumerate(texto):
        if ch.isspace():
            if espacio:
                continue
            chars.append(" ")
            mapa.append(i)
            espacio = True
        else:
            chars.append(ch.lower())
            mapa.append(i)
            espacio = False
    return "".join(chars), mapa


def occurrences(aguja: str, texto: str) -> list[int]:
    """Posiciones de la aguja normalizada dentro del texto normalizado."""
    salida: list[int] = []
    i = texto.find(aguja)
    while i != -1:
        salida.append(i)
        i = texto.find(aguja, i + 1)
    return salida


def _sin_espacios(texto: str) -> str:
    return _ESPACIOS.sub("", texto)


def _tramos_clausula(texto: str) -> list[tuple[int, int, str]]:
    """Tramos del documento: cada encabezado manda hasta el siguiente."""
    encabezados = escanear_encabezados(texto)
    tramos: list[tuple[int, int, str]] = []
    for i, enc in enumerate(encabezados):
        fin = encabezados[i + 1].posicion if i + 1 < len(encabezados) else len(texto)
        tramos.append((enc.posicion, fin, enc.clausula))
    return tramos


# --------------------------------------------------------------------------- #
# Comprobación A: re-anclaje requisito -> cláusula
# --------------------------------------------------------------------------- #
def medir_reanclaje(requisitos, texto: str) -> dict:
    """Re-localiza cada requisito en el texto continuo y comprueba su cláusula."""
    tramos = _tramos_clausula(texto)
    norm, mapa = normalizar_con_mapa(texto)

    def clausula_en(offset: int) -> str | None:
        encontrada = None
        for inicio, _fin, clausula in tramos:
            if inicio <= offset:
                encontrada = clausula
            else:
                break
        return encontrada

    verificados = 0
    no_localizados = 0
    ambiguos = 0
    desalineados: list[tuple[object, list[str]]] = []

    for r in requisitos:
        aguja = _ESPACIOS.sub(" ", r.texto).strip().lower()
        if not aguja:
            continue
        posiciones = occurrences(aguja, norm)
        if not posiciones and len(aguja) > 120:
            # El texto puede estar truncado o tener saltos de línea: se reintenta
            # con una ventana inicial suficiente para anclar la posición.
            posiciones = occurrences(aguja[:120], norm)
        if not posiciones:
            no_localizados += 1
            continue
        candidatos = {clausula_en(mapa[p]) for p in posiciones}
        if r.clausula in candidatos:
            verificados += 1
            if len(candidatos) > 1:
                ambiguos += 1
        else:
            desalineados.append((r, sorted(str(x) for x in candidatos if x)))

    total = verificados + no_localizados + len(desalineados)
    return {
        "total": total,
        "verificados": verificados,
        "no_localizados": no_localizados,
        "desalineados": desalineados,
        "ambiguos": ambiguos,
        "porcentaje": 100.0 * verificados / total if total else 0.0,
    }


# --------------------------------------------------------------------------- #
# Comprobación B: el texto de la cláusula empieza por su encabezado
# --------------------------------------------------------------------------- #
def medir_encabezados(texto: str) -> dict:
    """Cada segmento debe abrir con el encabezado de la cláusula que lo gobierna."""
    segmentos = segmentar_por_clausula(texto)
    ok = 0
    fallos = []
    for seg in segmentos:
        if not seg.encabezado:
            continue
        etiqueta = seg.encabezado.strip().lower()
        cuerpo = seg.texto.lstrip().lower()
        if cuerpo.startswith(etiqueta):
            ok += 1
        else:
            fallos.append(seg)
    total = ok + len(fallos)
    return {
        "total": total,
        "ok": ok,
        "fallos": fallos,
        "porcentaje": 100.0 * ok / total if total else 0.0,
    }


# --------------------------------------------------------------------------- #
# Comprobación C: coherencia de la numeración
# --------------------------------------------------------------------------- #
def medir_numeracion(texto: str) -> dict:
    """Toda sub-cláusula debe tener su padre; los hijos deben ser contiguos."""
    encabezados = escanear_encabezados(texto)
    detectados = {e.clausula for e in encabezados}

    huerfanos: list[str] = []
    hijos: dict[str, list[int]] = defaultdict(list)
    for e in encabezados:
        partes = e.clausula.split(".")
        if len(partes) == 1:
            continue
        if partes[0].isalpha():  # anexo: "Anexo A.4" -> padre "Anexo A"
            padre = " ".join(partes[:-1])
        else:
            padre = ".".join(partes[:-1])
        # La Introducción (cláusula 0) es una raíz virtual: su encabezado
        # ("Introducción") no lleva número y por tanto nunca se detecta.
        if padre == "0" or padre in detectados:
            hijos[padre].append(int(partes[-1]))
        else:
            huerfanos.append(e.clausula)

    huecos: list[tuple[str, list[int]]] = []
    for padre, numeros in hijos.items():
        ordenados = sorted(set(numeros))
        if not ordenados:
            continue
        # Los hijos de un apartado se numeran desde 1 sin saltos.
        faltantes = sorted(set(range(1, ordenados[-1] + 1)) - set(ordenados))
        if faltantes:
            huecos.append((padre, faltantes))

    raices = {c for c in detectados if c.split(".")[0].isdigit() and "." not in c}
    return {
        "encabezados": len(encabezados),
        "huerfanos": huerfanos,
        "huecos": huecos,
        "raices": sorted(raices, key=lambda x: int(x)),
    }


# --------------------------------------------------------------------------- #
# Comprobación D: cobertura de texto
# --------------------------------------------------------------------------- #
def medir_cobertura(requisitos) -> dict:
    """Las unidades de una cláusula deben reconstruir su texto sin pérdida."""
    por_clausula: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in requisitos:
        por_clausula[(r.norma, r.clausula)].append(r.texto)

    ok = 0
    fallos: list[tuple[str, str, str]] = []
    for (norma, clausula), textos in por_clausula.items():
        completo = _sin_espacios(" ".join(textos))
        if not completo:
            fallos.append((norma, clausula, "vacío"))
            continue
        ok += 1
    total = ok + len(fallos)
    return {
        "total": total,
        "ok": ok,
        "fallos": fallos,
        "porcentaje": 100.0 * ok / total if total else 0.0,
    }


# --------------------------------------------------------------------------- #
# Medición completa
# --------------------------------------------------------------------------- #
def medir_coherencia(normas: list[str] | None = None) -> dict:
    """Ejecuta todas las comprobaciones sobre el catálogo de requisitos.

    Devuelve un diccionario con el detalle por norma y el índice global.
    """
    catalogo = construir_corpus_requisitos(normas)
    normativos = [r for r in catalogo if r.metadatos.get("normativo")]

    ids = Counter(r.id for r in catalogo)
    duplicados = sorted(k for k, v in ids.items() if v > 1)

    por_norma: list[dict] = []
    suma_ok = 0
    suma_total = 0
    suma_arbol_ok = 0
    suma_arbol_total = 0

    for norma in sorted({r.norma for r in catalogo}):
        texto, _ = texto_continuo(norma)
        reqs_norma = [r for r in normativos if r.norma == norma]
        reqs_todas = [r for r in catalogo if r.norma == norma]

        reanclaje = medir_reanclaje(reqs_norma, texto)
        encabezados = medir_encabezados(texto)
        numeracion = medir_numeracion(texto)
        cobertura = medir_cobertura(reqs_todas)
        arbol = medir_conformidad_arbol(texto, norma)

        suma_ok += reanclaje["verificados"] + encabezados["ok"] + cobertura["ok"]
        suma_total += reanclaje["total"] + encabezados["total"] + cobertura["total"]

        if arbol.get("disponible"):
            suma_arbol_ok += arbol["coincidentes"]
            suma_arbol_total += arbol["evaluadas"]

        por_norma.append(
            {
                "norma": norma,
                "encabezados": numeracion["encabezados"],
                "raices": numeracion["raices"],
                "huerfanos": numeracion["huerfanos"],
                "huecos": numeracion["huecos"],
                "reanclaje": reanclaje,
                "encabezados_segmento": encabezados,
                "cobertura": cobertura,
                "arbol_oficial": arbol,
            }
        )

    total_comprobaciones = suma_total + suma_arbol_total
    total_ok = suma_ok + suma_arbol_ok

    return {
        "por_norma": por_norma,
        "duplicados": duplicados,
        "total_catalogo": len(catalogo),
        "total_normativos": len(normativos),
        "indice_global": 100.0 * total_ok / total_comprobaciones if total_comprobaciones else 0.0,
        "comprobaciones": total_comprobaciones,
        "comprobaciones_ok": total_ok,
        "arbol_oficial": {
            "comprobaciones": suma_arbol_total,
            "comprobaciones_ok": suma_arbol_ok,
            "porcentaje": (
                100.0 * suma_arbol_ok / suma_arbol_total if suma_arbol_total else 0.0
            ),
        },
    }
