"""API REST del MVP de diagnóstico de SIG (FastAPI).

Ejecución:  uvicorn mvp_sig.api.main:app --reload --port 8000
Documentación: http://localhost:8000/docs
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from mvp_sig.api.schemas import (
    BenchmarkRequest,
    DiagnosticoRequest,
    DiagnosticoResponse,
    EstadoResponse,
    EvidenciaRequest,
    ExclusionRequest,
    IngestaRequest,
    MetadatosRequest,
)
from mvp_sig.diagnosis.traceability import exportar_csv, exportar_html, exportar_json
from mvp_sig.evaluation.benchmark import (
    exportar_benchmark_csv,
    exportar_benchmark_markdown,
    ejecutar_benchmark,
)
from mvp_sig.evaluation.metrics import comparar_modelos, evaluar_diagnostico, evaluar_recuperacion
from mvp_sig.llm.provider import proveedores_disponibles
from mvp_sig.pipeline import Pipeline
from mvp_sig.settings import CORPUS_EVIDENCIAS, NORMAS, PATHS

app = FastAPI(
    title="MVP · Diagnóstico inteligente de Sistemas Integrados de Gestión",
    description=(
        "Sistema de diagnóstico de cumplimiento normativo ISO 9001 / 14001 / 45001 "
        "basado en IA generativa y arquitectura RAG, con trazabilidad "
        "requisito-evidencia verificada."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instancia perezosa del pipeline (evita cargar el modelo al importar).
_PIPELINE: Pipeline | None = None
_ULTIMO_INFORME = None


def get_pipeline() -> Pipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = Pipeline()
    return _PIPELINE


# --------------------------------------------------------------------------- #
# Salud y estado
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["sistema"])
def health() -> dict:
    return {
        "estado": "ok",
        "momento": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


@app.get("/estado", response_model=EstadoResponse, tags=["sistema"])
def estado() -> dict:
    return get_pipeline().estado()


@app.get("/proveedores", tags=["sistema"])
def proveedores() -> list[dict]:
    """Inventario de motores de lenguaje y su disponibilidad real."""
    return proveedores_disponibles()


@app.get("/normas", tags=["sistema"])
def normas() -> list[dict]:
    return [
        {
            "key": n.key,
            "nombre": n.nombre_archivo,
            "ambito": n.ambito,
            "color": n.color,
        }
        for n in NORMAS.values()
    ]


# --------------------------------------------------------------------------- #
# Corpus y requisitos
# --------------------------------------------------------------------------- #
@app.get("/catalogo", tags=["corpus"])
def catalogo() -> dict:
    """Catálogo documental de las evidencias indexadas."""
    return get_pipeline().cargar_catalogo()


@app.get("/requisitos", tags=["corpus"])
def requisitos(
    norma: str | None = Query(default=None),
    ambito: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Requisitos normativos disponibles para el diagnóstico."""
    pipeline = get_pipeline()
    todos = pipeline.cargar_requisitos([norma] if norma else None)
    if ambito:
        todos = [r for r in todos if r.ambito == ambito]
    ventana = todos[offset : offset + limite]
    return {
        "total": len(todos),
        "offset": offset,
        "requisitos": [r.to_dict() for r in ventana],
    }


# --------------------------------------------------------------------------- #
# Ingesta
# --------------------------------------------------------------------------- #
@app.post("/ingesta", tags=["corpus"])
def ingesta(req: IngestaRequest) -> dict:
    """Procesa e indexa el corpus documental de evidencias."""
    pipeline = get_pipeline()
    raiz = req.raiz or str(CORPUS_EVIDENCIAS)
    if not Path(raiz).exists():
        raise HTTPException(status_code=400, detail=f"Ruta inexistente: {raiz}")
    try:
        resultado = pipeline.ingerir(
            raiz,
            extensiones=tuple(req.extensiones),
            limite=req.limite,
        )
        if req.reindexar_requisitos:
            pipeline.indexar_requisitos()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return resultado.to_dict()


