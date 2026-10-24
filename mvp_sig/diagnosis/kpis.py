"""Matriz de indicadores clave de desempeño (KPI) por ámbito del SIG.

Objetivo específico 3.2 del anteproyecto: "estructurar indicadores de desempeño
asociados a la calidad, el ambiente y la seguridad laboral con base en los
requisitos normativos", y comparar su consistencia y redundancia.

Dos fuentes:
  1. **Derivados**: se extraen de la cláusula 9.1 (monitorización y medición)
     de cada norma, que es donde las ISO Paramount "establecen o sugieren" los
     indicadores.
  2. **Catálogo curado**: matriz de referencia con los indicadores que se usan
     en la práctica en auditoría de SIG, para permitir la comparación
     transversal y detectar redundancias.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from mvp_sig.knowledge.requirements import Requisito
from mvp_sig.utils.text import truncar


@dataclass
class KPI:
    """Indicador clave de desempeño."""

    id: str
    nombre: str
    ambito: str
    norma: str
    clausula_fuente: str
    formula: str
    unidad: str
    frecuencia: str
    meta_sugerida: str
    origen: str            # "normativo" | "catalogo"
    requisito_asociado: str = ""
    descripcion: str = ""
    ambitos_relacionados: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "ambito": self.ambito,
            "norma": self.norma,
            "clausula_fuente": self.clausula_fuente,
            "formula": self.formula,
            "unidad": self.unidad,
            "frecuencia": self.frecuencia,
            "meta_sugerida": self.meta_sugerida,
            "origen": self.origen,
            "requisito_asociado": self.requisito_asociado,
            "descripcion": self.descripcion,
            "ambitos_relacionados": self.ambitos_relacionados,
        }


# --------------------------------------------------------------------------- #
# Catálogo curado de indicadores (referencia de auditoría de SIG)
# --------------------------------------------------------------------------- #
CATALOGO_CURADO: list[dict] = [
    # -- Calidad ------------------------------------------------------------ #
    {
        "id": "CAL-01", "nombre": "Índice de cumplimiento del Sistema Integrado de Gestión",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "9.1.1",
        "formula": "(Nº de requisitos ISO con evidencia verificada / Nº total de requisitos aplicables) × 100",
        "unidad": "%", "frecuencia": "trimestral", "meta_sugerida": "≥ 90 %",
        "descripcion": "Indicador global de la madurez del SIG. Es el que consolida el diagnóstico automatizado.",
    },
    {
        "id": "CAL-02", "nombre": "Cumplimiento de acciones correctivas",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "10.2",
        "formula": "(Acciones correctivas cerradas en plazo / Acciones correctivas abiertas) × 100",
        "unidad": "%", "frecuencia": "mensual", "meta_sugerida": "≥ 95 %",
        "descripcion": "Mide la eficacia y el cierre oportuno de las acciones derivadas de no conformidades.",
    },
    {
        "id": "CAL-03", "nombre": "Tasa de no conformidades internas",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "9.1.3",
        "formula": "(Nº de no conformidades detectadas / Nº de auditorías internas ejecutadas)",
        "unidad": "ratio", "frecuencia": "trimestral", "meta_sugerida": "Tendencia descendente",
        "descripcion": "Detecta desviaciones del proceso antes de que las detecte el cliente.",
    },
    {
        "id": "CAL-04", "nombre": "Satisfacción del cliente",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "9.1.2",
        "formula": "(Clientes con satisfacción alta o muy alta / Total de respuestas) × 100",
        "unidad": "%", "frecuencia": "semestral", "meta_sugerida": "≥ 85 %",
        "descripcion": "Vigila el cumplimiento de los requisitos del cliente (9.1.2).",
    },
    {
        "id": "CAL-05", "nombre": "Cumplimiento de objetivos del SIG",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "6.2",
        "formula": "(Nº de objetivos con KPI en meta / Nº total de objetivos del SIG) × 100",
        "unidad": "%", "frecuencia": "trimestral", "meta_sugerida": "≥ 80 %",
        "descripcion": "Verifica la eficacia de la planificación (6.2) y del seguimiento (9.1).",
    },
    {
        "id": "CAL-06", "nombre": "Control de información documentada",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "7.5",
        "formula": "(Documentos revisados y vigentes / Documentos del listado maestro) × 100",
        "unidad": "%", "frecuencia": "semestral", "meta_sugerida": "100 %",
        "descripcion": "Mide la salud de la documentación controlada.",
    },
    {
        "id": "CAL-07", "nombre": "Eficacia de la revisión por la dirección",
        "ambito": "calidad", "norma": "ISO9001", "clausula_fuente": "9.3",
        "formula": "(Decisiones de la revisión ejecutadas / Decisiones registradas en acta) × 100",
        "unidad": "%", "frecuencia": "anual", "meta_sugerida": "100 %",
        "descripcion": "Verifica el cierre de las decisiones de la alta dirección.",
    },
    # -- Ambiente ------------------------------------------------------------ #
    {
        "id": "AMB-01", "nombre": "Cumplimiento de objetivos ambientales",
        "ambito": "ambiente", "norma": "ISO14001", "clausula_fuente": "6.2",
        "formula": "(Nº de objetivos ambientales en meta / Total de objetivos ambientales) × 100",
        "unidad": "%", "frecuencia": "trimestral", "meta_sugerida": "≥ 85 %",
        "descripcion": "Mide la eficacia del programa de gestión ambiental.",
    },
    {
        "id": "AMB-02", "nombre": "Consumo de agua por unidad producida",
        "ambito": "ambiente", "norma": "ISO14001", "clausula_fuente": "9.1.1",
        "formula": "(m³ de agua consumida / Unidad de producto terminado)",
        "unidad": "m³/u", "frecuencia": "mensual", "meta_sugerida": "Tendencia descendente",
        "descripcion": "Mide la eficiencia del uso del agua (programas de ahorro).",
    },
    {
        "id": "AMB-03", "nombre": "Consumo de energía eléctrica por unidad producida",
        "ambito": "ambiente", "norma": "ISO14001", "clausula_fuente": "9.1.1",
        "formula": "(kWh consumidos / Unidad de producto terminado)",
        "unidad": "kWh/u", "frecuencia": "mensual", "meta_sugerida": "Tendencia descendente",
        "descripcion": "Mide la eficiencia energética del proceso.",
    },
    {
        "id": "AMB-04", "nombre": "Generación de residuos peligrosos",
        "ambito": "ambiente", "norma": "ISO14001", "clausula_fuente": "8.1",
        "formula": "(kg de residuos peligrosos generados / Unidad producida)",
        "unidad": "kg/u", "frecuencia": "mensual", "meta_sugerida": "Tendencia descendente",
        "descripcion": "Vigila la gestión integral de residuos (8.1).",
    },
    {
        "id": "AMB-05", "nombre": "Cumplimiento de requisitos legales ambientales",
        "ambito": "ambiente", "norma": "ISO14001", "clausula_fuente": "9.1.2",
        "formula": "(Requisitos legales ambientales evaluados y conformes / Total de requisitos legales) × 100",
        "unidad": "%", "frecuencia": "semestral", "meta_sugerida": "100 %",
        "descripcion": "Verifica el cumplimiento del marco legal (9.1.2 / 6.1.3).",
    },
    {
        "id": "AMB-06", "nombre": "Índice de significancia de aspectos ambientales",
        "ambito": "ambiente", "norma": "ISO14001", "clausula_fuente": "6.1.2",
        "formula": "(Nº de aspectos ambientales con controles implementados / Total de aspectos identificados) × 100",
        "unidad": "%", "frecuencia": "anual", "meta_sugerida": "≥ 90 %",
        "descripcion": "Mide la cobertura de la matriz de aspectos e impactos.",
    },
    # -- Seguridad y salud en el trabajo ------------------------------------- #
    {
        "id": "SST-01", "nombre": "Índice de frecuencia de accidentes (IF)",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "9.1.2",
        "formula": "(Nº de accidentes con tiempo perdido × 200 000) / Total de horas-hombre trabajadas",
        "unidad": "índice", "frecuencia": "mensual", "meta_sugerida": "Tendencia descendente a 0",
        "descripcion": "Indicador estándar de Accidentabilidad para el seguimiento de 9.1.2.",
    },
    {
        "id": "SST-02", "nombre": "Índice de gravedad (IG)",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "9.1.2",
        "formula": "(Nº de días de incapacidad × 100) / Total de horas-hombre trabajadas",
        "unidad": "índice", "frecuencia": "mensual", "meta_sugerida": "Tendencia descendente a 0",
        "descripcion": "Complementa el IF con la severidad de las consecuencias.",
    },
    {
        "id": "SST-03", "nombre": "Cumplimiento del plan de inspecciones",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "9.1.2",
        "formula": "(Inspecciones ejecutadas / Inspecciones programadas) × 100",
        "unidad": "%", "frecuencia": "mensual", "meta_sugerida": "≥ 95 %",
        "descripcion": "Mide la ejecución del programa de inspecciones (9.1.2).",
    },
    {
        "id": "SST-04", "nombre": "Cobertura de capacitación en SST",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "7.2",
        "formula": "(Personal capacitado en SST / Personal total expuesto) × 100",
        "unidad": "%", "frecuencia": "semestral", "meta_sugerida": "100 %",
        "descripcion": "Verifica la competencia del personal (7.2) y reduce el riesgo por falta de formación.",
    },
    {
        "id": "SST-05", "nombre": "Cierre de acciones correctivas de seguridad",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "10.2",
        "formula": "(Acciones de seguridad cerradas en plazo / Acciones de seguridad abiertas) × 100",
        "unidad": "%", "frecuencia": "mensual", "meta_sugerida": "≥ 95 %",
        "descripcion": "Mide la eficacia del ciclo de mejora continua (10.2).",
    },
    {
        "id": "SST-06", "nombre": "Realización de simulacros de emergencia",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "8.2",
        "formula": "(Simulacros ejecutados / Simulacros programados) × 100",
        "unidad": "%", "frecuencia": "anual", "meta_sugerida": "100 %",
        "descripcion": "Verifica la preparación para emergencias (8.2).",
    },
    {
        "id": "SST-07", "nombre": "Cobertura de controles de riesgos prioritarios",
        "ambito": "seguridad", "norma": "ISO45001", "clausula_fuente": "6.1.2",
        "formula": "(Riesgos prioritarios con control implementado / Total de riesgos prioritarios) × 100",
        "unidad": "%", "frecuencia": "trimestral", "meta_sugerida": "≥ 95 %",
        "descripcion": "Mide la eficacia de la identificación y valoración de peligros (6.1.2).",
    },
    # -- Transversales ------------------------------------------------------- #
    {
        "id": "SIG-01", "nombre": "Trazabilidad requisito-evidencia",
        "ambito": "integral", "norma": "ISO9001", "clausula_fuente": "7.5.3",
        "formula": "(Citas verificadas contra el documento fuente / Citas declaradas en el diagnóstico) × 100",
        "unidad": "%", "frecuencia": "trimestral", "meta_sugerida": "≥ 95 %",
        "descripcion": "Indicador propio del sistema: mide la confianza del diagnóstico automatizado.",
    },
    {
        "id": "SIG-02", "nombre": "Cobertura documental del SIG",
        "ambito": "integral", "norma": "ISO9001", "clausula_fuente": "7.5.2",
        "formula": "(Documentos del listado maestro vigentes / Total de documentos requeridos) × 100",
        "unidad": "%", "frecuencia": "semestral", "meta_sugerida": "100 %",
        "descripcion": "Mide la suficiencia de la información documentada del SIG.",
    },
]


# --------------------------------------------------------------------------- #
# Derivación desde las normas
# --------------------------------------------------------------------------- #
_CLAUSULAS_MEDICION = ("9.1", "9.1.1", "9.1.2", "9.1.3", "9.2", "9.3", "8.1", "6.2")


def derivar_kpis_normativos(requisitos: list[Requisito]) -> list[KPI]:
    """Extrae los indicadores que las normas establecen o sugieren.

    Se localizan los requisitos de las cláusulas de monitorización y
    medición, y se registra el indicador con su cláusula de origen.
    """
    salida: list[KPI] = []
    contador = 0
    for req in requisitos:
        raiz = req.clausula.split(".")[0]
        if req.clausula not in _CLAUSULAS_MEDICION and not req.clausula.startswith("9.1"):
            continue
        if len(req.texto) < 80:
            continue
        contador += 1
        salida.append(
            KPI(
                id=f"NORM-{contador:03d}",
                nombre=truncar(req.texto, 120),
                ambito=req.ambito,
                norma=req.norma,
                clausula_fuente=req.clausula,
                formula="A definir por la organización a partir del requisito",
                unidad="-",
                frecuencia="trimestral",
                meta_sugerida="A definir",
                origen="normativo",
                requisito_asociado=req.id,
                descripcion=truncar(req.texto, 400),
            )
        )
    return salida


def construir_matriz_kpis(requisitos: list[Requisito] | None = None) -> list[KPI]:
    """Matriz consolidada: catálogo curado + indicadores derivados de las normas."""
    kpis: list[KPI] = []
    for item in CATALOGO_CURADO:
        kpis.append(
            KPI(
                id=item["id"],
                nombre=item["nombre"],
                ambito=item["ambito"],
                norma=item["norma"],
                clausula_fuente=item["clausula_fuente"],
                formula=item["formula"],
                unidad=item["unidad"],
                frecuencia=item["frecuencia"],
                meta_sugerida=item["meta_sugerida"],
                origen="catalogo",
                descripcion=item.get("descripcion", ""),
            )
        )
    if requisitos:
        kpis.extend(derivar_kpis_normativos(requisitos))
    return _enriquecer_relaciones(kpis)


def _enriquecer_relaciones(kpis: list[KPI]) -> list[KPI]:
    """Detecta indicadores con el mismo propósito en distintos ámbitos.

    Es el análisis de *consistencia y redundancia* que pide el objetivo 3.2:
    un mismo KPI aplicable a varias normas se marca como transversal, y así
    se evita duplicar indicadores en el cuadro de mando integral.
    """
    # Palabras clave que definen la "familia" funcional de un indicador.
    familias = {
        "cumplimiento_legal": ("requisitos legales", "requisitos legales evaluados"),
        "acciones_correctivas": ("acciones correctivas", "cierre de acciones"),
        "cumplimiento_objetivos": ("objetivos", "cumplimiento de objetivos"),
        "consumo_agua": ("agua",),
        "consumo_energia": ("energía", "energia"),
        "residuos": ("residuos",),
        "capacitacion": ("capacitación", "capacitacion"),
        "documentacion": ("documentos", "información documentada", "informacion documentada"),
    }
    for k in kpis:
        texto = f"{k.nombre} {k.descripcion}".lower()
        relacionados = []
        for familia, claves in familias.items():
            if any(c in texto for c in claves):
                relacionados.append(familia)
        k.ambitos_relacionados = sorted(relacionados)
    return kpis


# --------------------------------------------------------------------------- #
# Análisis de consistencia y redundancia
# --------------------------------------------------------------------------- #
def analizar_consistencia(kpis: list[KPI]) -> dict:
    """Analiza consistencia y redundancia de la matriz de indicadores."""
    por_familia: dict[str, list[KPI]] = {}
    for k in kpis:
        for f in k.ambitos_relacionados:
            por_familia.setdefault(f, []).append(k)

    transversales = {
        f: sorted({k.ambito for k in grupo})
        for f, grupo in por_familia.items()
        if len({k.ambito for k in grupo}) > 1
    }
    por_ambito: dict[str, int] = {}
    for k in kpis:
        por_ambito[k.ambito] = por_ambito.get(k.ambito, 0) + 1

    # Cobertura de las tres normas por los indicadores curados.
    cobertura_normas: dict[str, int] = {}
    for k in kpis:
        cobertura_normas[k.norma] = cobertura_normas.get(k.norma, 0) + 1

    return {
        "total_kpis": len(kpis),
        "por_ambito": por_ambito,
        "cobertura_normas": cobertura_normas,
        "indicadores_transversales": transversales,
        "potenciales_redundancias": sorted(transversales),
        "frecuencias": _conteo(k.frecuencia for k in kpis),
    }


def _conteo(valores) -> dict[str, int]:
    salida: dict[str, int] = {}
    for v in valores:
        salida[v] = salida.get(v, 0) + 1
    return dict(sorted(salida.items()))


# --------------------------------------------------------------------------- #
# Exportación
# --------------------------------------------------------------------------- #
COLUMNAS_KPI = [
    "id", "nombre", "ambito", "norma", "clausula_fuente", "formula", "unidad",
    "frecuencia", "meta_sugerida", "origen", "requisito_asociado", "descripcion",
    "ambitos_relacionados",
]


def exportar_kpis(kpis: list[KPI], ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNAS_KPI)
        writer.writeheader()
        for k in kpis:
            fila = k.to_dict()
            fila["ambitos_relacionados"] = ", ".join(k.ambitos_relacionados)
            writer.writerow(fila)
    return ruta


def exportar_kpis_json(kpis: list[KPI], analisis: dict, ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(
            {"kpis": [k.to_dict() for k in kpis], "analisis": analisis},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return ruta
