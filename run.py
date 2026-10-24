"""Interfaz de línea de comandos del MVP.

    python run.py estado
    python run.py ingesta --limite 20
    python run.py diagnostico --limite 10 --normas ISO9001
    python run.py matriz
    python run.py kpis
    python run.py metricas
    python run.py benchmark --modelos ollama/llama3.1:8b,ollama/llama3.2:3b
    python run.py n8n
    python run.py api
    python run.py ui
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvp_sig.diagnosis.traceability import exportar_todo
from mvp_sig.evaluation.benchmark import (
    exportar_benchmark_csv,
    exportar_benchmark_markdown,
    exportar_benchmark_json,
    ejecutar_benchmark,
)
from mvp_sig.evaluation.metrics import evaluar_recuperacion
from mvp_sig.pipeline import Pipeline
from mvp_sig.settings import CORPUS_EVIDENCIAS, PATHS, PIPELINE


def _titulo(txt: str) -> None:
    print("\n" + "=" * 72)
    print(txt)
    print("=" * 72)


def cmd_estado(args) -> None:
    _titulo("Estado del sistema")
    pipeline = Pipeline()
    print(json.dumps(pipeline.estado(), ensure_ascii=False, indent=2))


def cmd_ingesta(args) -> None:
    _titulo("Ingesta e indexación de evidencias")
    pipeline = Pipeline()
    resultado = pipeline.ingerir(
        args.ruta or str(CORPUS_EVIDENCIAS),
        extensiones=tuple(args.extensiones),
        limite=args.limite,
    )
    print(f"\nDocumentos indexados : {resultado.documentos_ok}")
    print(f"Documentos con error : {resultado.documentos_fallidos}")
    print(f"Fragmentos generados : {resultado.chunks}")
    print(f"Tiempo total         : {resultado.segundos:.1f} s")
    if args.indexar_requisitos:
        requisitos = pipeline.indexar_requisitos()
        print(f"Requisitos indexados : {len(requisitos)}")
    for adv in resultado.advertencias[:20]:
        print(f"  [aviso] {adv}")


def cmd_diagnostico(args) -> None:
    _titulo("Diagnóstico de cumplimiento normativo")
    pipeline = Pipeline()
    informe = pipeline.diagnosticar(
        normas=args.normas or None,
        ambitos=args.ambitos or None,
        limite=args.limite,
        top_k=args.top_k,
        organizacion=args.organizacion,
        con_resumen=not args.sin_resumen,
        proveedor=args.proveedor,
        modelo=args.modelo,
        notificar_n8n=args.notificar_n8n,
    )
    rutas = exportar_todo(informe, PATHS.reports)
    _titulo("Resultado")
    m = informe.metricas
    print(f"Requisitos evaluados      : {m.get('requisitos_evaluados')}")
    print(f"Tasa de cumplimiento      : {m.get('tasa_cumplimiento', 0) * 100:.1f}%")
    print(f"Tasa de no cumplimiento   : {m.get('tasa_no_cumplimiento', 0) * 100:.1f}%")
    print(f"Trazabilidad verificada   : {m.get('tasa_trazabilidad_verificada', 0) * 100:.1f}%")
    print(f"Latencia media            : {m.get('latencia_media_s')} s")
    print("\nInformes exportados:")
    for k, v in rutas.items():
        print(f"  {k}: {v}")
    if informe.resumen_ejecutivo:
        _titulo("Resumen ejecutivo")
        print(informe.resumen_ejecutivo)


def cmd_matriz(args) -> None:
    _titulo("Matriz de trazabilidad")
    pipeline = Pipeline()
    informe = pipeline.diagnosticar(
        normas=args.normas or None,
        ambitos=args.ambitos or None,
        limite=args.limite,
        top_k=args.top_k,
        con_resumen=False,
    )
    rutas = exportar_todo(informe, PATHS.reports, prefijo="matriz")
    for k, v in rutas.items():
        print(f"  {k}: {v}")


def cmd_kpis(args) -> None:
    _titulo("Matriz de indicadores (KPI)")
    from mvp_sig.diagnosis.kpis import exportar_kpis, exportar_kpis_json

    pipeline = Pipeline()
    kpis, analisis = pipeline.matriz_kpis()
    ruta_csv = exportar_kpis(kpis, PATHS.reports / "matriz_kpis.csv")
    ruta_json = exportar_kpis_json(kpis, analisis, PATHS.reports / "matriz_kpis.json")
    print(f"  CSV : {ruta_csv}")
    print(f"  JSON: {ruta_json}")
    print(json.dumps(analisis, ensure_ascii=False, indent=2))


def cmd_metricas(args) -> None:
    _titulo("Métricas de recuperación semántica")
    pipeline = Pipeline()
    metricas = evaluar_recuperacion(pipeline.store, k=args.k)
    print(json.dumps({k: v for k, v in metricas.items() if k != "detalle"}, ensure_ascii=False, indent=2))
    print("\nDetalle por caso:")
    print("  (fragmento | documento)")
    for d in metricas["detalle"]:
        print(
            f"  {d['caso_id']}  "
            f"P={d['precision']:.2f} R={d['recall']:.2f} MRR={d['mrr']:.2f} nDCG={d['ndcg']:.2f} | "
            f"P={d['precision_documento']:.2f} R={d['recall_documento']:.2f} "
            f"MRR={d['mrr_documento']:.2f} nDCG={d['ndcg_documento']:.2f}  {d['consulta'][:60]}"
        )


def cmd_benchmark(args) -> None:
    _titulo("Benchmarking de modelos de lenguaje")
    pipeline = Pipeline()
    requisitos = pipeline.cargar_requisitos(args.normas or None)
    vistos: set[str] = set()
    muestra = []
    for r in requisitos:
        if r.clausula in vistos:
            continue
        vistos.add(r.clausula)
        muestra.append(r)
        if len(muestra) >= args.limite:
            break
    modelos = []
    for item in args.modelos or ["ollama/llama3.1:8b"]:
        proveedor, _, modelo = item.partition("/")
        modelos.append((proveedor, modelo or proveedor))
    corridas = ejecutar_benchmark(pipeline.store, muestra, modelos, top_k=args.top_k)
    ruta_csv = exportar_benchmark_csv(corridas, PATHS.reports / "benchmark.csv")
    ruta_md = exportar_benchmark_markdown(corridas, PATHS.reports / "benchmark.md")
    ruta_json = exportar_benchmark_json(corridas, PATHS.reports / "benchmark.json")
    print(f"\n  CSV : {ruta_csv}")
    print(f"  MD  : {ruta_md}")
    print(f"  JSON: {ruta_json}")

    # Informe de costo-efectividad (pregunta de investigación nº 4).
    try:
        from mvp_sig.evaluation.benchmark import exportar_costo_efectividad

        total_requisitos = len(pipeline.cargar_requisitos(args.normas or None))
        ruta_costo = exportar_costo_efectividad(
            corridas,
            PATHS.reports / "costo_efectividad.md",
            requisitos_totales=total_requisitos,
        )
        print(f"  Coste: {ruta_costo}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] no se pudo generar el informe de coste: {exc}")


def cmd_evidencia(args) -> None:
    """Registro manual de evidencia (texto pegado o archivo suelto)."""
    from mvp_sig.ingestion import manual

    pipeline = Pipeline()

    if args.listar:
        _titulo("Inventario de evidencias")
        inventario = pipeline.inventario()
        if args.origen != "todos":
            inventario = [f for f in inventario if f["origen"] == args.origen]
        if not inventario:
            print("  (no hay evidencias que coincidan con el filtro)")
        for r in inventario:
            marca = " [excluido]" if r["excluido"] else ""
            print(
                f"  {r['documento']}{marca}  id={r['id']}  {r['origen']}  "
                f"{r['chunks']} fragmentos  ámbito={r['ambito_principal']}  "
                f"tipo={r['tipo_documento']}"
            )
        print(
            f"\n  Total: {len(inventario)}  "
            f"(corpus={sum(1 for f in inventario if f['origen'] == 'corpus')}, "
            f"manual={sum(1 for f in inventario if f['origen'] == 'manual')}, "
            f"excluidos={sum(1 for f in inventario if f['excluido'])})"
        )
        return

    if args.eliminar:
        _titulo("Baja de evidencia")
        resultado = pipeline.eliminar_evidencia(args.eliminar)
        if resultado.get("ok"):
            print(f"  {resultado['mensaje']}")
        else:
            print(f"  [error] {resultado['motivo']}")
        return

    if args.excluir:
        _titulo("Exclusión del diagnóstico")
        resultado = pipeline.excluir_evidencia(args.excluir, motivo=args.motivo or "")
        if resultado.get("ok"):
            print(f"  {resultado['mensaje']}")
        else:
            print(f"  [error] {resultado['motivo']}")
        return

    if args.reincorporar:
        _titulo("Reincorporación al diagnóstico")
        resultado = pipeline.reincorporar_evidencia(args.reincorporar)
        if resultado.get("ok"):
            print(f"  {resultado['mensaje']}")
        else:
            print(f"  [error] {resultado['motivo']}")
        return

    if args.reindexar:
        _titulo("Reindexado de un documento")
        resultado = pipeline.reindexar_documento(args.reindexar)
        if resultado.get("ok"):
            print(f"  {resultado['mensaje']}")
        else:
            print(f"  [error] {resultado['motivo']}")
        return

    if args.documento:
        _titulo("Edición de metadatos")
        resultado = pipeline.actualizar_metadatos(
            args.documento,
            ambitos=list(args.ambitos) if args.ambitos else None,
            ambito_principal=args.ambito_principal,
            tipo_documento=args.tipo,
            organizacion=args.organizacion,
            codigo=args.codigo,
        )
        if resultado.get("ok"):
            print(f"  {resultado['mensaje']}")
            meta = resultado.get("metadatos", {})
            print(f"  Ámbitos    : {', '.join(meta.get('ambitos', []))}")
            print(f"  Tipo       : {meta.get('tipo_documento', '')}")
            print(f"  Organiz.   : {meta.get('organizacion', '')}")
            print(f"  Código     : {meta.get('codigo', '')}")
        else:
            print(f"  [error] {resultado['motivo']}")
        return

    texto = args.texto
    if args.texto_archivo:
        p = Path(args.texto_archivo)
        if not p.exists():
            print(f"  [error] No existe el archivo de texto: {p}")
            return
        texto = p.read_text(encoding="utf-8", errors="replace")

    if not texto and not args.archivo:
        _titulo("Registro manual de evidencia")
        print("  Indica --texto, --texto-archivo o --archivo. Usa --listar para ver el inventario.")
        return

    _titulo("Registro manual de evidencia")
    if texto:
        resultado = manual.registrar_texto(
            pipeline,
            texto,
            args.nombre or "",
            ambitos=args.ambitos or None,
            ambito_principal=args.ambito_principal,
            tipo_documento=args.tipo,
            organizacion=args.organizacion,
            codigo=args.codigo,
        )
    else:
        resultado = manual.registrar_archivo(
            pipeline,
            args.archivo,
            args.nombre or "",
            ambitos=args.ambitos or None,
            ambito_principal=args.ambito_principal,
            tipo_documento=args.tipo,
            organizacion=args.organizacion,
            codigo=args.codigo,
        )

    for aviso in resultado.avisos:
        print(f"  [aviso] {aviso}")
    if resultado.ok:
        print(f"  {resultado.mensaje}")
        print(f"  Fragmentos : {resultado.chunks}")
        print(f"  Ámbitos    : {', '.join(resultado.ambitos)} (principal: {resultado.ambito_principal})")
        print(f"  Archivo    : {resultado.ruta}")
    else:
        print(f"  [error] {resultado.mensaje}")


def cmd_n8n(args) -> None:
    _titulo("Orquestador n8n")
    from mvp_sig.integrations import n8n

    print(f"  Flujo exportable       : {n8n.ruta_flujo()}")
    validacion = n8n.validar_flujo()
    if validacion["ok"]:
        print(f"  Estado del flujo       : válido ({validacion['detalle']})")
        for n in validacion["nodos"]:
            print(f"      · {n}")
    else:
        print(f"  Estado del flujo       : INVÁLIDO — {validacion['detalle']}")

    webhook = PIPELINE.n8n_webhook
    if webhook:
        print(f"  Webhook configurado    : {webhook}")
    else:
        print("  Webhook configurado    : no (define N8N_WEBHOOK en .env)")
    print(
        "\n  Importación: en n8n, «Workflows → Import from File» y selecciona\n"
        "  workflows/diagnostico_sig_n8n.json. El flujo llama a la API del MVP\n"
        "  (POST http://127.0.0.1:8000/diagnostico); ajusta la URL si el API\n"
        "  se levanta en otro puerto."
    )


def cmd_api(args) -> None:
    import uvicorn

    _titulo("API FastAPI")
    print(f"  http://localhost:{args.puerto}/docs")
    uvicorn.run("mvp_sig.api.main:app", host=args.host, port=args.puerto, reload=args.reload)


def cmd_ui(args) -> None:
    import subprocess

    _titulo("Interfaz web (Streamlit)")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(Path(__file__).parent / "mvp_sig" / "ui" / "app.py"),
         "--server.port", str(args.puerto)],
        check=False,
    )


# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="MVP de diagnóstico inteligente de Sistemas Integrados de Gestión",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("estado", help="Estado del sistema")
    p.set_defaults(func=cmd_estado)

    p = sub.add_parser("ingesta", help="Procesar e indexar el corpus de evidencias")
    p.add_argument("--ruta", default=None, help="Carpeta del corpus")
    p.add_argument("--extensiones", nargs="+", default=[".pdf", ".docx", ".xlsx", ".xls"])
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--indexar-requisitos", action="store_true", default=True)
    p.set_defaults(func=cmd_ingesta)

    p = sub.add_parser("diagnostico", help="Ejecutar el diagnóstico de cumplimiento")
    p.add_argument("--normas", nargs="*", default=None)
    p.add_argument("--ambitos", nargs="*", default=None)
    p.add_argument("--limite", type=int, default=10)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--organizacion", default="Organización evaluada")
    p.add_argument("--sin-resumen", action="store_true")
    p.add_argument("--proveedor", default=None)
    p.add_argument("--modelo", default=None)
    p.add_argument(
        "--notificar-n8n",
        action="store_true",
        help="Publica el informe en el webhook de n8n (N8N_WEBHOOK) al terminar",
    )
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("matriz", help="Generar sólo la matriz de trazabilidad")
    p.add_argument("--normas", nargs="*", default=None)
    p.add_argument("--ambitos", nargs="*", default=None)
    p.add_argument("--limite", type=int, default=10)
    p.add_argument("--top-k", type=int, default=5)
    p.set_defaults(func=cmd_matriz)

    p = sub.add_parser("kpis", help="Construir la matriz de indicadores")
    p.set_defaults(func=cmd_kpis)

    p = sub.add_parser("metricas", help="Métricas de recuperación semántica")
    p.add_argument("--k", type=int, default=5)
    p.set_defaults(func=cmd_metricas)

    p = sub.add_parser("benchmark", help="Comparar modelos de lenguaje")
    p.add_argument("--modelos", nargs="*", default=["ollama/llama3.1:8b"])
    p.add_argument("--limite", type=int, default=5)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--normas", nargs="*", default=None)
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser(
        "evidencia",
        help="Registrar evidencia manualmente (texto pegado o archivo suelto)",
    )
    p.add_argument("--texto", default=None, help="Texto de la evidencia")
    p.add_argument("--texto-archivo", default=None, help="Archivo con el texto de la evidencia")
    p.add_argument("--archivo", default=None, help="Archivo suelto a registrar (PDF/DOCX/XLSX/XLS/TXT)")
    p.add_argument("--nombre", default="", help="Nombre con el que se registra la evidencia")
    p.add_argument("--ambitos", nargs="*", default=None, help="calidad ambiente seguridad integral")
    p.add_argument("--ambito-principal", default=None, help="Ámbito principal de la evidencia")
    p.add_argument("--tipo", default=None, help="Tipo documental (acta, informe, registro…)")
    p.add_argument("--organizacion", default=None, help="Organización responsable")
    p.add_argument("--codigo", default=None, help="Código del documento")
    p.add_argument("--listar", action="store_true", help="Listar el inventario de evidencias")
    p.add_argument(
        "--origen",
        default="todos",
        choices=["todos", "corpus", "manual"],
        help="Filtro de origen para --listar",
    )
    p.add_argument("--eliminar", default=None, help="Dar de baja una evidencia manual por nombre o id")
    p.add_argument(
        "--excluir",
        default=None,
        help="Retirar un documento del diagnóstico (conserva el archivo)",
    )
    p.add_argument("--motivo", default=None, help="Motivo de la exclusión")
    p.add_argument(
        "--reincorporar",
        default=None,
        help="Volver a incorporar al diagnóstico un documento excluido",
    )
    p.add_argument(
        "--reindexar",
        default=None,
        help="Reindexar un documento desde su archivo (conserva los metadatos)",
    )
    p.add_argument(
        "--documento",
        default=None,
        help="Editar los metadatos de un documento (id, clave o nombre único)",
    )
    p.set_defaults(func=cmd_evidencia)

    p = sub.add_parser("n8n", help="Estado del orquestador n8n y del flujo exportable")
    p.set_defaults(func=cmd_n8n)

    p = sub.add_parser("api", help="Levantar la API REST")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--puerto", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_api)

    p = sub.add_parser("ui", help="Levantar la interfaz web")
    p.add_argument("--puerto", type=int, default=8501)
    p.set_defaults(func=cmd_ui)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    main()