# --------------------------------------------------------------------------- #
# Inventario y edición de evidencias (corpus + manual)
# --------------------------------------------------------------------------- #
@app.get("/evidencias", tags=["evidencia"])
def listar_evidencias(
    origen: str = Query("todos", description="todos | corpus | manual"),
    q: str = Query("", description="Texto libre sobre el nombre del documento"),
    incluir_excluidas: bool = Query(True, description="Mostrar las retiradas del diagnóstico"),
) -> dict:
    """Inventario de evidencias indexadas.

    Devuelve el corpus completo junto con la evidencia registrada a mano, con
    sus metadatos de clasificación.  Es la vista que consume la interfaz para
    corregir la clasificación de un documento sin rehacer la ingesta.
    """
    pipeline = get_pipeline()
    filas = pipeline.inventario()

    if origen != "todos":
        filas = [f for f in filas if f["origen"] == origen]
    if not incluir_excluidas:
        filas = [f for f in filas if not f["excluido"]]
    if q:
        texto = q.strip().lower()
        filas = [
            f
            for f in filas
            if texto in str(f["documento"]).lower()
            or texto in str(f["codigo"]).lower()
            or texto in str(f["organizacion"]).lower()
        ]

    resumen = {
        "total": len(filas),
        "corpus": sum(1 for f in filas if f["origen"] == "corpus"),
        "manual": sum(1 for f in filas if f["origen"] == "manual"),
        "excluidas": sum(1 for f in filas if f["excluido"]),
        "chunks": sum(int(f["chunks"]) for f in filas),
    }
    return {"total": len(filas), "resumen": resumen, "evidencias": filas}


@app.get("/evidencias/manuales", tags=["evidencia"])
def listar_evidencias_manuales() -> dict:
    """Lista sólo la evidencia registrada manualmente."""
    from mvp_sig.ingestion import manual

    pipeline = get_pipeline()
    registros = manual.listar_manuales(pipeline)
    return {"total": len(registros), "evidencias": registros}


@app.post("/evidencias", tags=["evidencia"])
def registrar_evidencia(req: EvidenciaRequest) -> dict:
    """Registra como evidencia un texto pegado.

    El texto se materializa como archivo en `data/evidencias_manuales/` y se
    indexa de forma incremental, sin reindexar el corpus.
    """
    from mvp_sig.ingestion import manual

    pipeline = get_pipeline()
    resultado = manual.registrar_texto(
        pipeline,
        req.texto,
        req.nombre or "",
        ambitos=req.ambitos or None,
        ambito_principal=req.ambito_principal,
        tipo_documento=req.tipo_documento,
        organizacion=req.organizacion,
        codigo=req.codigo,
    )
    if not resultado.ok:
        raise HTTPException(status_code=400, detail=resultado.mensaje)
    return resultado.to_dict()


@app.post("/evidencias/archivo", tags=["evidencia"])
def registrar_evidencia_archivo(
    archivo: UploadFile = File(...),
    nombre: str = Form(""),
    ambitos: str = Form(""),
    tipo_documento: str = Form(""),
    organizacion: str = Form(""),
    codigo: str = Form(""),
) -> dict:
    """Registra como evidencia un archivo suelto (PDF/DOCX/XLSX/XLS/TXT)."""
    from mvp_sig.ingestion import manual

    contenido = archivo.file.read()
    if len(contenido) > manual.MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {manual.MAX_BYTES // (1024 * 1024)} MB.",
        )

    pipeline = get_pipeline()
    resultado = manual.registrar_archivo(
        pipeline,
        contenido,
        nombre or archivo.filename or "",
        ambitos=[a.strip() for a in ambitos.split(",") if a.strip()] or None,
        tipo_documento=tipo_documento or None,
        organizacion=organizacion or None,
        codigo=codigo or None,
        extension=Path(archivo.filename or "").suffix,
    )
    if not resultado.ok:
        raise HTTPException(status_code=400, detail=resultado.mensaje)
    return resultado.to_dict()


