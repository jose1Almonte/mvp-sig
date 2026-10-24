"""Motor de diagnóstico: el corazón del MVP.

Para cada requisito normativo:
    recuperar -> generar (LLM) -> verificar trazabilidad -> consolidar.

La verificación de trazabilidad es la aporte metodológico central: una cita
que el modelo dice haber encontrado pero que no existe en el fragmento
recuperado invalida el hallazgo y degrada el veredicto.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from mvp_sig.diagnosis.prompts import (
    construir_prompt_requisito,
    construir_prompt_sintesis,
    VERDICTOS,
)
from mvp_sig.ingestion.cleaner import pre_limpiar_cita
from mvp_sig.knowledge.requirements import Requisito
from mvp_sig.knowledge.vectorstore import VectorStore
from mvp_sig.llm.provider import LLMProvider
from mvp_sig.settings import RETRIEVAL
from mvp_sig.utils.text import contiene_frase, truncar

_RE_REF = re.compile(r"^[Ee](\d+)$")


@dataclass
class EvidenciaCitada:
    """Cita producida por el modelo, ya verificada contra el fragmento original."""

    ref: str
    fragmento_id: str
    documento: str
    pagina: int | None
    seccion: str
    cita: str
    verificada: bool
    puntaje: float
    motivo_fallo: str = ""

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "fragmento_id": self.fragmento_id,
            "documento": self.documento,
            "pagina": self.pagina,
            "seccion": self.seccion,
            "cita": self.cita,
            "verificada": self.verificada,
            "puntaje": round(self.puntaje, 4),
            "motivo_fallo": self.motivo_fallo,
        }


@dataclass
class ResultadoDiagnostico:
    """Diagnóstico de un requisito."""

    requisito_id: str
    norma: str
    clausula: str
    ambito: str
    requisito_texto: str
    veredicto: str
    confianza: float
    confianza_evidence: float
    justificacion: str
    evidencia: list[EvidenciaCitada] = field(default_factory=list)
    hallazgo: str = ""
    severidad: str = ""
    recomendacion: str = ""
    fragmentos_recuperados: list[str] = field(default_factory=list)
    mejor_puntaje: float = 0.0
    latencia_s: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    modelo: str = ""
    proveedor: str = ""
    error: str | None = None

    # -- derivados ------------------------------------------------------- #
    @property
    def traza_verificada(self) -> bool:
        """Hay al menos una cita comprobada contra el fragmento recuperado."""
        return any(e.verificada for e in self.evidencia)

    @property
    def cumple(self) -> bool:
        return self.veredicto in {"CUMPLE", "CUMPLE_PARCIAL"}

    def to_dict(self) -> dict:
        return {
            "requisito_id": self.requisito_id,
            "norma": self.norma,
            "clausula": self.clausula,
            "ambito": self.ambito,
            "requisito_texto": self.requisito_texto,
            "veredicto": self.veredicto,
            "confianza": round(self.confianza, 3),
            "confianza_evidence": round(self.confianza_evidence, 3),
            "justificacion": self.justificacion,
            "evidencias": [e.to_dict() for e in self.evidencia],
            "hallazgo": self.hallazgo,
            "severidad": self.severidad,
            "recomendacion": self.recomendacion,
            "fragmentos_recuperados": self.fragmentos_recuperados,
            "mejor_puntaje": round(self.mejor_puntaje, 4),
            "traza_verificada": self.traza_verificada,
            "latencia_s": round(self.latencia_s, 3),
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "costo_usd": round(self.costo_usd, 6),
            "modelo": self.modelo,
            "proveedor": self.proveedor,
            "error": self.error,
        }


@dataclass
class InformeDiagnostico:
    """Resultado consolidado de una corrida de diagnóstico."""

    generado: str
    proveedor: str
    modelo: str
    organizacion: str
    resultados: list[ResultadoDiagnostico] = field(default_factory=list)
    resumen_ejecutivo: str = ""
    advertencias: list[str] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generado": self.generado,
            "proveedor": self.proveedor,
            "modelo": self.modelo,
            "organizacion": self.organizacion,
            "resumen_ejecutivo": self.resumen_ejecutivo,
            "advertencias": self.advertencias,
            "metricas": self.metricas,
            "resultados": [r.to_dict() for r in self.resultados],
        }

    def guardar(self, ruta) -> None:
        from pathlib import Path

        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #
class MotorDiagnostico:
    """Orquesta el flujo de extremo a extremo para un conjunto de requisitos."""

    def __init__(
        self,
        store: VectorStore,
        llm: LLMProvider,
        *,
        top_k: int | None = None,
        score_min: float | None = None,
        organizacion: str = "Organización evaluada",
    ) -> None:
        self.store = store
        self.llm = llm
        self.top_k = top_k or RETRIEVAL.top_k
        self.score_min = RETRIEVAL.score_min if score_min is None else score_min
        self.organizacion = organizacion

    # -- recuperación ------------------------------------------------------ #
    def recuperar(self, requisito: Requisito) -> list[dict]:
        """Recupera evidencia del SIG para un requisito.

        Para cláusulas estructurales del SIG (4 a 10) la búsqueda es abierta,
        porque esos requisitos aplican transversalmente a las tres normas.
        """
        consulta = f"{requisito.norma} {requisito.clausula}. {requisito.texto}"
        ambitos = [requisito.ambito]
        transversal = requisito.metadatos.get("ambito_transversal", False)
        if transversal:
            ambitos = ["calidad", "ambiente", "seguridad", "integral"]

        from mvp_sig.knowledge.vectorstore import filtro_ambito

        frags = self.store.buscar(
            VectorStore.EVIDENCIAS,
            consulta,
            k=self.top_k,
            where=filtro_ambito(ambitos) if not transversal else None,
            score_min=self.score_min,
            ambitos_aceptados=set(ambitos) if transversal else None,
        )
        return [
            {
                "id": f.id,
                "texto": f.texto,
                "puntaje": f.puntaje,
                "metadatos": f.metadatos,
            }
            for f in frags
        ]

    # -- evaluación de un requisito ------------------------------------------ #
    def evaluar_requisito(self, requisito: Requisito, contexto_extra: str = "") -> ResultadoDiagnostico:
        evidencias = self.recuperar(requisito)
        # Se recortan las evidencias al presupuesto de contexto.
        contexto = "\n\n".join(e["texto"] for e in evidencias)[: RETRIEVAL.context_chars]

        prompt = construir_prompt_requisito(
            requisito_texto=requisito.texto,
            requisito_id=requisito.id,
            norma=requisito.norma,
            clausula=requisito.clausula,
            ambito=requisito.ambito,
            evidencias=evidencias,
            contexto_extra=contexto_extra,
        )

        respuesta = self.llm.chat(
            construir_sistema(),
            prompt,
            json_modo=True,
        )

        resultado = ResultadoDiagnostico(
            requisito_id=requisito.id,
            norma=requisito.norma,
            clausula=requisito.clausula,
            ambito=requisito.ambito,
            requisito_texto=requisito.texto,
            veredicto="NO_CUMPLE",
            confianza=0.0,
            confianza_evidence=0.0,
            justificacion="",
            fragmentos_recuperados=[e["id"] for e in evidencias],
            mejor_puntaje=max([e["puntaje"] for e in evidencias], default=0.0),
            latencia_s=respuesta.latencia_s,
            tokens_entrada=respuesta.tokens_entrada,
            tokens_salida=respuesta.tokens_salida,
            costo_usd=respuesta.costo_usd,
            modelo=respuesta.modelo,
            proveedor=respuesta.proveedor,
            error=respuesta.error,
        )

        if respuesta.error:
            resultado.justificacion = f"Error invoking the model: {respuesta.error}"
            return resultado

        datos = respuesta.json()
        if not isinstance(datos, dict):
            resultado.veredicto = "NO_CUMPLE"
            resultado.justificacion = (
                "The model did not return a parsable JSON object. Raw output: "
                + truncar(respuesta.texto, 400)
            )
            return resultado

        self._aplicar_datos(resultado, datos, evidencias)
        return resultado

    # -- post-proceso --------------------------------------------------------- #
    def _aplicar_datos(
        self,
        resultado: ResultadoDiagnostico,
        datos: dict,
        evidencias: list[dict],
    ) -> None:
        veredicto = str(datos.get("veredicto", "")).strip().upper()
        veredicto = veredicto.replace(" ", "_").replace("-", "_")
        if veredicto not in VERDICTOS:
            veredicto = "NO_CUMPLE"
        resultado.veredicto = veredicto
        resultado.confianza = _float(datos.get("confianza"), 0.0)
        resultado.confianza_evidence = _float(datos.get("confianza_evidence"), 0.0)
        resultado.justificacion = str(datos.get("justificacion", "")).strip()
        resultado.hallazgo = str(datos.get("hallazgo", "")).strip()
        resultado.severidad = str(datos.get("severidad", "")).strip().upper()
        resultado.recomendacion = str(datos.get("recomendacion", "")).strip()

        # --- verificación de trazabilidad --------------------------------- #
        por_ref = {f"E{i + 1}": e for i, e in enumerate(evidencias)}
        texto_por_id = {e["id"]: e["texto"] for e in evidencias}

        citas: list[EvidenciaCitada] = []
        for item in datos.get("evidencias") or []:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref", "")).strip()
            cita = pre_limpiar_cita(str(item.get("cita", "")))
            documento = str(item.get("documento", "")).strip()
            m = _RE_REF.match(ref)
            idx = int(m.group(1)) - 1 if m else None
            frag = evidencias[idx] if (idx is not None and 0 <= idx < len(evidencias)) else None

            if frag is None:
                citas.append(
                    EvidenciaCitada(
                        ref=ref,
                        fragmento_id="",
                        documento=documento,
                        pagina=None,
                        seccion="",
                        cita=cita,
                        verificada=False,
                        puntaje=0.0,
                        motivo_fallo="Referencia de evidencia inexistente en el conjunto recuperado.",
                    )
                )
                continue

            meta = frag["metadatos"]
            verificada = contiene_frase(texto_por_id[frag["id"]], cita)
            citas.append(
                EvidenciaCitada(
                    ref=ref or f"E{idx + 1}",
                    fragmento_id=frag["id"],
                    documento=meta.get("documento", documento),
                    pagina=_int(meta.get("pagina")),
                    seccion=meta.get("seccion", "") or "",
                    cita=cita,
                    verificada=verificada,
                    puntaje=frag["puntaje"],
                    motivo_fallo=""
                    if verificada
                    else "La cita declarada no aparece textualmente en el fragmento recuperado.",
                )
            )

        resultado.evidencia = citas

        # --- degradación por falta de trazabilidad ------------------------- #
        verificadas = [c for c in citas if c.verificada]
        if citas and not verificadas:
            # El modelo afirmó una evidencia que no existe: no se puede sostener
            # un veredicto de cumplimiento.
            if resultado.veredicto in {"CUMPLE", "CUMPLE_PARCIAL"}:
                resultado.veredicto = "CUMPLE_PARCIAL"
                resultado.confianza = min(resultado.confianza, 0.4)
                resultado.hallazgo = (
                    resultado.hallazgo
                    or "La evidencia declarada no pudo verificarse contra la documentación recuperada."
                )
            resultado.justificacion += (
                " [Nota de trazabilidad: ninguna de las citas declaradas se verificó "
                "contra el fragmento recuperado.]"
            )
        elif not citas and resultado.veredicto == "CUMPLE":
            resultado.veredicto = "NO_CUMPLE"
            resultado.confianza = min(resultado.confianza, 0.4)
            resultado.hallazgo = (
                resultado.hallazgo
                or "No se identificó evidencia documental que sustente el cumplimiento."
            )

    # -- corrida completa ------------------------------------------------------ #
    def diagnosticar(
        self,
        requisitos: list[Requisito],
        *,
        contexto_extra: str = "",
        con_resumen: bool = True,
        progreso=None,
    ) -> InformeDiagnostico:
        informe = InformeDiagnostico(
            generado=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            proveedor=self.llm.nombre,
            modelo=self.llm.modelo,
            organizacion=self.organizacion,
        )
        total = len(requisitos)
        for i, req in enumerate(requisitos, start=1):
            res = self.evaluar_requisito(req, contexto_extra=contexto_extra)
            informe.resultados.append(res)
            if progreso:
                progreso(i, total, res)
            else:
                marca = {
                    "CUMPLE": "OK",
                    "CUMPLE_PARCIAL": "PARCIAL",
                    "NO_CUMPLE": "NO CUMPLE",
                    "NO_APLICA": "N/A",
                }.get(res.veredicto, "?")
                print(
                    f"  [{i:>3}/{total}] {req.id:<22} {marca:<10} "
                    f"evid={len(res.evidencia)} traza={'S' if res.traza_verificada else 'N'} "
                    f"({res.latencia_s:.1f}s)",
                    flush=True,
                )
            if res.error:
                informe.advertencias.append(f"{res.requisito_id}: {res.error}")

        informe.metricas = calcular_metricas(informe.resultados)
        if con_resumen and informe.resultados:
            informe.resumen_ejecutivo = self.generar_resumen(informe.resultados)
        return informe

    def generar_resumen(self, resultados: list[ResultadoDiagnostico]) -> str:
        prompt = construir_prompt_sintesis([r.to_dict() for r in resultados])
        respuesta = self.llm.chat(
            "Eres un jefe de auditoría interna. Escribes en español, con markdown y tono técnico.",
            prompt,
        )
        if respuesta.ok:
            return respuesta.texto
        return (
            "No se pudo generar el resumen ejecutivo "
            f"({respuesta.error or 'respuesta vacía'}). "
            "Consulte la matriz de trazabilidad para el detalle."
        )


def construir_sistema() -> str:
    from mvp_sig.diagnosis.prompts import SISTEMA_AUDITOR

    return SISTEMA_AUDITOR


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def calcular_metricas(resultados: list[ResultadoDiagnostico]) -> dict:
    """Métricas agregadas del diagnóstico (base para la fase de evaluación)."""
    if not resultados:
        return {}
    n = len(resultados)
    por_veredicto: dict[str, int] = {v: 0 for v in VERDICTOS}
    por_norma: dict[str, dict] = {}
    por_ambito: dict[str, dict] = {}
    verificables = 0
    con_evidencia = 0
    latencias: list[float] = []
    tokens_in = 0
    tokens_out = 0
    errores = 0

    for r in resultados:
        por_veredicto[r.veredicto] = por_veredicto.get(r.veredicto, 0) + 1
        for bucket, key in ((por_norma, r.norma), (por_ambito, r.ambito)):
            d = bucket.setdefault(key, {"total": 0, "cumple": 0, "parcial": 0, "no_cumple": 0, "na": 0})
            d["total"] += 1
            if r.veredicto == "CUMPLE":
                d["cumple"] += 1
            elif r.veredicto == "CUMPLE_PARCIAL":
                d["parcial"] += 1
            elif r.veredicto == "NO_CUMPLE":
                d["no_cumple"] += 1
            else:
                d["na"] += 1
        if r.traza_verificada:
            verificables += 1
        if r.evidencia:
            con_evidencia += 1
        latencias.append(r.latencia_s)
        tokens_in += r.tokens_entrada
        tokens_out += r.tokens_salida
        if r.error:
            errores += 1

    conformes = por_veredicto.get("CUMPLE", 0) + por_veredicto.get("CUMPLE_PARCIAL", 0)
    evaluables = n - por_veredicto.get("NO_APLICA", 0)
    return {
        "requisitos_evaluados": n,
        "evaluables": evaluables,
        "distribucion_veredictos": por_veredicto,
        "tasa_cumplimiento": round(conformes / n, 4),
        "tasa_cumplimiento_sobre_evaluables": round(conformes / evaluables, 4) if evaluables else 0.0,
        "tasa_no_cumplimiento": round(por_veredicto.get("NO_CUMPLE", 0) / n, 4),
        "tasa_trazabilidad_verificada": round(verificables / n, 4),
        "requisitos_con_evidencia_citada": con_evidencia,
        "por_norma": por_norma,
        "por_ambito": por_ambito,
        "latencia_media_s": round(sum(latencias) / n, 3) if latencias else 0.0,
        "latencia_total_s": round(sum(latencias), 3),
        "tokens_entrada": tokens_in,
        "tokens_salida": tokens_out,
        "errores": errores,
    }


def _float(valor, defecto: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(valor)))
    except (TypeError, ValueError):
        return defecto


def _int(valor) -> int | None:
    try:
        v = int(valor)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
