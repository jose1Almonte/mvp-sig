"""Catálogo de evidencias: registro documental y clasificación por ámbito SIG.

Implementa la "metodología documental de evidencias" (fase 3.1 del
anteproyecto): cada documento se registra con metadatos, responsable y tipo, y
se clasifica por el ámbito del SIG al que sirve como evidencia.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mvp_sig.utils.text import normalizar, truncar

# --------------------------------------------------------------------------- #
# Léxico de clasificación por ámbito
# --------------------------------------------------------------------------- #
KEYWORDS: dict[str, tuple[str, ...]] = {
    "calidad": (
        "calidad", "auditoria interna", "no conformidad", "accion correctiva",
        "control de documentos", "control de registros", "revision por la direccion",
        "revision por la gerencia", "mapa de procesos", "caracterizacion de proceso",
        "satisfaccion del cliente", "gestion de complaints", "quejas",
        "listado maestro", "manual del sistema", "alcance del sistema",
        "objetivos del sistema", "indicador", "kpi", "planificacion de requisitos",
        "producto no conforme", "control de producto", "cumplimiento de requisitos",
        "auditoria", "certificacion", "organigrama", "partes interesadas",
        "gestion documental", "informes de gestion",
    ),
    "ambiente": (
        "ambiental", "ambiente", "aspecto ambiental", "impacto ambiental",
        "residuo", "residuos peligrosos", "residuos no peligrosos",
        "emision", "emisiones", "vertido", "vertidos", "agua", "energia",
        "consumo de agua", "ahorro de energia", "huella de carbono",
        "residuos solidos", "compostaje", "reciclaje", "requisitos legales ambientales",
        "plan de manejo ambiental", "monitoreo ambiental", "sedimento",
    ),
    "seguridad": (
        "seguridad y salud", "sst", "salud ocupacional", "seguridad industrial",
        "riesgo", "peligro", "matriz de peligros", "identificacion de peligros",
        "accidente", "incidente", "investigacion de accident", "reporte de actos",
        "condiciones inseguras", "pve", "evaluacion de riesgo psicosocial",
        "epp", "epi", "botiquin", "extintor", "simulacro", "evacuacion",
        "plan de contingencia", "emergencia", "capacitacion", "entrenamiento",
        "medico ocupacional", "examen medico", "brigadista", "comite de seguridad",
        "transporte", "vehiculos", "maquinaria", "seguridad vial",
        "inspeccion de areas", "higiene industrial",
    ),
    "integral": (
        "politica integrada", "sistema integrado de gestion", "sig",
        "alcance del sistema integrado", "politica del sistema",
        "revision por la direccion", "comite de la direccion",
        "estructura organizacional", "asignacion de responsabilidades",
        "planificacion", "comunicacion interna", "participacion de los trabajadores",
        "cuestiones internas", "cuestiones externas", "plan de auditoria integral",
        "informe de auditoria integral",
    ),
}

# Documentos que son transversales al SIG por definición.
TRANSVERSALES = (
    "manual del sistema integrado", "politica integrada", "alcance del sistema integrado",
    "organigrama", "mapa de procesos", "revision por la direccion", "revision por la gerencia",
    "acta de nombramiento del responsable del sig", "objetivos del sistema integrado",
    "plan de auditoria interna", "informe de auditoria interna integral",
    "cuadro de mando integral", "listado maestro de informacion documentada",
)


def clasificar_ambitos(nombre: str, texto_muestra: str = "") -> tuple[list[str], str]:
    """Devuelve (ámbitos, ámbito principal) para un documento.

    Se apoya en el nombre del archivo (señal fuerte, curada por la
    organización) y en el contenido (señal débil).
    """
    n = normalizar(nombre)
    m = normalizar(texto_muestra[:4000])

    puntajes: dict[str, int] = {k: 0 for k in KEYWORDS}
    for ambito, palabras in KEYWORDS.items():
        for palabra in palabras:
            if palabra in n:
                puntajes[ambito] += 3          # el nombre pesa más
            elif palabra in m:
                puntajes[ambito] += 1

    for marca in TRANSVERSALES:
        if marca in n:
            puntajes["integral"] += 4
            break

    if all(v == 0 for v in puntajes.values()):
        return ["integral"], "integral"

    ambitos = [a for a, v in puntajes.items() if v > 0]
    # Un documento transversal también sirve a los ámbitos que sí marcó.
    if "integral" in ambitos:
        for a in ("calidad", "ambiente", "seguridad"):
            if puntajes[a] > 0:
                ambitos.append(a)
    principal = max(puntajes.items(), key=lambda kv: kv[1])[0]
    if principal == "integral" and len(ambitos) > 1:
        # Si sólo se marcó transversal por el nombre, el principal es el de mayor puntaje real.
        reales = {a: v for a, v in puntajes.items() if a != "integral" and v > 0}
        if reales:
            principal = max(reales.items(), key=lambda kv: kv[1])[0]
    return sorted(set(ambitos)), principal


# Palabras que sugieren el tipo documental (usado como metadato y en la UI).
TIPO_DOC_PATRONES: list[tuple[str, tuple[str, ...]]] = [
    ("manual", ("manual del sistema", "manual de calidad")),
    ("procedimiento", ("procedimiento",)),
    ("instructivo", ("instructivo",)),
    ("matriz", ("matriz",)),
    ("plan", ("plan de", "programa de", "plan anual")),
    ("informe", ("informe", "reporte de")),
    ("acta", ("acta",)),
    ("formato", ("formato", "ficha", "registro de")),
    ("lista", ("listado", "lista de", "lista maestro")),
    ("politica", ("politica",)),
    ("requisitos", ("requisitos legales", "requisitos y expectativas")),
]


def inferir_tipo_documento(nombre: str) -> str:
    n = normalizar(nombre)
    for tipo, patrones in TIPO_DOC_PATRONES:
        if any(p in n for p in patrones):
            return tipo
    return "documento"


# --------------------------------------------------------------------------- #
# Registro documental
# --------------------------------------------------------------------------- #
def clave_documento(documento: str, ruta: str | Path) -> str:
    """Identificador único de un documento dentro del catálogo.

    El corpus CIL ONG contiene 17 pares de documentos **homónimos** (el mismo
    nombre en carpetas distintas: `Revisión por la Dirección_CIL ONG.docx` está
    en dos sitios).  El nombre, por tanto, no identifica un documento: dos
    entradas con el mismo nombre serían indistinguibles en la matriz de
    trazabilidad y, peor, una acción sobre una afectaría a la otra.

    La clave combina el nombre visible con un resumen corto de la ruta, de modo
    que sea estable entre ejecuciones y legible en la interfaz:

        ``Revisión por la Dirección_CIL ONG.docx#a1b2c3``
    """
    resumen = hashlib.sha1(str(ruta).encode("utf-8")).hexdigest()[:6]
    return f"{documento}#{resumen}"


def id_documento(ruta: str | Path) -> str:
    """Identificador corto y seguro para usar en una URL.

    La `clave_documento` es legible pero contiene `#` y espacios, que hay que
    escapar en una URL.  Este identificador (12 hexadecimales) se puede
    escribir tal cual en un endpoint y sigue siendo único dentro del corpus.
    """
    return hashlib.sha1(str(ruta).encode("utf-8")).hexdigest()[:12]


@dataclass
class RegistroEvidencia:
    """Entrada del catálogo documental de evidencias."""

    documento: str
    ruta: str
    tipo: str
    tipo_documento: str
    ambitos: list[str]
    ambito_principal: str
    paginas: int
    bloques: int
    chunks: int
    caracteres: int
    sha256: str
    modificado: str
    indexado: str
    estado: str = "indexado"
    notas: list[str] = field(default_factory=list)
    organizacion: str = ""
    codigo: str = ""
    clave: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.clave:
            self.clave = clave_documento(self.documento, self.ruta)
        if not self.id:
            self.id = id_documento(self.ruta)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "clave": self.clave,
            "documento": self.documento,
            "ruta": self.ruta,
            "tipo": self.tipo,
            "tipo_documento": self.tipo_documento,
            "ambitos": self.ambitos,
            "ambito_principal": self.ambito_principal,
            "paginas": self.paginas,
            "bloques": self.bloques,
            "chunks": self.chunks,
            "caracteres": self.caracteres,
            "sha256": self.sha256,
            "modificado": self.modificado,
            "indexado": self.indexado,
            "estado": self.estado,
            "notas": self.notas,
            "organizacion": self.organizacion,
            "codigo": self.codigo,
        }


def sha256_archivo(ruta: Path, bloques: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        while True:
            bloque = fh.read(bloques)
            if not bloque:
                break
            h.update(bloque)
    return h.hexdigest()


def metadatos_responsable(nombre: str) -> dict[str, str]:
    """Extrae metadatos de gestión del nombre del archivo.

    Convención observada en el corpus: ``<Documento>_<SIG>.docx`` donde el
    sufijo identifica la organización, y algunos documentos traen el
    responsable dentro del nombre (p. ej. "Director HSEQ").
    """
    base = Path(nombre).stem
    sufijo = None
    if "_" in base:
        posible = base.rsplit("_", 1)[-1].strip()
        if 2 <= len(posible) <= 40:
            sufijo = posible
    return {
        "codigo": re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-"),
        "organizacion": sufijo or "",
        "nombre": truncar(base, 120),
    }


def ahora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