@app.put("/evidencias/{documento}", tags=["evidencia"])
def actualizar_evidencia(documento: str, req: MetadatosRequest) -> dict:
    """Corrige la clasificación de un documento y lo reindexa.

    Acepta el `id` corto, la `clave` o el nombre del documento.  Los campos no
    indicados conservan su valor actual.
    """
    pipeline = get_pipeline()
    resultado = pipeline.actualizar_metadatos(
        documento,
        ambitos=req.ambitos,
        ambito_principal=req.ambito_principal,
        tipo_documento=req.tipo_documento,
        organizacion=req.organizacion,
        codigo=req.codigo,
    )
    if not resultado.get("ok"):
        raise HTTPException(status_code=404, detail=resultado.get("motivo", "No se pudo actualizar."))
    return resultado


@app.post("/evidencias/{documento}/reindexar", tags=["evidencia"])
def reindexar_evidencia(documento: str) -> dict:
    """Reindexa un documento desde su archivo conservando sus metadatos."""
    pipeline = get_pipeline()
    resultado = pipeline.reindexar_documento(documento)
    if not resultado.get("ok"):
        raise HTTPException(status_code=404, detail=resultado.get("motivo", "No se pudo reindexar."))
    return resultado


@app.post("/evidencias/{documento}/excluir", tags=["evidencia"])
def excluir_evidencia(documento: str, req: ExclusionRequest) -> dict:
    """Retira un documento del diagnóstico sin borrar su archivo.

    La exclusión persiste: la ingesta completa la respeta.
    """
    pipeline = get_pipeline()
    resultado = pipeline.excluir_evidencia(documento, motivo=req.motivo)
    if not resultado.get("ok"):
        raise HTTPException(status_code=404, detail=resultado.get("motivo", "No se pudo excluir."))
    return resultado


@app.post("/evidencias/{documento}/reincorporar", tags=["evidencia"])
def reincorporar_evidencia(documento: str) -> dict:
    """Devuelve al diagnóstico un documento previamente excluido."""
    pipeline = get_pipeline()
    resultado = pipeline.reincorporar_evidencia(documento)
    if not resultado.get("ok"):
        raise HTTPException(status_code=404, detail=resultado.get("motivo", "No se pudo reincorporar."))
    return resultado


@app.delete("/evidencias/{documento}", tags=["evidencia"])
def eliminar_evidencia(documento: str) -> dict:
    """Da de baja una evidencia manual: borra sus fragmentos, catálogo y archivo."""
    pipeline = get_pipeline()
    resultado = pipeline.eliminar_evidencia(documento)
    if not resultado.get("ok"):
        raise HTTPException(status_code=404, detail=resultado.get("motivo", "No se pudo eliminar."))
    return resultado


