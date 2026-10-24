"""Integración con el orquestador n8n.

El anteproyecto define el flujo de trabajo como *"gestionado mediante un
orquestador (ej. n8n) para validar la arquitectura"* y la fase 3.4.b pide
integrar el módulo de diagnóstico *"con el resto de la lógica del flujo
mediante una plataforma de automatización (n8n o similar)"*.

Este módulo materializa esa integración en los dos sentidos:

* **n8n conduce el flujo**: el flujo exportable de `workflows/` recibe un
  webhook, invoca la API del MVP (`POST /diagnostico`) y reparte el resultado
  según el veredicto.  El MVP no necesita saber nada de n8n para eso.
* **el MVP notifica a n8n**: al terminar una corrida, el orquestador puede
  publicar el informe en el webhook configurado en ``N8N_WEBHOOK`` para
  encadenar pasos posteriores (correo, ticket, tablero, recálculo de KPI).

La notificación es **opcional y no fatal**: si el webhook no está definido o
no responde, el diagnóstico se conserva íntegro y sólo se registra un aviso.
Un fallo de la orquestación nunca debe invalidar el resultado del análisis.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvp_sig.settings import PIPELINE

# Fichero del flujo exportable (se importa desde la interfaz de n8n).
RUTA_FLUJO = Path(__file__).resolve().parent.parent.parent / "workflows" / "diagnostico_sig_n8n.json"


@dataclass
class ResultadoNotificacion:
    """Resultado de intentar publicar un informe en el webhook de n8n."""

    enviado: bool
    url: str
    codigo: int | None = None
    detalle: str = ""

    def to_dict(self) -> dict:
        return {
            "enviado": self.enviado,
            "url": self.url,
            "codigo": self.codigo,
            "detalle": self.detalle,
        }


def webhook_configurado(url: str | None = None) -> bool:
    """True si hay un webhook de n8n definido."""
    destino = (url if url is not None else PIPELINE.n8n_webhook).strip()
    return bool(destino)


def payload_diagnostico(informe: Any, *, resumen: bool = True) -> dict:
    """Construye el cuerpo que se publica en el webhook de n8n.

    Se envía el informe completo (veredicto, evidencia citada y trazabilidad)
    más un bloque resumen con los agregados que un orquestador necesita para
    decidir a dónde enrutar la corrida.
    """
    datos = informe.to_dict() if hasattr(informe, "to_dict") else dict(informe)
    resultados = datos.get("resultados", [])

    conteo: dict[str, int] = {}
    for r in resultados:
        v = str(r.get("veredicto", "DESCONOCIDO"))
        conteo[v] = conteo.get(v, 0) + 1

    verificadas = sum(1 for r in resultados if r.get("traza_verificada"))
    bloque = {
        "organizacion": datos.get("organizacion", ""),
        "generado": datos.get("generado", ""),
        "proveedor": datos.get("proveedor", ""),
        "modelo": datos.get("modelo", ""),
        "total_requisitos": len(resultados),
        "veredictos": conteo,
        "trazabilidad_verificada_pct": (
            round(100.0 * verificadas / len(resultados), 2) if resultados else 0.0
        ),
        "metricas": datos.get("metricas", {}),
    }
    if resumen:
        bloque["resumen_ejecutivo"] = datos.get("resumen_ejecutivo", "")
    return {"evento": "diagnostico.sig", "resumen": bloque, "informe": datos}


def notificar(
    informe: Any,
    url: str | None = None,
    *,
    timeout: int = 15,
    resumen: bool = True,
) -> ResultadoNotificacion:
    """Publica el informe en el webhook de n8n.

    Nunca propaga la excepción: un orquestador caído se traduce en un aviso,
    no en la pérdida del diagnóstico.
    """
    destino = (url if url is not None else PIPELINE.n8n_webhook).strip()
    if not destino:
        return ResultadoNotificacion(
            False, "", None, "No hay webhook configurado (N8N_WEBHOOK)."
        )

    cuerpo = payload_diagnostico(informe, resumen=resumen)
    try:
        import requests

        resp = requests.post(
            destino,
            json=cuerpo,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        ok = 200 <= resp.status_code < 300
        return ResultadoNotificacion(
            ok,
            destino,
            resp.status_code,
            "Publicado" if ok else f"El webhook respondió {resp.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        return ResultadoNotificacion(False, destino, None, f"No se pudo publicar: {exc}")


def ruta_flujo() -> Path:
    """Ruta del flujo exportable de n8n."""
    return RUTA_FLUJO


def validar_flujo() -> dict:
    """Comprueba que el flujo exportable existe y es un JSON importable."""
    if not RUTA_FLUJO.exists():
        return {"ok": False, "detalle": f"No existe {RUTA_FLUJO}"}
    try:
        datos = json.loads(RUTA_FLUJO.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "detalle": f"JSON inválido: {exc}"}
    nodos = datos.get("nodes") or []
    conexiones = datos.get("connections") or {}
    if not nodos:
        return {"ok": False, "detalle": "El flujo no define nodos"}
    return {
        "ok": True,
        "detalle": f"{len(nodos)} nodos, {len(conexiones)} conexiones",
        "nodos": [n.get("name") for n in nodos],
    }
