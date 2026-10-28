"""Extractores de texto: PDF, DOCX, XLSX.

Cada extractor devuelve una lista de `Bloque`, donde un bloque es una unidad
de texto con su referencia de ubicación (página, sección, celda). Esa
referencia es la base de la trazabilidad requisito-evidencia.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mvp_sig.utils.text import colapsar_espacios

# Logging para ver qué extractor se usa
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "extractor_debug.log"


def _log_extractor(msg: str) -> None:
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass
    try:
        sys.stderr.write(f"{msg}\n")
        sys.stderr.flush()
    except Exception:
        pass
    print(msg, flush=True)


# Docling integration (optional)
try:
    from docling.document_converter import DocumentConverter

    _DOCLING_AVAILABLE = True
    try:
        _DOCLING_CONVERTER = DocumentConverter()
    except Exception:
        _DOCLING_CONVERTER = None
except Exception:
    _DOCLING_AVAILABLE = False
    _DOCLING_CONVERTER = None


@dataclass
class Bloque:
    """Fragmento de texto extraído con su procedencia."""

    texto: str
    pagina: int | None = None
    seccion: str | None = None
    tabla: str | None = None
    extras: dict = field(default_factory=dict)

    def clave(self) -> str:
        partes = []
        if self.pagina is not None:
            partes.append(f"p{self.pagina}")
        if self.seccion:
            partes.append(f"s{self.seccion[:40]}")
        if self.tabla:
            partes.append(f"t{self.tabla[:40]}")
        return "|".join(partes) if partes else "bloque"


@dataclass
class DocumentoExtraido:
    ruta: Path
    nombre: str
    tipo: str
    bloques: list[Bloque] = field(default_factory=list)
    paginas: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.bloques)

    def texto_completo(self) -> str:
        return "\n\n".join(b.texto for b in self.bloques if b.texto.strip())


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def extraer_pdf(ruta: Path) -> DocumentoExtraido:
    from pypdf import PdfReader

    doc = DocumentoExtraido(ruta=ruta, nombre=ruta.name, tipo="pdf")
    try:
        reader = PdfReader(str(ruta))
        doc.paginas = len(reader.pages)
        for i, page in enumerate(reader.pages, start=1):
            try:
                texto = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - un PDF corrupto no debe abortar el lote
                texto = ""
            texto = colapsar_espacios(texto)
            if texto.strip():
                doc.bloques.append(Bloque(texto=texto, pagina=i))
    except Exception as exc:  # noqa: BLE001
        doc.error = f"PDF ilegible: {exc}"
    return doc


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #
def _docx_bloques_en_orden(doc) -> list[Bloque]:
    """Intercala párrafos y tablas respetando el orden real del documento."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    bloques: list[Bloque] = []
    seccion_actual = None
    n_tablas = 0
    cuerpo = doc.element.body
    for hijo in cuerpo.iterchildren():
        tag = hijo.tag.split("}")[-1]
        if tag == "p":
            parrafo = Paragraph(hijo, doc)
            texto = parrafo.text.strip()
            estilo = (parrafo.style.name or "").lower() if parrafo.style else ""
            if not texto:
                continue
            if "t" in estilo and estilo.startswith("t") and "título" in estilo or estilo in {"title", "subtitle"}:
                seccion_actual = texto
            elif estilo.startswith("heading") or estilo.startswith("encabezado"):
                seccion_actual = texto
            bloques.append(Bloque(texto=texto, seccion=seccion_actual))
        elif tag == "tbl":
            tabla = Table(hijo, doc)
            n_tablas += 1
            filas = []
            for fila in tabla.rows:
                celdas = [c.text.strip().replace("\n", " ") for c in fila.cells]
                if any(celdas):
                    filas.append(" | ".join(celdas))
            if filas:
                bloques.append(
                    Bloque(
                        texto="\n".join(filas),
                        seccion=seccion_actual,
                        tabla=f"tabla_{n_tablas}",
                    )
                )
    return bloques