# --------------------------------------------------------------------------- #
# Diagnóstico
# --------------------------------------------------------------------------- #
@app.post("/diagnostico", response_model=DiagnosticoResponse, tags=["diagnostico"])
def diagnostico(req: DiagnosticoRequest) -> dict:
    """Ejecuta el diagnóstico de cumplimiento normativo."""
    global _ULTIMO_INFORME
    pipeline = get_pipeline()
    try:
        informe = pipeline.diagnosticar(
            normas=req.normas,
            ambitos=req.ambitos,
            clausulas=req.clausulas,
            limite=req.limite,
            top_k=req.top_k,
            organizacion=req.organizacion,
            contexto_extra=req.contexto_extra,
            con_resumen=req.con_resumen,
            proveedor=req.proveedor,
            modelo=req.modelo,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _ULTIMO_INFORME = informe
    return informe.to_dict()


@app.get("/diagnostico/ultimo", tags=["diagnostico"])
def ultimo_diagnostico() -> dict:
    if _ULTIMO_INFORME is None:
        raise HTTPException(status_code=404, detail="Todavía no hay ningún diagnóstico en memoria")
    return _ULTIMO_INFORME.to_dict()


@app.get("/diagnostico/matriz.csv", tags=["diagnostico"])
def matriz_csv():
    """Matriz de trazabilidad requisito-evidencia en CSV."""
    if _ULTIMO_INFORME is None:
        raise HTTPException(status_code=404, detail="Ejecuta primero un diagnóstico")
    ruta = PATHS.reports / "matriz_trazabilidad.csv"
    exportar_csv(_ULTIMO_INFORME, ruta)
    return FileResponse(ruta, media_type="text/csv", filename="matriz_trazabilidad.csv")


@app.get("/diagnostico/informe.html", response_class=HTMLResponse, tags=["diagnostico"])
def informe_html():
    """Informe HTML autocontenido del último diagnóstico."""
    if _ULTIMO_INFORME is None:
        raise HTTPException(status_code=404, detail="Ejecuta primero un diagnóstico")
    ruta = PATHS.reports / "informe_diagnostico.html"
    exportar_html(_ULTIMO_INFORME, ruta)
    return HTMLResponse(ruta.read_text(encoding="utf-8"))


@app.get("/diagnostico/informe.json", tags=["diagnostico"])
def informe_json():
    if _ULTIMO_INFORME is None:
        raise HTTPException(status_code=404, detail="Ejecuta primero un diagnóstico")
    ruta = PATHS.reports / "informe_diagnostico.json"
    exportar_json(_ULTIMO_INFORME, ruta)
    return FileResponse(ruta, media_type="application/json", filename="informe_diagnostico.json")


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
@app.get("/kpis", tags=["indicadores"])
def kpis(con_normativos: bool = True) -> dict:
    """Matriz de indicadores clave de desempeño por ámbito del SIG."""
    pipeline = get_pipeline()
    lista, analisis = pipeline.matriz_kpis(con_normativos=con_normativos)
    return {"kpis": [k.to_dict() for k in lista], "analisis": analisis}


# --------------------------------------------------------------------------- #
# Evaluación
# --------------------------------------------------------------------------- #
@app.get("/metricas/recuperacion", tags=["evaluacion"])
def metricas_recuperacion(k: int = Query(default=5, ge=1, le=20)) -> dict:
    """Precisión, recall, MRR y nDCG de la recuperación semántica."""
    return evaluar_recuperacion(get_pipeline().store, k=k)


@app.get("/metricas/diagnostico", tags=["evaluacion"])
def metricas_diagnostico() -> dict:
    if _ULTIMO_INFORME is None:
        raise HTTPException(status_code=404, detail="Ejecuta primero un diagnóstico")
    return evaluar_diagnostico(_ULTIMO_INFORME.resultados)


@app.post("/benchmark", tags=["evaluacion"])
def benchmark(req: BenchmarkRequest) -> dict:
    """Compara varios modelos de lenguaje sobre los mismos requisitos."""
    pipeline = get_pipeline()
    requisitos = pipeline.cargar_requisitos(req.normas)
    if not requisitos:
        raise HTTPException(status_code=400, detail="No hay requisitos indexados")
    # Se toma una muestra representativa: primer requisito de cada cláusula.
    vistos: set[str] = set()
    muestra = []
    for r in requisitos:
        if r.clausula in vistos:
            continue
        vistos.add(r.clausula)
        muestra.append(r)
        if len(muestra) >= req.limite_requisitos:
            break
    modelos = [(m["proveedor"], m["modelo"]) for m in (req.modelos or [])] or None
    corridas = ejecutar_benchmark(pipeline.store, muestra, modelos, top_k=req.top_k)

    rutas = {
        "csv": str(exportar_benchmark_csv(corridas, PATHS.reports / "benchmark.csv")),
        "markdown": str(exportar_benchmark_markdown(corridas, PATHS.reports / "benchmark.md")),
    }
    comparacion = comparar_modelos({c.etiqueta: c.resultados for c in corridas if c.resultados})
    return {
        "rutas": rutas,
        "comparacion": comparacion,
        "carridas": [c.resumen() for c in corridas],
    }


@app.get("/docs-json", tags=["sistema"])
def docs_json() -> dict:
    return {"rutas": [r.path for r in app.routes if hasattr(r, "path")]}
