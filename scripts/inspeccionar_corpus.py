"""Inspección de los archivos del corpus que la ingesta no cubre."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvp_sig.settings import CORPUS_EVIDENCIAS  # noqa: E402

OLE = b"\xd0\xcf\x11\xe0"
ZIP = b"PK\x03\x04"

print("--- Archivos con extensión no indexada ---")
for p in sorted(Path(CORPUS_EVIDENCIAS).rglob("*")):
    if not p.is_file():
        continue
    ext = p.suffix.lower()
    if ext in {".pdf", ".docx", ".xlsx"}:
        continue
    head = p.read_bytes()[:8]
    if head.startswith(OLE):
        tipo = "OLE2"
    elif head.startswith(ZIP):
        tipo = "ZIP"
    elif head.startswith(b"Rar"):
        tipo = "RAR"
    else:
        tipo = "otro"
    etiqueta = ext if ext else "(sin ext)"
    print(f"{etiqueta:12} {tipo:5} {p.stat().st_size:>9} bytes  {p.name}")

print()
print("--- Contenedores OLE2 clasificados ---")
try:
    import olefile
except ImportError:
    olefile = None

for p in sorted(Path(CORPUS_EVIDENCIAS).rglob("*")):
    if not p.is_file():
        continue
    try:
        head = p.read_bytes()[:4]
    except OSError:
        continue
    if not head.startswith(OLE):
        continue
    clase = "desconocido"
    if olefile is not None:
        try:
            with olefile.OleFileIO(str(p)) as ole:
                nombres = {"/".join(x) for x in ole.listdir()}
            if any(n.endswith("EncryptedPackage") for n in nombres):
                clase = "CIFRADO (contraseña)"
            elif any(n.endswith("WordDocument") for n in nombres):
                clase = "Word 97-2003"
            elif any(n.endswith(("Workbook", "Book")) for n in nombres):
                clase = "Excel 97-2003"
        except Exception as exc:  # noqa: BLE001
            clase = f"ilegible ({exc})"
    print(f"{clase:22} ext={p.suffix.lower():6} {p.stat().st_size:>9}  {p.name}")