def extraer_docx(ruta: Path) -> DocumentoExtraido:
    import docx

    doc = DocumentoExtraido(ruta=ruta, nombre=ruta.name, tipo="docx")
    try:
        d = docx.Document(str(ruta))
        doc.bloques = _docx_bloques_en_orden(d)
        doc.paginas = 0
    except Exception as exc:  # noqa: BLE001
        doc.error = f"DOCX ilegible: {exc}"
    return doc


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #
def extraer_xlsx(ruta: Path) -> DocumentoExtraido:
    import warnings

    import openpyxl

    doc = DocumentoExtraido(ruta=ruta, nombre=ruta.name, tipo="xlsx")
    try:
        with warnings.catch_warnings():
            # openpyxl avisa de validaciones de datos que no puede preservar:
            # es inocuo para la extracción de texto.
            warnings.filterwarnings("ignore", message=".*Data Validation extension.*")
            wb = openpyxl.load_workbook(str(ruta), data_only=True, read_only=True)
            try:
                for hoja in wb.worksheets:
                    filas: list[str] = []
                    n_fila = 0
                    for fila in hoja.iter_rows(values_only=True):
                        n_fila += 1
                        celdas = ["" if v is None else str(v).strip() for v in fila]
                        if not any(celdas):
                            continue
                        texto = " | ".join(c for c in celdas if c)
                        if texto:
                            filas.append(f"[f{n_fila}] {texto}")
                    if filas:
                        doc.bloques.append(
                            Bloque(
                                texto="\n".join(filas),
                                seccion=hoja.title,
                                tabla=hoja.title,
                                extras={"hoja": hoja.title, "filas": n_fila},
                            )
                        )
            finally:
                wb.close()
    except Exception as exc:  # noqa: BLE001
        doc.error = f"XLSX ilegible: {exc}"
    return doc


# --------------------------------------------------------------------------- #
# XLS (Excel 97-2003, formato binario OLE2)
# --------------------------------------------------------------------------- #
def extraer_xls(ruta: Path) -> DocumentoExtraido:
    """Extrae hojas de libros Excel antiguos (``.xls``), comunes en el corpus.

    `xlrd` 2.x sólo lee el formato binario BIFF, que es exactamente lo que
    se necesita aquí (los ``.xlsx`` los cubre `openpyxl`).
    """
    import xlrd

    doc = DocumentoExtraido(ruta=ruta, nombre=ruta.name, tipo="xls")
    try:
        libro = xlrd.open_workbook(str(ruta))
        try:
            for hoja in libro.sheets():
                filas: list[str] = []
                n_fila = 0
                for indice in range(hoja.nrows):
                    n_fila += 1
                    valores = hoja.row_values(indice)
                    tipos = hoja.row_types(indice)
                    celdas: list[str] = []
                    for valor, tipo in zip(valores, tipos):
                        if tipo == xlrd.XL_CELL_DATE:
                            # Las fechas llegan como número serial de Excel.
                            try:
                                celdas.append(
                                    xlrd.xldate_as_datetime(
                                        valor, libro.datemode
                                    ).strftime("%Y-%m-%d")
                                )
                                continue
                            except Exception:  # noqa: BLE001
                                pass
                            celdas.append(str(valor).strip())
                        elif tipo in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                            celdas.append("")
                        elif valor is None:
                            celdas.append("")
                        else:
                            celdas.append(str(valor).strip())
                    if not any(celdas):
                        continue
                    texto = " | ".join(c for c in celdas if c)
                    if texto:
                        filas.append(f"[f{n_fila}] {texto}")
                if filas:
                    doc.bloques.append(
                        Bloque(
                            texto="\n".join(filas),
                            seccion=hoja.name,
                            tabla=hoja.name,
                            extras={"hoja": hoja.name, "filas": n_fila},
                        )
                    )
            doc.paginas = len(libro.sheets())
        finally:
            release = getattr(libro, "release_resources", None)
            if callable(release):
                release()
    except Exception as exc:  # noqa: BLE001
        doc.error = f"XLS ilegible: {exc}"
    return doc


