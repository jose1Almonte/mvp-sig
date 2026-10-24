"""Extraccion del arbol de clausulas canonico a partir de los PDF oficiales.

Genera ``data/seed/arbol_oficial.json``: la lista de clausulas (con su titulo)
que cada norma declara en su indice.  Ese archivo es la referencia contra la
que se valida la atribucion de clausulas del pre-procesamiento, de modo que la
comprobacion no dependa de un arbol memorizado sino de las versiones oficiales
de las normas.

Uso::

    python scripts/generar_arbol_oficial.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pypdf import PdfReader  # noqa: E402

from mvp_sig.settings import NORMAS, PATHS  # noqa: E402

TESIS = Path(r"C:\Users\josey\OneDrive\Desktop\Tesis")
PDFS = {
    "ISO9001": TESIS / "Normas" / "UNE-EN ISO 9001 2015.pdf",
    "ISO14001": TESIS / "Normas" / "UNE-EN ISO 14001_2015.pdf",
    "ISO45001": TESIS / "Normas" / "ISO 45001_2018.pdf",
}

# "3.1 Terminos relacionados con ... ..... 12"
# El titulo no contiene puntos; entre el titulo y el numero de pagina hay una
# secuencia de puntos guia que en algunas lineas queda interrumpida por un
# punto suelto ("... Personas ...... . 19"), de ahi el grupo [ \t.]*.
# El titulo puede partirse en dos lineas ("4.2 Comprension ... y de otras" +
# "partes interesadas ..... 10"), por eso se admite un salto de linea.
RE_INDICE = re.compile(
    r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})[ \t]+(?P<tit>[^.]+?)[ \t]*\n?[ \t]*"
    r"\.{2,}[ \t.]*(?P<pag>\d+)[ \t]*$",
    re.MULTILINE,
)
# "Anexo A (informativo) Orientaciones para el uso ... ..... 21"
RE_ANEXO = re.compile(
    r"^(?P<tit>Anexo\s+[A-Z][^\n]*?)[ \t]*\.{2,}[ \t.]*(?P<pag>\d+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# "Introduccion ..... vii" (en ISO 45001 la Introduccion no lleva numero en
# el indice, pero en el cuerpo se numera como clausula 0).
RE_INTRODUCCION = re.compile(
    r"^(?P<tit>Introducci[oó]n)[ \t]*\.{2,}[ \t.]*(?P<pag>[ivxlcdm]+|\d+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def _paginas_indice(lector: PdfReader) -> list[str]:
    """Devuelve el texto de las paginas que contienen el indice de la norma.

    El indice se reconoce por su formato (lineas con puntos guia que terminan
    en numero de pagina) y no por un rotulo: el indice continua en paginas
    siguientes que no repiten el titulo "Indice".
    """
    paginas: list[str] = []
    for pag in lector.pages:
        txt = pag.extract_text() or ""
        lineas = [ln for ln in txt.splitlines() if RE_INDICE.match(ln.strip())]
        if len(lineas) >= 3:
            paginas.append(txt)
    return paginas


def extraer_arbol(ruta_pdf: Path) -> dict:
    lector = PdfReader(str(ruta_pdf))
    clausulas: dict[str, str] = {}
    anexos: dict[str, str] = {}
    for txt in _paginas_indice(lector):
        for m in RE_INDICE.finditer(txt):
            num = m.group("num")
            tit = re.sub(r"\s+", " ", m.group("tit")).strip()
            # La primera coincidencia gana: el indice es la primera
            # aparicion del titulo de la clausula.
            clausulas.setdefault(num, tit)
        for m in RE_INTRODUCCION.finditer(txt):
            clausulas.setdefault("0", "Introducción")
        for m in RE_ANEXO.finditer(txt):
            tit = re.sub(r"\s+", " ", m.group("tit")).strip()
            letra = re.match(r"Anexo\s+([A-Z])", tit, re.IGNORECASE)
            clave = letra.group(1).upper() if letra else tit[:10]
            anexos.setdefault(clave, tit)
    return {"clausulas": clausulas, "anexos": anexos}


def main() -> None:
    destino = PATHS.seed_fragments.parent / "arbol_oficial.json"
    destino.parent.mkdir(parents=True, exist_ok=True)

    arbol: dict[str, dict] = {}
    for clave, pdf in PDFS.items():
        if not pdf.exists():
            print(f"[omitido] no existe {pdf}")
            continue
        datos = extraer_arbol(pdf)
        arbol[clave] = {
            "norma": NORMAS[clave].nombre_archivo,
            "pdf": str(pdf),
            "clausulas": dict(sorted(datos["clausulas"].items(), key=lambda kv: _ord(kv[0]))),
            "anexos": datos["anexos"],
        }
        print(f"  {clave}: {len(datos['clausulas'])} clausulas · {len(datos['anexos'])} anexos")

    destino.write_text(json.dumps(arbol, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEscrito: {destino}")


def _ord(clausula: str) -> tuple:
    return tuple(int(p) for p in clausula.split("."))


if __name__ == "__main__":
    main()
