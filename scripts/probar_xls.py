"""Prueba del extractor .xls sobre los libros Excel 97-2003 del corpus."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.ingestion.extractors import extract_documento  # noqa: E402
from mvp_sig.settings import CORPUS_EVIDENCIAS  # noqa: E402

for p in sorted(Path(CORPUS_EVIDENCIAS).rglob("*.xls")):
    doc = extract_documento(p)
    print(f"=== {p.name}")
    if not doc.ok:
        print(f"    ERROR: {doc.error}")
        continue
    print(f"    hojas/paginas: {doc.paginas}  bloques: {len(doc.bloques)}")
    for b in doc.bloques:
        print(f"    - [{b.seccion}] {len(b.texto)} chars")
        for linea in b.texto.splitlines()[:3]:
            print(f"        {linea[:150]}")