# --------------------------------------------------------------------------- #
# Texto plano
# --------------------------------------------------------------------------- #
def extraer_txt(ruta: Path) -> DocumentoExtraido:
    """Extrae un documento de texto plano (.txt, .md).

    Es el formato en que se materializa la evidencia registrada a mano desde
    la interfaz: el usuario pega un acta, un correo o un reporte y el sistema
    lo conserva como archivo para que la evidencia sea auditable en disco y no
    sólo un texto en memoria.
    """
    doc = DocumentoExtraido(ruta=ruta, nombre=ruta.name, tipo="txt")
    try:
        crudo = ruta.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        doc.error = f"Texto ilegible: {exc}"
        return doc
    for i, parrafo in enumerate(crudo.split("\n\n"), start=1):
        texto = colapsar_espacios(parrafo)
        if texto.strip():
            doc.bloques.append(Bloque(texto=texto, seccion=f"párrafo {i}"))
    if not doc.bloques:
        doc.error = "El archivo no contiene texto legible."
    return doc


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
EXTRACTORES = {
    ".pdf": extraer_pdf,
    ".docx": extraer_docx,
    ".xlsx": extraer_xlsx,
    ".xls": extraer_xls,
    ".txt": extraer_txt,
    ".md": extraer_txt,
}


def _clase_ole(ruta: Path) -> str:
    """Clasifica un contenedor OLE2 (Word/Excel 97-2003) por sus streams.

    Distingue el caso relevante: un documento *cifrado con contraseña* no es
    recuperable sin la credencial, y conviene decirlo con precisión en lugar
    de reportar un error genérico de formato.
    """
    try:
        import olefile
    except ImportError:
        return "desconocido"
    try:
        with olefile.OleFileIO(str(ruta)) as ole:
            nombres = {"/".join(x) for x in ole.listdir()}
    except Exception:  # noqa: BLE001
        return "desconocido"
    if any(n.endswith("EncryptedPackage") for n in nombres):
        return "cifrado"
    if any(n.endswith("WordDocument") for n in nombres):
        return "word"
    if any(n.endswith(("Workbook", "Book")) for n in nombres):
        return "excel"
    return "desconocido"


def extract_documento_docling(ruta: Path) -> DocumentoExtraido:
    if not _DOCLING_AVAILABLE or _DOCLING_CONVERTER is None:
        raise RuntimeError("Docling no disponible")
    try:
        result = _DOCLING_CONVERTER.convert(str(ruta))
        doc = result.document
        # Try to export as markdown/text
        try:
            texto = doc.export_to_markdown()
        except Exception:
            try:
                texto = doc.export_to_text()
            except Exception:
                texto = ""
        if not texto or not texto.strip():
            return DocumentoExtraido(ok=False, tipo=_tipo(ruta), texto="", paginas=0, error="Docling: sin contenido extraído")
        # Try to get page count
        paginas = 0
        try:
            paginas = len(doc.pages) if hasattr(doc, "pages") else 0
        except Exception:
            paginas = 0
        return DocumentoExtraido(ok=True, tipo=_tipo(ruta), texto=texto, paginas=paginas, error=None)
    except Exception as exc:
        return DocumentoExtraido(ok=False, tipo=_tipo(ruta), texto="", paginas=0, error=f"Docling error: {exc}")


def extract_documento(ruta: Path, motor: str | None = None) -> DocumentoExtraido:
    ext = ruta.suffix.lower()
    fn = EXTRACTORES.get(ext)
    if fn is None:
        return DocumentoExtraido(
            ruta=ruta,
            nombre=ruta.name,
            tipo=ext.lstrip("."),
            bloques=[],
            error=f"Formato no soportado: {ext}",
        )
    doc = fn(ruta)
    # Si la extensión no corresponde al formato real, el error debe decirlo.
    if doc.error and sniff_mime(ruta) == "ole":
        clase = _clase_ole(ruta)
        if clase == "cifrado":
            doc.error = (
                "Documento OLE (Word/Excel 97-2003) cifrado con contraseña: "
                "no se puede extraer el texto sin la credencial."
            )
        else:
            doc.error = (
                f"Documento OLE legacy ({clase}) con extensión '{ext}': "
                "no fue posible extraer su contenido."
            )
    return doc


def sniff_mime(ruta: Path) -> str:
    """Detecta el tipo real por firma binaria (evita confiar sólo en la extensión)."""
    try:
        head = ruta.read_bytes()[:8]
    except OSError:
        return "desconocido"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "docx"  # OOXML: docx/xlsx/pptx (se desambigua por extensión)
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"  # .doc/.xls antiguos
    return "desconocido"
