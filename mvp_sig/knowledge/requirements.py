"""Construcción del corpus de requisitos normativos (fase 3.3.a).

Convierte el texto de las tres normas en *unidades de requisito* con
identificador estable, cláusula, ámbito y página. Esa unidad es el sujeto del
diagnóstico y el ancla de la trazabilidad.

La atribución de cláusula no se hace fragmento a fragmento (el corpus semilla
fue segmentado por páginas y un fragmento suele contener varias cláusulas),
sino **por segmentación**: se localiza cada encabezado de cláusula dentro del
texto continuo de la norma, se parte el texto en esos puntos y cada segmento
hereda la cláusula de su encabezado. Es la aproximación que reproduce lo que
un auditor lee en el PDF: la cláusula es la unidad de referencia.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mvp_sig.settings import FRAGMENTO_A_NORMA, NORMAS, PATHS
from mvp_sig.utils.text import (
    colapsar_espacios,
    dividir_oraciones,
    es_continuacion,
    es_exigible,
    es_recomendacion,
    limpiar_ruido_iso,
    truncar,
)

# --------------------------------------------------------------------------- #
# Detección de cláusulas
# --------------------------------------------------------------------------- #
# Número de cláusula: "8.2.3.2". El guard `(?<![\d])(?<!\d\.)` impide capturar
# un sub-número ("2.3.2" dentro de "8.2.3.2") y `(?!\d)` impide partir un año
# ("2015" sólo tiene dos dígitos, así que tampoco casa con el patrón).
# El segundo guard admite "...planificado.8.1 Titulo", donde el extractor de
# PDF pegó el punto final con el número de cláusula.
_RE_NUMERO = re.compile(r"(?<![\d])(?<!\d\.)\d{1,2}(?:\.\d{1,2}){0,3}(?!\d)")

# Encabezado de anexo: "Anexo A (Informativo)".
_RE_ANEXO = re.compile(r"(?i)\banexo\s+([a-z])\b")

# Sub-encabezado de anexo: "A.4.2 Comprensión de las necesidades ...".
# El guard sólo excluye un dígito precedente: el extractor de PDF pega con
# frecuencia el final de una palabra al inicio del encabezado ("externoA.2").
# La letra debe ser una de las de los anexos normativos (A..E): si no, el
# "T" final de un acrónimo ("SST.4.2") se tomaría por un anexo.
_RE_ANEXO_SUB = re.compile(r"(?<![0-9])([A-E])\.(\d{1,2}(?:\.\d{1,2}){0,2})(?!\d)")

# Encabezado de bibliografía (contenido informativo).
_RE_BIBLIOGRAFIA = re.compile(r"(?i)\bbibliograf[ií]a\b")

# Palabras que introducen una *referencia cruzada* ("véase el apartado 8.2")
# y que, por tanto, nunca pueden preceder a un encabezado de cláusula.
_PALABRAS_REFERENCIA = {
    "véase", "vease", "ver", "v", "apartado", "apartados", "cláusula", "clausula",
    "cláusulas", "artículo", "articulo", "página", "pagina", "pág", "tabla",
    "tablas", "figura", "figuras", "anexo", "anexos", "punto", "puntos",
    "sección", "seccion", "inciso", "letra", "capítulo", "capitulo", "iso",
    "une-en", "nota", "notas", "ejemplo", "ejemplos", "e", "y", "o", "u",
    "conforme", "según", "segun", "referente", "relativo", "en", "de", "del",
    "a", "al", "establecido", "establecida", "indicado", "indicada", "previsto",
    "prevista", "definido", "definida", "descrito", "descrita", "aplicable",
    "aplicables", "siguiente", "siguientes", "anterior", "superior", "inferior",
    "mencionado", "mencionada", "citado", "citada", "contemplado", "contemplada",
}
# Sólo las referencias largas se comparan por sufijo ("sub-cláusula").
_REFERENCIAS_LARGAS = {w for w in _PALABRAS_REFERENCIA if len(w) >= 4}

# Conectores de enumeración ("...4.1 y 4.2").  Si el número candidato va
# detrás de un conector puede estar pegado al final de una referencia
# ("apartados 4.1 y 4.2.5 Liderazgo") y ser en realidad un encabezado nuevo.
_CONECTORES = {"y", "e", "o", "u"}

# Token inmediatamente anterior a un número (para descartar referencias).
# Un token numérico con forma de cláusula ("6.1.4") indica que el número
# candidato es la continuación de una lista ("véanse 6.1.4, 6.2, 7, 8 y 9.1").
# Un token como "2015" (referencia a una norma) no cuenta.
_RE_TOKEN_CLAUSULA = re.compile(r"^\d{1,2}(?:\.\d{1,2})*$")

# Cláusulas de primer nivel que existen en ISO 9001/14001/45001.
_CLAUSULAS_RAIZ = set(range(0, 11))

# Cláusulas que aplican a las tres normas (estructura del SIG).
CLAUSULAS_SIG = tuple(f"{i}" for i in range(4, 11))


@dataclass
class Encabezado:
    """Encabezado de cláusula localizado en el texto de la norma."""

    posicion: int
    fin: int
    clausula: str
    tipo: str = "clausula"  # clausula | anexo | anexo_sub | bibliografia
    etiqueta: str = ""      # texto original del encabezado


@dataclass
class Segmento:
    """Tramo de texto que pertenece a una única cláusula."""

    clausula: str
    texto: str
    inicio: int
    fin: int
    pagina: int | None = None
    encabezado: str = ""


@dataclass
class Requisito:
    """Unidad de requisito normativo con su anclaje documental."""

    id: str
    norma: str
    ambito: str
    clausula: str
    texto: str
    pagina: int | None = None
    fuente: str = ""
    tipo: str = "requisito"
    metadatos: dict = field(default_factory=dict)

    @property
    def normativo(self) -> bool:
        """True si la unidad encierran una exigencia exigible."""
        return bool(self.metadatos.get("normativo", self.tipo == "requisito"))

    def to_metadata(self) -> dict:
        return {
            "id": self.id,
            "norma": self.norma,
            "ambito": self.ambito,
            "clausula": self.clausula,
            "tipo": self.tipo,
            "normativo": self.normativo,
            "pagina": self.pagina if self.pagina is not None else -1,
            "fuente": self.fuente,
        }

    def to_dict(self) -> dict:
        d = self.to_metadata()
        d["texto"] = self.texto
        d["metadatos"] = self.metadatos
        return d


# --------------------------------------------------------------------------- #
# Utilidades de bajo nivel
# --------------------------------------------------------------------------- #
@dataclass
class Contexto:
    """Lo que hay inmediatamente antes de un número candidato a encabezado."""

    token: str          # palabra que precede al número (sin puntuación)
    separador: str      # texto entre esa palabra y el número
    cierra_frase: bool  # la palabra cerraba la frase anterior
    token_previo: str   # palabra anterior a esa (la que precede al conector)
    sep_previo: str     # separador entre ambas
    inicio_token: int   # posición del inicio del token en el texto


def _token_previo(texto: str, pos: int) -> Contexto:
    """Analiza el contexto lingüístico inmediatamente anterior a ``pos``.

    El token no incluye la puntuación envolvente; el separador es el texto que
    media entre el token y el candidato (sirve para saber si el candidato
    continúa una lista enumerada con comas).  ``cierra_frase`` indica que el
    token era la última palabra de la frase anterior: en ese caso no puede
    introducir una referencia cruzada.  Lo es cuando el propio token termina
    en puntuación de cierre ("siguientes:", "correctiv a.") o cuando el
    separador la aporta ("apartados 4.1, 4.2").

    El recorrido hacia atrás evita copiar el prefijo del documento en cada
    candidato: con miles de candidatos sobre un texto de cien mil caracteres,
    el copiado convertía el escaneo en una operación cuadrática.
    """
    j = pos - 1
    while j >= 0 and texto[j].isspace():
        j -= 1
    if j < 0:
        return Contexto("", "", False, "", "", 0)
    k = j
    while k >= 0 and not texto[k].isspace():
        k -= 1
    bruto = texto[k + 1 : j + 1]
    token = bruto.strip(".,;:()[]{}\"'«»").lower()
    separador = texto[j + 1 : pos]
    cierra_frase = bruto[-1:] in ".,;:" or separador[:1] in ".,"

    # Palabra anterior: necesaria para saber si un conector ("y", "e") está
    # encadenando una lista de referencias cruzadas.
    j2 = k - 1
    while j2 >= 0 and texto[j2].isspace():
        j2 -= 1
    if j2 < 0:
        token_previo, sep_previo = "", ""
    else:
        k2 = j2
        while k2 >= 0 and not texto[k2].isspace():
            k2 -= 1
        token_previo = texto[k2 + 1 : j2 + 1].strip(".,;:()[]{}\"'«»").lower()
        sep_previo = texto[j2 + 1 : k + 1]

    return Contexto(token, separador, cierra_frase, token_previo, sep_previo, k + 1)


def _es_referencia(token: str) -> bool:
    """True si el token introduce una referencia cruzada."""
    if not token:
        return False
    if token in _PALABRAS_REFERENCIA:
        return True
    return any(token.endswith(w) for w in _REFERENCIAS_LARGAS)


def _empieza_titulo(texto: str, pos: int) -> bool:
    """True si a partir de `pos` empieza un título (letra mayúscula)."""
    resto = texto[pos:]
    if not resto or not resto[0].isspace():
        return False
    resto = resto.lstrip()
    if not resto:
        return False
    c = resto[0]
    return c.isupper() or c in "\"'“«("


def _partes_validas(texto: str) -> tuple[int, ...] | None:
    """Convierte "8.2.3.2" en (8, 2, 3, 2) si es un número de cláusula válido."""
    try:
        partes = tuple(int(p) for p in texto.split("."))
    except ValueError:
        return None
    if not partes:
        return None
    if partes[0] not in _CLAUSULAS_RAIZ:
        return None
    if any(p < 1 for p in partes[1:]):
        return None
    if len(partes) > 4:
        return None
    return partes


def _compatible(actual: tuple[int, ...] | None, partes: tuple[int, ...]) -> bool:
    """¿Puede `partes` ser el siguiente encabezado tras `actual`?

    En las normas ISO los encabezados se recorren en profundidad: 4 -> 4.1 ->
    4.1.1 -> 4.1.2 -> 4.2 -> 5 -> 5.1 ...  Este test reproduce esa secuencia y
    descarta los números que son referencias cruzadas o cifras de un texto.
    """
    if actual is None:
        return True
    da, dc = len(actual), len(partes)
    if partes[0] < actual[0]:
        return False
    if dc > da:
        return partes[:da] == actual
    if dc == da:
        return partes >= actual
    return partes[:-1] == actual[: dc - 1] and partes[-1] > actual[dc - 1]


def _sigue_titulo_o_parentesis(texto: str, pos: int, permite_bracket: bool = False) -> bool:
    """True si tras `pos` empieza un título, un paréntesis o un corchete."""
    resto = texto[pos:].lstrip()
    if not resto:
        return True
    c = resto[0]
    if c.isupper():
        return True
    if c == "(":
        return True
    return permite_bracket and c == "["


def _encadena_lista(texto: str, ctx: Contexto) -> bool:
    """True si el conector está encadenando una lista de referencias.

    En "véanse 6.1.4, 6.2, 7, 8 y 9.1" el conector "y" cierra una enumeración
    separada por comas: el número que sigue es el último elemento de la lista,
    no un encabezado.  En cambio, en "apartados 4.1 y 4.2.5 Liderazgo" no hay
    comas y "4.2.5" sí es un encabezado.

    La comprobación recorre hacia atrás desde el conector hasta la primera
    coma o hasta el final de la frase; el punto decimal de un número de
    cláusula ("4.1.2") también corta el recorrido.
    """
    if ctx.token not in _CONECTORES:
        return False
    limite = max(0, ctx.inicio_token - 200)
    i = ctx.inicio_token - 1
    while i >= limite:
        ch = texto[i]
        if ch == ",":
            return True
        if ch in ".;:":
            return False
        i -= 1
    return False


def _evaluar_numero(
    texto: str,
    ini: int,
    fin: int,
    dato: str,
    ctx: Contexto,
    actual: tuple[int, ...] | None,
    en_anexo: bool,
) -> tuple[str, tuple[int, ...] | None]:
    """Decide si un número es un encabezado de cláusula.

    Devuelve ``(motivo_del_rechazo, clausula_actualizada)``; el motivo es
    cadena vacía cuando el candidato se acepta.
    """
    if en_anexo:
        # Dentro de un anexo sólo hay sub-cláusulas "A.x": los números sueltos
        # son referencias al cuerpo de la norma.
        return "dentro de un anexo", actual
    if not ctx.cierra_frase and _es_referencia(ctx.token):
        return f"referencia cruzada ({ctx.token})", actual
    if _RE_TOKEN_CLAUSULA.match(ctx.token) and "," in ctx.separador:
        # Continuación de una lista numérica ("véanse 6.1.4, 6.2, 7").
        return f"continuación de lista ({ctx.token})", actual
    partes = _partes_validas(dato)
    if partes is None:
        return "número de cláusula no válido", actual
    if not _empieza_titulo(texto, fin):
        return "no le sigue un título", actual
    if not _compatible(actual, partes):
        return f"fuera de secuencia (tras {actual})", actual
    return "", partes


# --------------------------------------------------------------------------- #
# Localización de encabezados
# --------------------------------------------------------------------------- #
def escanear_encabezados(texto: str, diagnostico: list | None = None) -> list[Encabezado]:
    """Localiza los encabezados de cláusula del texto de una norma.

    Devuelve la lista ordenada de encabezados. Un encabezado se acepta sólo si
    cumple tres condiciones: el número es válido para la norma, le sigue un
    título y no está introducido por una palabra de referencia cruzada.

    Si se pasa una lista en ``diagnostico`` se anota en ella el motivo de
    rechazo de cada candidato descartado (auditoría del detector).
    """
    candidatos: list[tuple[int, int, str, str]] = []  # (ini, fin, tipo, dato)

    for m in _RE_NUMERO.finditer(texto):
        candidatos.append((m.start(), m.end(), "numero", m.group(0)))
    for m in _RE_ANEXO.finditer(texto):
        candidatos.append((m.start(), m.end(), "anexo", m.group(1)))
    for m in _RE_ANEXO_SUB.finditer(texto):
        candidatos.append((m.start(), m.end(), "anexo_sub", f"{m.group(1)}.{m.group(2)}"))
    for m in _RE_BIBLIOGRAFIA.finditer(texto):
        candidatos.append((m.start(), m.end(), "bibliografia", ""))

    candidatos.sort(key=lambda c: (c[0], -(c[1] - c[0])))

    encabezados: list[Encabezado] = []
    actual: tuple[int, ...] | None = None
    en_anexo = False

    def _descartar(ini: int, dato: str, tipo: str, motivo: str) -> None:
        if diagnostico is not None:
            diagnostico.append((ini, dato, tipo, motivo))

    for ini, fin, tipo, dato in candidatos:
        ctx = _token_previo(texto, ini)
        motivo = ""

        if tipo == "numero":
            motivo, nuevo_actual = _evaluar_numero(
                texto, ini, fin, dato, ctx, actual, en_anexo
            )
            if (
                motivo
                and ctx.token in _CONECTORES
                and "." in dato
                and not _encadena_lista(texto, ctx)
            ):
                # El extractor de PDF pega una referencia y el encabezado
                # siguiente: "...en los apartados 4.1 y 4.2" + "5 Liderazgo"
                # llega como "4.2.5 Liderazgo".  Se reintenta anclando el
                # encabezado en su último componente, que es el que precede al
                # título.  Si el conector encadena una enumeración de
                # referencias ("véanse 6.1.4, 6.2, 7, 8 y 9.1") no se reintenta:
                # ahí el número es el último elemento de la lista.
                ultimo = dato.rsplit(".", 1)[-1]
                ini_alt = fin - len(ultimo)
                ctx_alt = _token_previo(texto, ini_alt)
                motivo_alt, actual_alt = _evaluar_numero(
                    texto, ini_alt, fin, ultimo, ctx_alt, actual, en_anexo
                )
                if not motivo_alt:
                    ini, dato, motivo, nuevo_actual = ini_alt, ultimo, "", actual_alt
            if motivo:
                _descartar(ini, dato, tipo, motivo)
                continue
            actual = nuevo_actual
            encabezados.append(
                Encabezado(ini, fin, ".".join(str(p) for p in actual), "clausula", dato)
            )
            continue

        if tipo == "anexo":
            letra = dato.upper()
            if _es_referencia(ctx.token) and ctx.token not in {"anexo", "anexos"}:
                motivo = f"referencia cruzada ({ctx.token})"
            elif not _sigue_titulo_o_parentesis(texto, fin):
                # "El Anexo B proporciona detalles ..." no es un encabezado.
                motivo = "no le sigue un título"
            if motivo:
                _descartar(ini, dato, tipo, motivo)
                continue
            en_anexo = True
            actual = None
            encabezados.append(Encabezado(ini, fin, f"Anexo {letra}", "anexo", f"Anexo {letra}"))
            continue

        if tipo == "anexo_sub":
            if _es_referencia(ctx.token) and not _encadena_lista(texto, ctx):
                motivo = f"referencia cruzada ({ctx.token})"
            elif _RE_TOKEN_CLAUSULA.match(ctx.token) and "," in ctx.separador:
                motivo = f"continuación de lista ({ctx.token})"
            elif not _empieza_titulo(texto, fin):
                motivo = "no le sigue un título"
            if motivo:
                _descartar(ini, dato, tipo, motivo)
                continue
            letra, sub = dato.split(".", 1)
            en_anexo = True
            encabezados.append(
                Encabezado(ini, fin, f"Anexo {letra}.{sub}", "anexo_sub", dato)
            )
            continue

        if tipo == "bibliografia":
            if _es_referencia(ctx.token):
                motivo = f"referencia cruzada ({ctx.token})"
            elif not _sigue_titulo_o_parentesis(texto, fin, permite_bracket=True):
                motivo = "no le sigue un título"
            if motivo:
                _descartar(ini, dato, tipo, motivo)
                continue
            actual = None
            en_anexo = False
            encabezados.append(Encabezado(ini, fin, "Bibliografía", "bibliografia", "Bibliografía"))

    # Descarta encabezados duplicados o solapados.
    limpios: list[Encabezado] = []
    for enc in encabezados:
        if limpios and enc.posicion < limpios[-1].fin:
            continue
        if limpios and enc.posicion == limpios[-1].posicion and enc.tipo == limpios[-1].tipo:
            continue
        limpios.append(enc)
    return limpios


# --------------------------------------------------------------------------- #
# Segmentación por cláusula
# --------------------------------------------------------------------------- #
def segmentar_por_clausula(texto: str) -> list[Segmento]:
    """Parte el texto continuo de una norma en tramos con una sola cláusula."""
    encabezados = escanear_encabezados(texto)
    segmentos: list[Segmento] = []

    if not encabezados:
        if texto.strip():
            segmentos.append(Segmento("0", texto.strip(), 0, len(texto)))
        return segmentos

    # Texto previo al primer encabezado: introducción (cláusula 0).
    prefijo = texto[: encabezados[0].posicion].strip()
    if len(prefijo) >= 40:
        segmentos.append(Segmento("0", prefijo, 0, encabezados[0].posicion))

    for i, enc in enumerate(encabezados):
        fin = encabezados[i + 1].posicion if i + 1 < len(encabezados) else len(texto)
        cuerpo = texto[enc.posicion : fin].strip()
        if not cuerpo:
            continue
        segmentos.append(
            Segmento(
                clausula=enc.clausula,
                texto=cuerpo,
                inicio=enc.posicion,
                fin=fin,
                encabezado=enc.etiqueta,
            )
        )
    return segmentos


def detectar_clausula(texto: str, por_defecto: str = "0") -> str:
    """Detecta la cláusula ISO a la que pertenece un fragmento de texto.

    Devuelve la cláusula del primer encabezado encontrado; si el texto no
    contiene ninguno, devuelve `por_defecto`.
    """
    if not texto:
        return por_defecto
    encabezados = escanear_encabezados(texto)
    if encabezados:
        return encabezados[0].clausula
    return por_defecto


# --------------------------------------------------------------------------- #
# Construcción del corpus
# --------------------------------------------------------------------------- #
def _norma_ambito(norma_corta: str) -> str:
    return NORMAS[norma_corta].ambito


def _es_clausula_sig(clausula: str) -> bool:
    return clausula.split(".")[0] in {str(i) for i in range(4, 11)}


def cargar_fragmentos(norma_corta: str) -> list[dict]:
    """Carga los fragmentos pre-segmentados de una norma."""
    spec = NORMAS[norma_corta]
    ruta = PATHS.seed_fragments / spec.fragmentos_json
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontraron los fragmentos de {norma_corta}: {ruta}")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for d in datos:
        d.setdefault("metadatos", {})
    return datos


def _unir_fragmentos(fragmentos: list[dict]) -> tuple[str, list[tuple[int, int, int | None]]]:
    """Une los fragmentos en un texto continuo y anota el rango de páginas."""
    trozos: list[str] = []
    tramos: list[tuple[int, int, int | None]] = []
    pos = 0
    for frag in fragmentos:
        texto = limpiar_ruido_iso(frag.get("contenido", ""))
        if not texto.strip():
            continue
        if trozos:
            pos += 1  # espacio de unión entre fragmentos
        inicio = pos
        trozos.append(texto)
        pos += len(texto)
        tramos.append((inicio, pos, frag.get("metadatos", {}).get("pagina")))
    return "".join(trozos), tramos


def texto_continuo(norma_corta: str) -> tuple[str, list[tuple[int, int, int | None]]]:
    """Texto continuo de una norma y el rango de páginas de cada fragmento.

    El texto continuo es el documento tal como se lee (los fragmentos de
    página unidos), no una reconstrucción: es la referencia contra la que se
    verifica la atribución de cláusulas.
    """
    return _unir_fragmentos(cargar_fragmentos(norma_corta))


def _pagina_de(tramos: list[tuple[int, int, int | None]], offset: int) -> int | None:
    for inicio, fin, pagina in tramos:
        if inicio <= offset < fin:
            return pagina
    return None


def construir_requisitos(
    norma_corta: str,
    *,
    max_chars: int = 1400,
    min_chars: int = 80,
) -> list[Requisito]:
    """Construye las unidades de requisito de una norma.

    La granularidad es de *sub-cláusula* (p. ej. ``7.1.6``), que es el nivel en
    el que un auditor externo formula sus hallazgos.
    """
    spec = NORMAS[norma_corta]
    fragmentos = cargar_fragmentos(norma_corta)
    texto, tramos = _unir_fragmentos(fragmentos)
    segmentos = segmentar_por_clausula(texto)

    # 1) Agrupar los segmentos por cláusula conservando el orden.
    por_clausula: dict[str, list[Segmento]] = {}
    orden: list[str] = []
    for seg in segmentos:
        clave = seg.clausula
        if clave not in por_clausula:
            por_clausula[clave] = []
            orden.append(clave)
        por_clausula[clave].append(seg)

    requisitos: list[Requisito] = []
    for clausula in orden:
        # La Introducción de las ISO es informativa por definición (Directivas
        # ISO/IEC Parte 2) y no contiene requisitos que un auditor pueda
        # exigir: se excluye del corpus normativo.
        if clausula.split(".")[0] == "0":
            continue

        partes = por_clausula[clausula]
        cuerpo = colapsar_espacios(" ".join(p.texto for p in partes))
        if len(cuerpo) < min_chars:
            continue
        pagina = next((p.pagina for p in partes if p.pagina is not None), None)
        encabezado = next((p.encabezado for p in partes if p.encabezado), "")

        unidades = _dividir_en_unidades(cuerpo, clausula, max_chars)
        unidades, informativas = _separar_normativas(unidades)
        # El contenido informativo se conserva en el catálogo (es útil para el
        # análisis de contexto), pero no se evalúa como cumplimiento.
        for i, unidad in enumerate(informativas, start=1):
            if len(unidad) < min_chars:
                continue
            requisitos.append(
                _construir_requisito(
                    norma_corta,
                    clausula,
                    unidad,
                    pagina=pagina,
                    spec=spec,
                    normativo=False,
                    parte=i,
                    partes_total=len(informativas),
                    encabezado=encabezado,
                )
            )
        for i, unidad in enumerate(unidades, start=1):
            if len(unidad) < min_chars:
                continue
            requisitos.append(
                _construir_requisito(
                    norma_corta,
                    clausula,
                    unidad,
                    pagina=pagina,
                    spec=spec,
                    normativo=True,
                    parte=i,
                    partes_total=len(unidades),
                    encabezado=encabezado,
                )
            )
    return requisitos


def _identificador(
    norma: str, clausula: str, normativo: bool, parte: int, partes_total: int
) -> str:
    """Construye el identificador estable de una unidad de requisito.

    Una misma cláusula produce a menudo dos unidades: una *exigible* (la que
    enuncia la obligación) y una *informativa* (la NOTA o el ejemplo que la
    acompaña). Ambas comparten clause, de modo que el identificador debe
    distinguir el tipo además del número de parte; de lo contrario los dos
    registros colisionarían al indexarse en la base vectorial.
    """
    base = f"{norma}-{clausula}"
    if normativo:
        return base if partes_total <= 1 else f"{base}-{parte}"
    return f"{base}-i" if partes_total <= 1 else f"{base}-i{parte}"


def _construir_requisito(
    norma_corta: str,
    clausula: str,
    texto: str,
    *,
    pagina: int | None,
    spec,
    normativo: bool,
    parte: int,
    partes_total: int,
    encabezado: str = "",
) -> Requisito:
    rid = _identificador(norma_corta, clausula, normativo, parte, partes_total)
    return Requisito(
        id=rid,
        norma=norma_corta,
        ambito=_norma_ambito(norma_corta),
        clausula=clausula,
        texto=texto,
        pagina=pagina,
        fuente=f"{spec.nombre_archivo} (pág. {pagina})" if pagina else spec.nombre_archivo,
        tipo="requisito" if normativo else "informativo",
        metadatos={
            "clausula_sig": _es_clausula_sig(clausula),
            "ambito_transversal": _es_clausula_sig(clausula),
            "normativo": normativo,
            "parte": parte,
            "partes_total": partes_total,
            "encabezado": encabezado,
        },
    )


def _separar_normativas(unidades: list[str]) -> tuple[list[str], list[str]]:
    """Separa las unidades que encierran una exigencia de las informativas.

    Una unidad es *exigible* si contiene la modalidad "debe"/"shall". Quedan
    fuera las NOTA, los ejemplos, la bibliografía y el texto que sólo
    recomienda ("debería"): ninguno de ellos genera una no conformidad, y
    evaluarlos como si fueran requisitos invalidaría el diagnóstico.

    Las continuaciones de una enumeración ("a)", "b)", "-") se reincorporan a
    la unidad exigible que las precede, para no perder la parte `b)` de
    un requisito enunciado como lista.
    """
    exigibles: list[str] = []
    informativas: list[str] = []
    ultima_exigible: str | None = None

    for unidad in unidades:
        if es_exigible(unidad):
            exigibles.append(unidad)
            ultima_exigible = unidad
            continue
        # Continuación de una enumeración exigible previa.
        if ultima_exigible and es_continuacion(unidad) and len(unidad) < 900:
            exigibles[-1] = f"{ultima_exigible} {unidad}".strip()
            ultima_exigible = exigibles[-1]
            continue
        informativas.append(unidad)
        ultima_exigible = None

    return exigibles, informativas


def _dividir_en_unidades(texto: str, clausula: str, max_chars: int) -> list[str]:
    """Divide el texto de una cláusula en unidades manejables, sin perder integridad."""
    if len(texto) <= max_chars:
        return [texto]

    # Preferir cortar en fronteras de oración que contengan un numeral de
    # sub-cláusula; si no, cortar por oración.
    oraciones = dividir_oraciones(texto)
    unidades: list[str] = []
    buffer = ""
    for oracion in oraciones:
        if len(buffer) + len(oracion) + 1 > max_chars and buffer:
            unidades.append(buffer.strip())
            buffer = ""
        buffer = f"{buffer} {oracion}".strip()
    if buffer:
        unidades.append(buffer.strip())

    # Si alguna unidad quedó muy corta, fusionarla con la anterior.
    fusionadas: list[str] = []
    for u in unidades:
        if fusionadas and len(u) < 120:
            fusionadas[-1] = f"{fusionadas[-1]} {u}".strip()
        else:
            fusionadas.append(u)
    return fusionadas


def construir_corpus_requisitos(
    normas: list[str] | None = None,
    *,
    solo_normativos: bool = False,
    **kwargs,
) -> list[Requisito]:
    """Corpus de requisitos de las normas indicadas (por defecto, las tres).

    ``solo_normativos=True`` devuelve únicamente las unidades que encierran
    una exigencia ("debe"/"shall"), que son las que un auditor puede
    verificar. El resto (NOTA, ejemplos, bibliografía) queda en el catálogo
    completo, tagged como ``tipo='informativo'``.
    """
    normas = normas or list(NORMAS.keys())
    todos: list[Requisito] = []
    for n in normas:
        todos.extend(construir_requisitos(n, **kwargs))
    if solo_normativos:
        todos = [r for r in todos if r.metadatos.get("normativo")]
    return todos


def resumen_corpus(requisitos: list[Requisito]) -> dict:
    """Estadísticas del corpus de requisitos para la UI y los reportes."""
    por_norma: dict[str, int] = {}
    por_ambito: dict[str, int] = {}
    por_clausula: dict[str, int] = {}
    for r in requisitos:
        por_norma[r.norma] = por_norma.get(r.norma, 0) + 1
        por_ambito[r.ambito] = por_ambito.get(r.ambito, 0) + 1
        por_clausula[r.clausula] = por_clausula.get(r.clausula, 0) + 1
    return {
        "total": len(requisitos),
        "por_norma": por_norma,
        "por_ambito": por_ambito,
        "por_clausula": dict(sorted(por_clausula.items())),
        "caracteres": sum(len(r.texto) for r in requisitos),
    }
