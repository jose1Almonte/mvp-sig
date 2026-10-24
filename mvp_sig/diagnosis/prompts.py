"""Ingeniería de prompts para el diagnóstico normativo.

El prompt fuerza tres cosas que la tesis necesita:
  1. que el veredicto se base **sólo** en la evidencia entregada;
  2. que cada afirmación cite el fragmento que la respalda;
  3. que la salida sea JSON estructurado y parseable.
"""
from __future__ import annotations

from mvp_sig.utils.text import truncar

SISTEMA_AUDITOR = (
    "Eres un auditor interno experto en Sistemas Integrados de Gestión (SIG) "
    "bajo las normas ISO 9001:2015, ISO 14001:2015 e ISO 45001:2018. "
    "Evalúas el cumplimiento normativo a partir de la documentación de la organización. "
    "Reglas innegociables:\n"
    "1) Basa el veredicto EXCLUSIVAMENTE en los fragmentos de evidencia proporcionados. "
    "Si la evidencia es insuficiente, el veredicto debe ser 'NO_APLICA' o 'NO_CUMPLE' según corresponda, "
    "nunca debes inventar información.\n"
    "2) Toda cita debe ser un fragmento textual LITERAL de la evidencia recibida, "
    "con el identificador del fragmento (E1, E2, ...).\n"
    "3) Respondes SIEMPRE en español y con un objeto JSON válido, sin texto adicional."
)

VERDICTOS = ("CUMPLE", "CUMPLE_PARCIAL", "NO_CUMPLE", "NO_APLICA")
SEVERIDADES = ("BAJA", "MEDIA", "ALTA", "CRITICA")


def construir_prompt_requisito(
    requisito_texto: str,
    requisito_id: str,
    norma: str,
    clausula: str,
    ambito: str,
    evidencias: list[dict],
    contexto_extra: str = "",
) -> str:
    """Arma el prompt de evaluación de un requisito contra sus evidencias."""
    bloques = []
    for i, ev in enumerate(evidencias, start=1):
        ref = f"E{i}"
        meta = ev.get("metadatos", {})
        origen = meta.get("documento", "?")
        pagina = meta.get("pagina")
        seccion = meta.get("seccion") or ""
        ubic = f"{origen}"
        if pagina and int(pagina) > 0:
            ubic += f", pág. {pagina}"
        if seccion:
            ubic += f" — {seccion}"
        bloques.append(
            f"[{ref}] Fuente: {ubic}\n"
            f"Similitud: {ev.get('puntaje', 0):.3f}\n"
            f"Contenido:\n{ev['texto']}\n"
        )

    if not bloques:
        bloques.append(
            "[—] No se recuperó ninguna evidencia documental para este requisito.\n"
        )

    extra = f"\nCONTEXTO ADICIONAL DEL CASO:\n{contexto_extra}\n" if contexto_extra else ""

    return f"""DISEÑA EL DIAGNÓSTICO DE UN REQUISITO NORMATIVO

REQUISITO A EVALUAR
- Identificador: {requisito_id}
- Norma: {norma}
- Cláusula: {clausula}
- Ámbito del SIG: {ambito}
- Texto del requisito: "{requisito_texto}"
{extra}
EVIDENCIA DOCUMENTAL RECUPERADA
{chr(10).join(bloques)}
INSTRUCCIONES
1. Decide el grado de cumplimiento del requisito usando EXCLUSIVAMENTE estos cuatro valores:
   - "CUMPLE": la evidencia demuestra íntegramente el requisito.
   - "CUMPLE_PARCIAL": la evidencia cubre sólo parte del requisito.
   - "NO_CUMPLE": existe evidencia que contradice el requisito, o la evidencia
     es claramente insuficiente para demostrar su cumplimiento.
   - "NO_APLICA": el requisito no aplica a esta organización según la evidencia.
2. "confianza": número entre 0 y 1 que expresa tu certeza sobre el veredicto.
3. "evidencias": lista de objetos con el identificador del fragmento que sustenta
   el veredicto ("ref": "E1"), el documento y el texto citado de forma literal.
   Si no hay evidencia, devuelve una lista vacía.
4. "hallazgo": descripción objetiva de la brecha detectada (cadena vacía si cumple).
5. "severidad": "BAJA", "MEDIA", "ALTA" o "CRITICA" (vacía si cumple o no aplica).
6. "recomendacion": acción correctiva concreta sugerida (cadena vacía si cumple o no aplica).
7. "confianza_evidence": entre 0 y 1, indica qué tan claramente la evidencia citada
   sustenta tu veredicto.

Responde con este JSON exacto y nada más:
{{
  "requisito_id": "{requisito_id}",
  "veredicto": "CUMPLE|CUMPLE_PARCIAL|NO_CUMPLE|NO_APLICA",
  "confianza": 0.0,
  "confianza_evidence": 0.0,
  "justificacion": "explicación de 2-4 frases",
  "evidencias": [
    {{"ref": "E1", "documento": "nombre del documento", "cita": "texto literal"}}
  ],
  "hallazgo": "",
  "severidad": "",
  "recomendacion": ""
}}"""


def construir_prompt_sintesis(diagnostico: list[dict]) -> str:
    """Prompt para el resumen ejecutivo del diagnóstico."""
    filas = []
    for d in diagnostico:
        filas.append(
            f"- [{d['requisito_id']}] {d['norma']} cl.{d['clausula']} ({d['ambito']}): "
            f"veredicto={d['veredicto']} (confianza {d.get('confianza', 0):.2f})"
            + (f" | hallazgo: {d['hallazgo']}" if d.get("hallazgo") else "")
        )
    return f"""Actúa como jefe de Auditoría Interna de un Sistema Integrado de Gestión.
Redacta el RESUMEN EJECUTIVO del diagnóstico de cumplimiento normativo siguiente.

RESULTADOS DEL DIAGNÓSTICO
{chr(10).join(filas)}

Estructura tu respuesta en markdown con estas secciones:
1. **Panorama general** (2-3 frases): estado del SIG por norma y ámbito.
2. **Brechas críticas**: los 3 hallazgos más relevantes, con la cláusula afectada.
3. **Riesgo de no conformidad**: qué ISO 9001/14001/45001 se ve más expuesta y por qué.
4. **Plan de acción priorizado**: 5 acciones concretas y priorizadas.

No inventes hallazgos que no estén en la lista."""


def construir_prompt_kpi(requisito_texto: str, norma: str, clausula: str) -> str:
    """Prompt para derivar indicadores de desempeño a partir de un requisito."""
    return f"""Deriva indicadores clave de desempeño (KPI) a partir de este requisito normativo.

Norma: {norma}
Cláusula: {clausula}
Requisito: "{requisito_texto}"

Responde con este JSON exacto:
{{
  "nombre": "nombre corto del indicador",
  "formula": "expresión de cálculo del KPI",
  "unidad": "% | conteo | horas | días | ratio",
  "frecuencia": "mensual | trimestral | anual",
  "meta_sugerida": "valor o rango orientativo",
  "ambito": "calidad | ambiente | seguridad"
}}
Si el requisito no implica un indicador medible, devuelve {{"nombre": null}}."""
