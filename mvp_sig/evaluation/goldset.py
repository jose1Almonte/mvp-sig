"""Conjunto de referencia (gold set) para evaluar la recuperación semántica.

Cada entrada asocia un requisito normativo con los documentos que *deberían*
sustentarlo en el corpus de la organización. Sirve para medir precisión, recall
y nDCG de la base vectorial, que es el indicador central de la fase 4.1 del
anteproyecto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Extensiones de los documentos del corpus: no forman parte del nombre del
# documento y enturbian la comparación por tokens ("gestion.docx" != "gestion").
_EXTENSIONES = (".docx", ".xlsx", ".xls", ".pdf", ".doc", ".csv", ".txt")


def _tokens_significativos(texto: str) -> set[str]:
    """Palabras de más de cuatro letras, sin extensión ni puntuación.

    "2. Manual del Sistema Integrado de Gestión.docx" produce
    {manual, sistema, integrado, gestion}: la extensión se descarta y los
    separadoresnuméricos no arrastran palabras sueltas.
    """
    from mvp_sig.utils.text import normalizar

    limpio = normalizar(texto)
    for ext in _EXTENSIONES:
        if limpio.endswith(ext):
            limpio = limpio[: -len(ext)]
            break
    return {t for t in re.split(r"[^a-z0-9]+", limpio) if len(t) > 4}


@dataclass
class CasoGold:
    """Requisito de referencia y documentos esperados como evidencia."""

    id: str
    consulta: str
    norma: str
    clausula: str
    ambito: str
    documentos_esperados: list[str]   # nombres de archivo (coincidencia parcial)

    def coincide(self, documento: str) -> bool:
        """Compara por fragmentos normalizados (tolerante a variaciones)."""
        from mvp_sig.utils.text import normalizar

        d = normalizar(documento)
        for esperado in self.documentos_esperados:
            e = normalizar(esperado)
            if e == d or e in d or d in e:
                return True
            # Coincidencia por tokens significativos (>4 caracteres).
            tokens_e = _tokens_significativos(e)
            tokens_d = _tokens_significativos(d)
            if tokens_e and len(tokens_e & tokens_d) / len(tokens_e) >= 0.6:
                return True
        return False


# Casos derivados del corpus CIL ONG (nombres de archivo reales del corpus).
CASOS: list[CasoGold] = [
    CasoGold(
        id="G01",
        consulta="La organización debe documentar la información del sistema integrado de gestión y controlarla",
        norma="ISO9001",
        clausula="7.5",
        ambito="calidad",
        documentos_esperados=["Control de Documentos y Registros", "Listado Maestro de Documentos y Registros", "Listado Maestro de Informacion Documentada"],
    ),
    CasoGold(
        id="G02",
        consulta="Realizar revisiones por la dirección con información de entrada y salidas",
        norma="ISO9001",
        clausula="9.3",
        ambito="integral",
        documentos_esperados=["Revision por la Direccion", "Procedimiento para la Revision por la Gerencia", "Acta de Revision por la Direccion"],
    ),
    CasoGold(
        id="G03",
        consulta="Establecer y documentar el alcance del sistema integrado de gestión",
        norma="ISO9001",
        clausula="4.3",
        ambito="integral",
        documentos_esperados=["Alcance del Sistema Integrado de Gestion"],
    ),
    CasoGold(
        id="G04",
        consulta="Definir la política del sistema integrado de gestión y comunicarla",
        norma="ISO9001",
        clausula="5.2",
        ambito="integral",
        documentos_esperados=["Politica Integrada", "Acta_Socializacion de las Responsabilidades de la Alta Direccion"],
    ),
    CasoGold(
        id="G05",
        consulta="Gestionar las acciones correctivas y de mejora ante las no conformidades",
        norma="ISO9001",
        clausula="10.2",
        ambito="calidad",
        documentos_esperados=["Gestion de Acciones Correctivas y de Mejora", "Procedimiento de Acciones Correctivas y de Mejora"],
    ),
    CasoGold(
        id="G06",
        consulta="Planificar y ejecutar el programa de auditorías internas",
        norma="ISO9001",
        clausula="9.2",
        ambito="calidad",
        documentos_esperados=["Programa de Auditoria Interna", "Plan de Auditoria Interna", "Informe de Auditoria Interna Integral"],
    ),
    CasoGold(
        id="G07",
        consulta="Identificar peligros, evaluar riesgos y determinar controles operacionales",
        norma="ISO45001",
        clausula="6.1.2",
        ambito="seguridad",
        documentos_esperados=["Identificacion de Peligros, Evaluacion y Valoraci\u00f3n de Riesgos", "Matriz de Peligros", "Matriz IPEVREC"],
    ),
    CasoGold(
        id="G08",
        consulta="Establecer procesos para la preparación y respuesta a emergencias",
        norma="ISO45001",
        clausula="8.2",
        ambito="seguridad",
        documentos_esperados=["Plan de Contingencia", "Hoja de Control de Simulacros de Emergencias"],
    ),
    CasoGold(
        id="G09",
        consulta="Gestionar los riesgos y oportunidades del sistema integrado de gestión",
        norma="ISO9001",
        clausula="6.1",
        ambito="integral",
        documentos_esperados=["Matriz de Abordaje de Riesgos y Oportunidades", "Procedimiento Abordaje Riesgos y Oportunidades"],
    ),
    CasoGold(
        id="G10",
        consulta="Identificar aspectos e impactos ambientales y evaluarlos",
        norma="ISO14001",
        clausula="6.1.2",
        ambito="ambiente",
        documentos_esperados=["Identificaci\u00f3n de Aspectos y Valoraci\u00f3n de Impactos Ambientales", "Matriz de Aspectos e Impactos Ambientales"],
    ),
    CasoGold(
        id="G11",
        consulta="Gestionar integralmente los residuos peligrosos y no peligrosos",
        norma="ISO14001",
        clausula="8.1",
        ambito="ambiente",
        documentos_esperados=["Programa de Gesti\u00f3n Integral de Residuos"],
    ),
    CasoGold(
        id="G12",
        consulta="Establecer objetivos medibles del sistema integrado de gestión y su plan de cumplimiento",
        norma="ISO9001",
        clausula="6.2",
        ambito="integral",
        documentos_esperados=["Objetivos del Sistema Integrado de Gestion", "Plan de Cumplimiento de los Objetivos del SIG", "Plan Anual de Trabajo"],
    ),
    CasoGold(
        id="G13",
        consulta="Asegurar la competencia del personal y la formación en seguridad y salud en el trabajo",
        norma="ISO45001",
        clausula="7.2",
        ambito="seguridad",
        documentos_esperados=["Procedimiento de Capacitaci\u00f3n y Entrenamiento HSEQ", "Cronograma Anual de Capacitaciones", "Registro de Asistencia", "Evaluaci\u00f3n de la Inducci\u00f3n y Reinducci\u00f3n"],
    ),
    CasoGold(
        id="G14",
        consulta="Determinar y controlar los requisitos legales y otros requisitos aplicables",
        norma="ISO14001",
        clausula="6.1.3",
        ambito="integral",
        documentos_esperados=["Requisitos Legales y Aplicables", "Identificaci\u00f3n y Evaluaci\u00f3n de Requisitos Legales y Aplicables"],
    ),
    CasoGold(
        id="G15",
        consulta="Definir la estructura organizacional, responsabilidades y autoridades",
        norma="ISO9001",
        clausula="5.3",
        ambito="integral",
        documentos_esperados=["Organigrama", "Acta_Nombramiento del Responsable del SIG", "Perfil del Cargo"],
    ),
    CasoGold(
        id="G16",
        consulta="Planificar la gestión del cambio en el sistema integrado de gestión",
        norma="ISO9001",
        clausula="6.3",
        ambito="integral",
        documentos_esperados=["Gesti\u00f3n del Cambio", "Procedimiento de Gesti\u00f3n del Cambio"],
    ),
    CasoGold(
        id="G17",
        consulta="Adquirir y evaluar proveedores de bienes y servicios",
        norma="ISO9001",
        clausula="8.4",
        ambito="calidad",
        documentos_esperados=["Selecci\u00f3n de Proveedores", "Evaluaci\u00f3n-Reevaluaci\u00f3n de Proveedores", "Adquisici\u00f3n de bienes y servicios"],
    ),
    CasoGold(
        id="G18",
        consulta="Planificar y controlar el mantenimiento de la infraestructura y los equipos",
        norma="ISO45001",
        clausula="7.1.3",
        ambito="seguridad",
        documentos_esperados=["Programa de Mantenimiento"],
    ),
    CasoGold(
        id="G19",
        consulta="Controlar las operaciones de vigilancia, medición, análisis y mejora",
        norma="ISO9001",
        clausula="8.1",
        ambito="calidad",
        documentos_esperados=["Control de Documentos y Registros", "Programa de Inspecciones", "Inspecciones Gerenciales"],
    ),
    CasoGold(
        id="G20",
        consulta="Gestionar las consultas y participación de los trabajadores sobre salud y seguridad",
        norma="ISO45001",
        clausula="5.4",
        ambito="seguridad",
        documentos_esperados=["Procedimiento_Comunicaci\u00f3n, Participaci\u00f3n, Consulta y Motivaci\u00f3n de los Trabajadores"],
    ),
]


def casos_por_ambito(ambito: str) -> list[CasoGold]:
    return [c for c in CASOS if c.ambito == ambito]


def casos_por_norma(norma: str) -> list[CasoGold]:
    return [c for c in CASOS if c.norma == norma]
