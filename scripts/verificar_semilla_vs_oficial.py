"""Verifica la semilla normativa contra las versiones oficiales de las normas.

El objetivo especifico de validacion exige comprobar el sistema "usando las
versiones oficiales de las normas". Este script contrasta el corpus normativo
que consume el MVP (`data/seed/iso_fragments/`) con los PDF oficiales de
`Tesis/Normas/`, y cuantifica:

* que porcentaje del texto oficial conserva la semilla;
* que clausulas raiz (0-10) aparecen en una y otra;
* que el titulo oficial de cada clausula raiz sobrevive en la semilla.

Uso::

    python scripts/verificar_semilla_vs_oficial.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pypdf import PdfReader  # noqa: E402

TESIS = Path(r"C:\Users\josey\OneDrive\Desktop\Tesis")
SEMILLA = RAIZ / "data" / "seed" / "iso_fragments"

PARES = [
    (
        TESIS / "Normas" / "UNE-EN ISO 9001 2015.pdf",
        SEMILLA / "UNE-EN ISO 9001 2015_fragmentos.json",
    ),
    (
        TESIS / "Normas" / "UNE-EN ISO 14001_2015.pdf",
        SEMILLA / "UNE-EN ISO 14001_2015_fragmentos.json",
    ),
    (
        TESIS / "Normas" / "ISO 45001_2018.pdf",
        SEMILLA / "ISO 45001_2018_fragmentos.json",
    ),
]


def colapsar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto)


def sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    ).lower()


def titulos_raiz(texto_pdf: str) -> dict[str, str]:
    """Extrae 'numero -> titulo' de las clausulas raiz del PDF oficial.

    Los titulos del PDF aparecen en el indice con puntos guia ('......') o en
    el cuerpo como '7.5 Informacion documentada' al inicio de una linea.
    """
    titulos: dict[str, str] = {}
    # Indice: "7.5 Informacion documentada ......... 23"
    for m in re.finditer(
        r"(?m)^[ \t]*(\d{1,2})[ \t]+([A-ZÁÉÍÓÚÑ][^\n.]{4,80}?)[ \t]*\.{2,}",
        texto_pdf,
    ):
        num, tit = m.group(1), m.group(2).strip()
        if num not in titulos:
            titulos[num] = tit
    # Cuerpo del documento: "7.5 Informacion documentada" en linea propia.
    for m in re.finditer(
        r"(?m)^[ \t]*(\d{1,2})[ \t]+([A-ZÁÉÍÓÚÑ][^\n]{4,80}?)[ \t]*$",
        texto_pdf,
    ):
        num, tit = m.group(1), m.group(2).strip()
        if num not in titulos and not tit.endswith("."):
            titulos[num] = tit
    return titulos


def main() -> None:
    carpeta = TESIS / "Normas"
    if not carpeta.is_dir():
        print("No se encuentra la carpeta de normas oficiales en:", carpeta)
        return

    for pdf, js in PARES:
        if not pdf.exists() or not js.exists():
            print(f"[omitido] {pdf.name} o su semilla no existen")
            continue

        lector = PdfReader(str(pdf))
        texto_pdf = colapsar(" ".join((p.extract_text() or "") for p in lector.pages))
        crudo_pdf = "\n".join((p.extract_text() or "") for p in lector.pages)
        semilla = json.loads(js.read_text(encoding="utf-8"))
        cont = " ".join(f.get("contenido", "") for f in semilla)

        titulos = titulos_raiz(crudo_pdf)
        cont_plano = sin_acentos(cont)

        print("=" * 78)
        print(pdf.name)
        print(f"  PDF oficial  : {len(lector.pages):>3} paginas · {len(texto_pdf):,} caracteres")
        print(
            f"  Semilla      : {len(semilla):>3} fragmentos · {len(cont):,} caracteres"
            f"  -> {len(cont) / len(texto_pdf) * 100:.1f} % del PDF"
        )

        if not titulos:
            print("  (no se pudieron extraer los titulos del indice)")
            continue

        ausentes = []
        print("  Clausulas raiz (titulo oficial -> presente en la semilla?):")
        for num in sorted(titulos, key=lambda x: int(x)):
            if int(num) > 10:
                continue  # pies de pagina y numeracion de anexos, no son clausulas
            tit = titulos[num]
            presente = sin_acentos(tit)[:45] in cont_plano
            marca = "SI" if presente else "NO"
            if not presente:
                ausentes.append(f"{num} {tit}")
            print(f"      {num:>3} {tit[:56]:<58} {marca}")
        print(f"  Ausentes: {ausentes or 'ninguna'}")


if __name__ == "__main__":
    main()
