"""Interfaz web del MVP (Streamlit).

Ejecución:  streamlit run mvp_sig/ui/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Permite ejecutar el archivo directamente.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

from mvp_sig.diagnosis.traceability import construir_filas
from mvp_sig.evaluation.benchmark import exportar_benchmark_markdown, ejecutar_benchmark
from mvp_sig.evaluation.metrics import evaluar_recuperacion
from mvp_sig.llm.provider import proveedores_disponibles
from mvp_sig.pipeline import Pipeline
from mvp_sig.settings import CORPUS_EVIDENCIAS, NORMAS, PATHS

st.set_page_config(
    page_title="Diagnóstico inteligente de SIG · MVP",
    page_icon="🧭",
    layout="wide",
)

VERDICTO_COLOR = {
    "CUMPLE": "🟢",
    "CUMPLE_PARCIAL": "🟡",
    "NO_CUMPLE": "🔴",
    "NO_APLICA": "⚪",
}


@st.cache_resource(show_spinner=False)
def obtener_pipeline() -> Pipeline:
    return Pipeline()


def fmt_pct(x) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


# --------------------------------------------------------------------------- #
# Barra lateral
# --------------------------------------------------------------------------- #
def barra_lateral() -> None:
    st.sidebar.title("🧭 Diagnóstico de SIG")
    st.sidebar.caption("ISO 9001 · 14001 · 45001 con RAG y trazabilidad verificada")

    with st.sidebar:
        st.subheader("Motor de lenguaje")
        provs = proveedores_disponibles()
        for p in provs:
            estado = "🟢 disponible" if p.get("disponible") else "⚪ no disponible"
            st.markdown(f"**{p['proveedor']}** · `{p.get('modelo', '-')}` — {estado}")

        st.subheader("Alcance del diagnóstico")
        normas_sel = st.multiselect(
            "Normas",
            options=list(NORMAS.keys()),
            default=list(NORMAS.keys()),
            format_func=lambda k: f"{k} ({NORMAS[k].ambito})",
        )
        ambitos_sel = st.multiselect(
            "Ámbitos",
            options=["calidad", "ambiente", "seguridad"],
            default=["calidad", "ambiente", "seguridad"],
        )

        st.subheader("Selección de requisitos")
        modo_eval = st.radio(
            "Modo de evaluación",
            options=["Por límite", "Por cláusulas específicas", "Por requisitos concretos"],
            index=0,
            help="Por límite: toma los primeros N del listado. Por cláusulas: evalúa solo las cláusulas elegidas. Por requisitos concretos: elige IDs exactos.",
        )

        clausulas_sel = []
        requisitos_ids_sel = []

        try:
            _p_side = obtener_pipeline()
            _reqs_side = _p_side.cargar_requisitos(normas_sel or None)
            if ambitos_sel:
                _reqs_side = [r for r in _reqs_side if r.ambito in ambitos_sel]
        except Exception:
            _reqs_side = []

        if modo_eval == "Por cláusulas específicas":
            clausulas_unicas = sorted({r.clausula for r in _reqs_side})
            if not clausulas_unicas:
                st.warning("No hay cláusulas disponibles con los filtros actuales.")
            clausulas_sel = st.multiselect(
                "Selecciona cláusulas",
                options=clausulas_unicas,
                help="Ej. 4.1, 4.2, 5.1.1, 6.1, 8.2, 9.2...",
            )
            if clausulas_sel:
                cnt = sum(1 for r in _reqs_side if r.clausula in clausulas_sel)
                st.caption(f"Se evaluarán **{cnt}** requisito(s) con esta selección.")
            else:
                st.caption("Selecciona al menos una cláusula.")

        elif modo_eval == "Por requisitos concretos":
            if not _reqs_side:
                st.warning("No hay requisitos disponibles con los filtros actuales.")
            else:
                opciones_req = [
                    f"{r.id} | {r.norma} | cl.{r.clausula} | {r.ambito} | {r.texto[:70]}..."
                    for r in _reqs_side
                ]
                seleccionados_ui = st.multiselect(
                    "Selecciona requisitos exactos",
                    options=opciones_req,
                    help="Puedes buscar por ID, norma o cláusula escribiendo en el buscador.",
                )
                for s in seleccionados_ui:
                    try:
                        requisitos_ids_sel.append(s.split(" | ")[0])
                    except Exception:
                        pass
                if requisitos_ids_sel:
                    st.caption(f"Se evaluarán **{len(requisitos_ids_sel)}** requisito(s) seleccionado(s).")
                else:
                    st.caption("Selecciona al menos un requisito.")

        limite = st.number_input(
            "Máximo de requisitos a evaluar",
            min_value=1,
            max_value=300,
            value=12,
            step=1,
            disabled=(modo_eval != "Por límite"),
            help="Solo se usa cuando el modo es 'Por límite'.",
        )
        top_k = st.slider("Fragmentos recuperados por requisito (k)", 1, 12, 5)
        organizacion = st.text_input("Organización evaluada", "METUNIMET — Manufacturas Metalmecánicas")
        con_resumen = st.checkbox("Generar resumen ejecutivo con LLM", value=True)

        st.subheader("Corpus de evidencias")
        raiz = st.text_input("Carpeta del corpus", str(CORPUS_EVIDENCIAS))

    st.session_state["cfg"] = {
        "normas": normas_sel,
        "ambitos": ambitos_sel,
        "limite": int(limite),
        "top_k": int(top_k),
        "organizacion": organizacion,
        "con_resumen": con_resumen,
        "raiz": raiz,
        "modo_eval": modo_eval,
        "clausulas_sel": clausulas_sel,
        "requisitos_ids_sel": requisitos_ids_sel,
    }


barra_lateral()
cfg = st.session_state["cfg"]
pipeline = obtener_pipeline()

# --------------------------------------------------------------------------- #
# Encabezado
# --------------------------------------------------------------------------- #
st.title("Sistema inteligente de diagnóstico de Sistemas Integrados de Gestión")
st.caption(
    "Verificación de requisitos normativos contra la evidencia documental de la organización, "
    "con trazabilidad requisito–evidencia verificada sobre la cita."
)

estado = pipeline.estado()
cols = st.columns(5)
cols[0].metric("Requisitos indexados", estado["base_vectorial"]["requisitos"])
cols[1].metric("Fragmentos de evidencia", estado["base_vectorial"]["evidencias"])
cols[2].metric("Documentos catalogados", estado["catalogo"])
cols[3].metric("Embeddings", estado["base_vectorial"]["modelo_embeddings"])
cols[4].metric("LLM", f"{estado['llm']['proveedor']}/{estado['llm']['modelo']}")

tabs = st.tabs(
    [
        "🚀 Diagnóstico",
        "🔗 Matriz de trazabilidad",
        "📊 Indicadores (KPI)",
        "🧪 Evaluación",
        "📥 Evidencia",
        "⚙️ Ingesta",
    ]
)

# --------------------------------------------------------------------------- #
# Pestaña: diagnóstico
# --------------------------------------------------------------------------- #
with tabs[0]:
    st.subheader("Ejecutar diagnóstico de cumplimiento")
    st.caption(
        "El sistema recupera la evidencia relevante para cada requisito, la razona con el LLM "
        "y verifica que cada cita exista realmente en el documento fuente."
    )

    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("▶ Ejecutar diagnóstico", type="primary", use_container_width=True):
            with st.spinner("Procesando requisitos y verificando trazabilidad..."):
                try:
                    from mvp_sig.diagnosis.engine import MotorDiagnostico

                    modo_eval = cfg.get("modo_eval", "Por límite")
                    reqs_all = pipeline.cargar_requisitos(cfg["normas"] or None)
                    if cfg.get("ambitos"):
                        reqs_all = [r for r in reqs_all if r.ambito in cfg["ambitos"]]

                    if modo_eval == "Por cláusulas específicas":
                        claus = cfg.get("clausulas_sel") or []
                        if not claus:
                            st.warning("Selecciona al menos una cláusula para ejecutar el diagnóstico.")
                            st.stop()
                        reqs_eval = [r for r in reqs_all if r.clausula in claus]
                        st.info(f"Evaluando {len(reqs_eval)} requisito(s) por cláusulas: {', '.join(claus)}")
                        motor = MotorDiagnostico(pipeline.store, pipeline.llm, top_k=cfg["top_k"], organizacion=cfg["organizacion"])
                        informe = motor.diagnosticar(reqs_eval, con_resumen=cfg["con_resumen"])

                    elif modo_eval == "Por requisitos concretos":
                        ids_sel = cfg.get("requisitos_ids_sel") or []
                        if not ids_sel:
                            st.warning("Selecciona al menos un requisito concreto para ejecutar el diagnóstico.")
                            st.stop()
                        reqs_eval = [r for r in reqs_all if r.id in ids_sel]
                        st.info(f"Evaluando {len(reqs_eval)} requisito(s) por ID: {', '.join(ids_sel)}")
                        motor = MotorDiagnostico(pipeline.store, pipeline.llm, top_k=cfg["top_k"], organizacion=cfg["organizacion"])
                        informe = motor.diagnosticar(reqs_eval, con_resumen=cfg["con_resumen"])

                    else:
                        informe = pipeline.diagnosticar(
                            normas=cfg["normas"] or None,
                            ambitos=cfg["ambitos"] or None,
                            limite=cfg["limite"],
                            top_k=cfg["top_k"],
                            organizacion=cfg["organizacion"],
                            con_resumen=cfg["con_resumen"],
                        )

                    st.session_state["informe"] = informe
                    st.session_state["informe_dict"] = informe.to_dict()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Error en el diagnóstico: {exc}")

    with col_b:
        st.metric(
            "Fragmentos en la base de evidencia",
            estado["base_vectorial"]["evidencias"],
            help="Si es 0, ejecuta primero la ingesta en la pestaña ⚙️",
        )
        if estado["base_vectorial"]["evidencias"] == 0:
            st.warning("No hay evidencias indexadas. Ve a **⚙️ Ingesta** para cargar el corpus.")

    informe = st.session_state.get("informe")
    if informe is not None:
        m = informe.metricas
        st.markdown("#### Resultado")
        c = st.columns(5)
        c[0].metric("Requisitos evaluados", m.get("requisitos_evaluados", 0))
        c[1].metric("Tasa de cumplimiento", fmt_pct(m.get("tasa_cumplimiento")))
        c[2].metric("No cumplimiento", fmt_pct(m.get("tasa_no_cumplimiento")))
        c[3].metric("Trazabilidad verificada", fmt_pct(m.get("tasa_trazabilidad_verificada")))
        c[4].metric("Latencia media", f"{m.get('latencia_media_s', 0):.1f} s")

        if informe.resumen_ejecutivo:
            with st.expander("📄 Resumen ejecutivo", expanded=True):
                st.markdown(informe.resumen_ejecutivo)

        # Distribución por veredicto
        dist = m.get("distribucion_veredictos", {})
        if dist:
            st.markdown("#### Distribución de veredictos")
            st.bar_chart(pd.Series(dist))

        # Detalle por requisito
        st.markdown("#### Detalle por requisito")
        filas = construir_filas(informe)
        df = pd.DataFrame(filas)
        if not df.empty:
            vista = df[
                [
                    "requisito_id",
                    "norma",
                    "clausula",
                    "ambito",
                    "veredicto",
                    "confianza",
                    "traza_verificada",
                    "evidencia_documento",
                    "hallazgo",
                    "severidad",
                ]
            ]
            st.dataframe(
                vista,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "confianza": st.column_config.NumberColumn(format="%.2f"),
                },
            )
            # Hallazgos no conformes
            nc = df[df["veredicto"].isin(["NO_CUMPLE", "CUMPLE_PARCIAL"])]
            if not nc.empty:
                st.markdown("#### Hallazgos y acciones correctivas")
                for _, r in nc.iterrows():
                    icono = VERDICTO_COLOR.get(r["veredicto"], "")
                    with st.expander(
                        f"{icono} {r['requisito_id']} · {r['norma']} cl.{r['clausula']} — {r['severidad'] or 'sin severidad'}"
                    ):
                        st.markdown(f"**Requisito:** {r['requisito']}")
                        if r["hallazgo"]:
                            st.markdown(f"**Hallazgo:** {r['hallazgo']}")
                        if r["recomendacion"]:
                            st.markdown(f"**Recomendación:** {r['recomendacion']}")
                        if r["evidencia_cita"]:
                            st.caption(f"Evidencia: {r['evidencia_documento']}")
                            st.info(r["evidencia_cita"])
                        st.caption(f"Trazabilidad verificada: {r['traza_verificada']}")

            st.download_button(
                "⬇ Descargar informe completo (JSON)",
                data=json.dumps(st.session_state["informe_dict"], ensure_ascii=False, indent=2),
                file_name="informe_diagnostico.json",
                mime="application/json",
            )

# --------------------------------------------------------------------------- #
# Pestaña: matriz de trazabilidad
# --------------------------------------------------------------------------- #
with tabs[1]:
    st.subheader("Matriz de trazabilidad requisito–evidencia")
    informe = st.session_state.get("informe")
    if informe is None:
        st.info("Ejecuta un diagnóstico para construir la matriz.")
    else:
        filas = construir_filas(informe)
        df = pd.DataFrame(filas)
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_norma = st.multiselect("Filtrar por norma", options=sorted(df["norma"].unique()))
        with col_f2:
            filtro_ver = st.multiselect(
                "Filtrar por veredicto",
                options=sorted(df["veredicto"].unique()),
                default=sorted(df["veredicto"].unique()),
            )
        vista = df
        if filtro_norma:
            vista = vista[vista["norma"].isin(filtro_norma)]
        if filtro_ver:
            vista = vista[vista["veredicto"].isin(filtro_ver)]
        st.dataframe(vista, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Descargar matriz (CSV)",
            data=vista.to_csv(index=False).encode("utf-8-sig"),
            file_name="matriz_trazabilidad.csv",
            mime="text/csv",
        )

# --------------------------------------------------------------------------- #
# Pestaña: KPIs
# --------------------------------------------------------------------------- #
with tabs[2]:
    st.subheader("Matriz de indicadores clave de desempeño por ámbito")
    st.caption(
        "Objetivo específico 3.2: estructurar los indicadores de calidad, ambiente y seguridad "
        "con base en los requisitos normativos, y analizar su consistencia y redundancia."
    )
    if st.button("Construir matriz de indicadores"):
        with st.spinner("Analizando indicadores..."):
            kpis, analisis = pipeline.matriz_kpis()
            st.session_state["kpis"] = (kpis, analisis)

    if "kpis" in st.session_state:
        kpis, analisis = st.session_state["kpis"]
        c = st.columns(4)
        c[0].metric("Indicadores totales", analisis["total_kpis"])
        c[1].metric("Ámbitos cubiertos", len(analisis["por_ambito"]))
        c[2].metric("Familias transversales", len(analisis["indicadores_transversales"]))
        c[3].metric("Indicadores normativos", sum(1 for k in kpis if k.origen == "normativo"))

        df_k = pd.DataFrame([k.to_dict() for k in kpis])
        if not df_k.empty:
            amb_sel = st.multiselect(
                "Filtrar por ámbito", options=sorted(df_k["ambito"].unique()), default=[]
            )
            vista_k = df_k[df_k["ambito"].isin(amb_sel)] if amb_sel else df_k
            st.dataframe(
                vista_k[
                    [
                        "id",
                        "nombre",
                        "ambito",
                        "norma",
                        "clausula_fuente",
                        "formula",
                        "unidad",
                        "frecuencia",
                        "meta_sugerida",
                        "origen",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "⬇ Descargar matriz de KPI (CSV)",
                data=vista_k.to_csv(index=False).encode("utf-8-sig"),
                file_name="matriz_kpis.csv",
                mime="text/csv",
            )

        st.markdown("#### Análisis de consistencia y redundancia")
        st.json(analisis["indicadores_transversales"])

# --------------------------------------------------------------------------- #
# Pestaña: evaluación
# --------------------------------------------------------------------------- #
with tabs[3]:
    st.subheader("Evaluación del sistema")
    st.markdown("#### 1. Calidad de la recuperación semántica")
    st.caption("Precisión@k, recall@k, MRR y nDCG sobre el conjunto de referencia (gold set).")
    if st.button("Evaluar recuperación"):
        with st.spinner("Ejecutando consultas de referencia..."):
            metricas = evaluar_recuperacion(pipeline.store, k=cfg["top_k"])
            st.session_state["metricas_rec"] = metricas

    if "metricas_rec" in st.session_state:
        m = st.session_state["metricas_rec"]
        c = st.columns(4)
        c[0].metric("Precisión@k", fmt_pct(m["precision@k"]))
        c[1].metric("Recall@k", fmt_pct(m["recall@k"]))
        c[2].metric("MRR", f"{m['mrr']:.3f}")
        c[3].metric("nDCG@k", f"{m['ndcg@k']:.3f}")
        df_m = pd.DataFrame(m["detalle"])
        st.dataframe(
            df_m[["caso_id", "consulta", "precision", "recall", "mrr", "ndcg"]],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### 2. Benchmarking de modelos de lenguaje")
    st.caption("Objetivo 3.3.c: comparación costo-efectiva de los modelos candidatos.")
    modelos_txt = st.text_area(
        "Modelos a comparar (JSON, uno por línea)",
        value='[{"proveedor": "ollama", "modelo": "llama3.1:8b"}]',
        height=110,
    )
    limite_bench = st.number_input("Requisitos por modelo", min_value=1, max_value=30, value=5)

    if st.button("▶ Ejecutar benchmarking"):
        try:
            modelos = json.loads(modelos_txt)
        except json.JSONDecodeError as exc:
            st.error(f"JSON inválido: {exc}")
            modelos = []
        if modelos:
            requisitos = pipeline.cargar_requisitos(cfg["normas"] or None)
            vistos: set[str] = set()
            muestra = []
            for r in requisitos:
                if r.clausula in vistos:
                    continue
                vistos.add(r.clausula)
                muestra.append(r)
                if len(muestra) >= limite_bench:
                    break
            with st.spinner("Ejecutando modelos..."):
                corridas = ejecutar_benchmark(
                    pipeline.store, muestra, [(m["proveedor"], m["modelo"]) for m in modelos]
                )
                st.session_state["benchmark"] = corridas

    if "benchmark" in st.session_state:
        corridas = st.session_state["benchmark"]
        filas = [
            {
                "proveedor": c.proveedor,
                "modelo": c.modelo,
                "estado": c.resumen().get("estado"),
                "trazabilidad": fmt_pct(c.resumen().get("tasa_trazabilidad_verificada")),
                "cumplimiento": fmt_pct(c.resumen().get("tasa_cumplimiento")),
                "latencia_prom": c.resumen().get("latencia_media_s"),
                "tokens_in": int(c.resumen().get("tokens_promedio_entrada", 0) or 0),
                "tokens_out": int(c.resumen().get("tokens_promedio_salida", 0) or 0),
                "coste_usd": c.resumen().get("costo_usd_total", 0),
            }
            for c in corridas
        ]
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
        ruta_md = exportar_benchmark_markdown(corridas, PATHS.reports / "benchmark.md")
        st.download_button(
            "⬇ Descargar informe de benchmarking (Markdown)",
            data=Path(ruta_md).read_text(encoding="utf-8"),
            file_name="benchmark.md",
            mime="text/markdown",
        )

# --------------------------------------------------------------------------- #
# Pestaña: evidencia (registro manual y edición del corpus)
# --------------------------------------------------------------------------- #
with tabs[4]:
    st.subheader("Evidencia: registro manual y edición del corpus")
    st.caption(
        "Dos vías para trabajar con la evidencia del diagnóstico: incorporar documentos que no "
        "vienen del corpus (un acta pegada desde un correo, un reporte exportado) y corregir "
        "la clasificación de los que ya están indexados, sin rehacer la ingesta completa."
    )

    from mvp_sig.ingestion import manual as manual_mod

    vista_ev = st.radio(
        "Vista",
        ["➕ Registrar evidencia", "🗂️ Inventario y edición del corpus"],
        horizontal=True,
        key="vista_evidencia",
    )

    if vista_ev == "🗂️ Inventario y edición del corpus":
        # ------------------------------------------------------------------ #
        # Inventario y edición
        # ------------------------------------------------------------------ #
        st.markdown("#### Inventario de evidencias")
        st.caption(
            "Selecciona una fila de la tabla —o el desplegable de debajo— para corregir su "
            "clasificación (ámbito, tipo documental, "
            "organización, código), reindexarla tras un cambio en el archivo original, "
            "o retirarla del diagnóstico. La exclusión conserva el archivo y **persiste** "
            "aunque la ingesta completa se vuelva a ejecutar."
        )

        inventario = pipeline.inventario()
        if not inventario:
            st.info("El inventario está vacío. Ejecute la ingesta del corpus o registre evidencia.")
        else:
            c_f1, c_f2, c_f3 = st.columns([2, 1, 1])
            with c_f1:
                busqueda = st.text_input(
                    "Buscar",
                    placeholder="nombre del documento, código u organización",
                    key="busqueda_inventario",
                )
            with c_f2:
                origen_filtro = st.multiselect(
                    "Origen",
                    ["corpus", "manual"],
                    default=["corpus", "manual"],
                    key="filtro_origen_inventario",
                )
            with c_f3:
                estado_filtro = st.selectbox(
                    "Estado",
                    ["indexadas y excluidas", "sólo indexadas", "sólo excluidas"],
                    key="filtro_estado_inventario",
                )

            filas = list(inventario)
            if busqueda.strip():
                texto = busqueda.strip().lower()
                filas = [
                    f
                    for f in filas
                    if texto in str(f["documento"]).lower()
                    or texto in str(f["codigo"]).lower()
                    or texto in str(f["organizacion"]).lower()
                ]
            if origen_filtro:
                filas = [f for f in filas if f["origen"] in origen_filtro]
            if estado_filtro == "sólo indexadas":
                filas = [f for f in filas if not f["excluido"]]
            elif estado_filtro == "sólo excluidas":
                filas = [f for f in filas if f["excluido"]]

            st.caption(
                f"{len(filas)} documento(s) · "
                f"{sum(1 for f in filas if f['origen'] == 'corpus')} del corpus · "
                f"{sum(1 for f in filas if f['origen'] == 'manual')} manuales · "
                f"{sum(1 for f in filas if f['excluido'])} excluidos · "
                f"{sum(int(f['chunks']) for f in filas):,} fragmentos"
            )

            if filas:
                df_inv = pd.DataFrame(filas)
                columnas = [
                    "documento",
                    "origen",
                    "tipo_documento",
                    "ambito_principal",
                    "chunks",
                    "caracteres",
                    "estado",
                    "codigo",
                    "id",
                ]
                evento = st.dataframe(
                    df_inv[columnas],
                    on_select="rerun",
                    selection_mode="single-row",
                    hide_index=True,
                    use_container_width=True,
                    # La clave incluye los filtros: al cambiar la búsqueda, la
                    # tabla se recrea y no queda seleccionada una fila que ahora
                    # corresponde a otro documento.
                    key=(
                        f"tabla_inventario_{len(filas)}"
                        f"_{'-'.join(origen_filtro) or 'none'}"
                        f"_{estado_filtro}_{busqueda.strip()[:40]}"
                    ),
                )
                seleccion = evento.selection.rows if evento and evento.selection else []
            else:
                seleccion = []

            # La selección de fila del dataframe no es accesible por teclado y su
            # gesto puede pasar desapercibido; se ofrece además un desplegable.
            indice = seleccion[0] if seleccion else None
            if indice is None and filas:
                if len(filas) == 1:
                    indice = 0
                else:
                    etiquetas = [
                        f"{f['documento']}  ·  {f['id']}  ·  {f['origen']}" for f in filas
                    ]
                    elegido = st.selectbox(
                        "…o elige aquí el documento",
                        ["(ninguno)"] + etiquetas,
                    )
                    if elegido != "(ninguno)":
                        indice = etiquetas.index(elegido)

            if indice is not None:
                fila = filas[indice]
                st.markdown("---")
                st.markdown(f"#### {fila['documento']}")
                st.caption(
                    f"**id** `{fila['id']}` · **origen** {fila['origen']} · "
                    f"**estado** {fila['estado']} · "
                    f"**{int(fila['chunks']):,} "
                    f"{'fragmento' if int(fila['chunks']) == 1 else 'fragmentos'}**"
                )
                st.caption(f"Ruta de origen: `{fila['ruta']}`")

                with st.expander("Ficha documental", expanded=False):
                    st.json(
                        {
                            "documento": fila["documento"],
                            "tipo": fila["tipo"],
                            "tipo_documento": fila["tipo_documento"],
                            "ambitos": fila["ambitos"],
                            "ambito_principal": fila["ambito_principal"],
                            "organizacion": fila["organizacion"],
                            "codigo": fila["codigo"],
                            "chunks": fila["chunks"],
                            "caracteres": fila["caracteres"],
                            "indexado": fila["indexado"],
                            "motivo_exclusion": fila["motivo_exclusion"],
                        }
                    )

                if fila["excluido"]:
                    st.info(
                        "Este documento está excluido del diagnóstico: su archivo se conserva y no "
                        "participa en la recuperación de evidencia."
                    )
                    if st.button("♻️ Reincorporar al diagnóstico", type="primary"):
                        with st.spinner("Reindexando..."):
                            res = pipeline.reincorporar_evidencia(fila["id"])
                        if res.get("ok"):
                            st.success(res.get("mensaje", "Documento reincorporado."))
                            st.rerun()
                        else:
                            st.error(res.get("motivo", "No se pudo reincorporar."))
                else:
                    st.markdown("**Corregir la clasificación**")
                    with st.form(f"form_editar_{fila['id']}"):
                        e1, e2 = st.columns(2)
                        with e1:
                            ambitos_ed = st.multiselect(
                                "Ámbito(s) del SIG",
                                ["calidad", "ambiente", "seguridad", "integral"],
                                default=list(fila["ambitos"] or []),
                                key=f"edit_ambitos_{fila['id']}",
                            )
                        with e2:
                            tipo_ed = st.text_input(
                                "Tipo documental",
                                value=str(fila["tipo_documento"] or ""),
                                key=f"edit_tipo_{fila['id']}",
                            )
                        e3, e4 = st.columns(2)
                        with e3:
                            org_ed = st.text_input(
                                "Organización responsable",
                                value=str(fila["organizacion"] or ""),
                                key=f"edit_org_{fila['id']}",
                            )
                        with e4:
                            cod_ed = st.text_input(
                                "Código del documento",
                                value=str(fila["codigo"] or ""),
                                key=f"edit_cod_{fila['id']}",
                            )
                        guardar_ed = st.form_submit_button(
                            "💾 Guardar y reindexar", type="primary"
                        )

                    if guardar_ed:
                        with st.spinner("Reindexando el documento..."):
                            res = pipeline.actualizar_metadatos(
                                fila["id"],
                                ambitos=list(ambitos_ed) or None,
                                tipo_documento=tipo_ed or None,
                                organizacion=org_ed or None,
                                codigo=cod_ed or None,
                            )
                        if res.get("ok"):
                            st.success(res.get("mensaje", "Documento actualizado."))
                            st.rerun()
                        else:
                            st.error(res.get("motivo", "No se pudo actualizar."))

                    c_a1, c_a2 = st.columns(2)
                    with c_a1:
                        if st.button("🔄 Reindexar desde el archivo", use_container_width=True):
                            with st.spinner("Reindexando el documento..."):
                                res = pipeline.reindexar_documento(fila["id"])
                            if res.get("ok"):
                                st.success(res.get("mensaje", "Documento reindexado."))
                                st.rerun()
                            else:
                                st.error(res.get("motivo", "No se pudo reindexar."))
                    with c_a2:
                        motivo_ex = st.text_input(
                            "Motivo de la exclusión",
                            value="",
                            placeholder="p. ej. duplicado del manual de calidad",
                            key=f"motivo_ex_{fila['id']}",
                        )
                        if st.button(
                            "🚫 Excluir del diagnóstico",
                            use_container_width=True,
                            help="Retira el documento del índice y del catálogo; el archivo se conserva.",
                        ):
                            with st.spinner("Excluyendo..."):
                                res = pipeline.excluir_evidencia(fila["id"], motivo=motivo_ex)
                            if res.get("ok"):
                                st.success(res.get("mensaje", "Documento excluido."))
                                st.rerun()
                            else:
                                st.error(res.get("motivo", "No se pudo excluir."))

                    if fila["origen"] == "manual":
                        st.caption(
                            "La baja elimina también el archivo de `data/evidencias_manuales/`. "
                            "Para conservar el archivo, use la exclusión."
                        )
                        if st.button("🗑️ Dar de baja (elimina el archivo)"):
                            with st.spinner("Dando de baja..."):
                                res = pipeline.eliminar_evidencia(fila["id"])
                            if res.get("ok"):
                                st.success(res.get("mensaje", "Evidencia dada de baja."))
                                st.rerun()
                            else:
                                st.error(res.get("motivo", "No se pudo dar de baja."))

            st.divider()
            st.caption(
                "Para comprobar que una evidencia concreta es recuperable por el LLM, use la prueba "
                "de búsqueda de la vista «Registrar evidencia»."
            )

    else:
        st.subheader("Registro manual de evidencia")
        st.caption(
            "Incorpora evidencia que no viene del corpus: un acta pegada desde un correo, un "
            "reporte exportado del sistema, un documento suelto. Se indexa de forma incremental "
            "—no reindexa el corpus— y queda disponible para ser citada por el diagnóstico."
        )

        modo = st.radio(
            "Origen de la evidencia",
            ["📝 Pegar texto", "📎 Subir archivo"],
            horizontal=True,
            key="modo_evidencia",
        )

        with st.form("form_evidencia", clear_on_submit=False):
            c1, c2 = st.columns([2, 1])
            with c1:
                nombre = st.text_input(
                    "Nombre del documento *",
                    placeholder="Acta de revisión por la dirección 2026-02",
                    help="Así aparecerá en la matriz de trazabilidad y en las citas del diagnóstico.",
                )
            with c2:
                ambitos_sel = st.multiselect(
                    "Ámbito(s) del SIG",
                    ["calidad", "ambiente", "seguridad", "integral"],
                    default=["integral"],
                    help="Si no se indica, el sistema lo infiere del nombre y del texto.",
                )

            c3, c4 = st.columns(2)
            with c3:
                tipo_sel = st.selectbox(
                    "Tipo documental",
                    [
                        "(inferir del nombre)",
                        "acta",
                        "informe",
                        "registro",
                        "procedimiento",
                        "formato",
                        "matriz",
                        "lista",
                        "plan",
                        "politica",
                        "manual",
                        "documento",
                    ],
                )
            with c4:
                organizacion_sel = st.text_input(
                    "Organización responsable",
                    value=cfg.get("organizacion", ""),
                    help="Se usa como metadato de la evidencia.",
                )

            codigo_sel = st.text_input("Código del documento (opcional)")

            if modo == "📝 Pegar texto":
                texto_sel = st.text_area(
                    "Texto de la evidencia *",
                    height=220,
                    placeholder=(
                        "Pega aquí el acta, el correo, el reporte o el fragmento de texto "
                        "que debe servir como evidencia..."
                    ),
                )
                archivo_sel = None
            else:
                texto_sel = ""
                archivo_sel = st.file_uploader(
                    "Archivo *",
                    type=["pdf", "docx", "xlsx", "xls", "txt", "md"],
                    help="El archivo se copia a data/evidencias_manuales/ para que la evidencia sea auditable.",
                )

            enviado = st.form_submit_button("▶ Registrar evidencia", type="primary")

        if enviado:
            with st.spinner("Indexando la evidencia..."):
                try:
                    if modo == "📝 Pegar texto":
                        if not texto_sel.strip():
                            st.warning("Escribe o pega el texto de la evidencia.")
                            st.stop()
                        resultado = manual_mod.registrar_texto(
                            pipeline,
                            texto_sel,
                            nombre,
                            ambitos=ambitos_sel or None,
                            tipo_documento=None if tipo_sel.startswith("(") else tipo_sel,
                            organizacion=organizacion_sel or None,
                            codigo=codigo_sel or None,
                        )
                    else:
                        if archivo_sel is None:
                            st.warning("Selecciona un archivo.")
                            st.stop()
                        bytes_ = archivo_sel.getvalue()
                        if len(bytes_) > manual_mod.MAX_BYTES:
                            st.error(
                                f"El archivo supera el límite de "
                                f"{manual_mod.MAX_BYTES // (1024 * 1024)} MB."
                            )
                            st.stop()
                        resultado = manual_mod.registrar_archivo(
                            pipeline,
                            bytes_,
                            nombre or archivo_sel.name,
                            ambitos=ambitos_sel or None,
                            tipo_documento=None if tipo_sel.startswith("(") else tipo_sel,
                            organizacion=organizacion_sel or None,
                            codigo=codigo_sel or None,
                            extension=Path(archivo_sel.name).suffix,
                        )
                    for aviso in resultado.avisos:
                        st.warning(aviso)
                    if resultado.ok:
                        st.success(resultado.mensaje)
                    else:
                        st.error(resultado.mensaje)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Error al registrar la evidencia: {exc}")

        st.divider()
        st.subheader("Evidencia manual registrada")
        registros = manual_mod.listar_manuales(pipeline)
        if not registros:
            st.info("Todavía no hay evidencia registrada manualmente.")
        else:
            df = pd.DataFrame(registros)
            st.dataframe(
                df[
                    [
                        "documento",
                        "tipo_documento",
                        "ambito_principal",
                        "chunks",
                        "caracteres",
                        "indexado",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Para corregir la clasificación o dar de baja una evidencia, vaya a la vista "
                "«Inventario y edición del corpus»."
            )

        st.divider()
        st.subheader("Comprobar que la evidencia es recuperable")
        st.caption(
            "Antes de lanzar el diagnóstico, comprueba que el texto registrado aparece entre los "
            "fragmentos recuperados: si no aparece, el LLM no podrá citarla."
        )
        consulta = st.text_input(
            "Consulta de prueba",
            value="",
            placeholder="La organización debe establecer los objetivos del sistema integrado",
            key="consulta_prueba",
        )
        if consulta.strip():
            from mvp_sig.knowledge.vectorstore import VectorStore

            with st.spinner("Buscando..."):
                try:
                    encontrados = pipeline.store.buscar(
                        VectorStore.EVIDENCIAS, consulta, k=5, score_min=0.0
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Error en la búsqueda: {exc}")
                    encontrados = []
            if encontrados:
                for i, frag in enumerate(encontrados, start=1):
                    meta = frag.metadatos
                    st.markdown(
                        f"**{i}. {meta.get('documento', '?')}** · "
                        f"puntaje {frag.puntaje:.3f} · ámbito {meta.get('ambito', '?')} · "
                        f"origen {meta.get('origen', 'corpus')}"
                    )
                    st.caption(frag.texto[:300])
                    st.divider()
            else:
                st.warning("No se recuperó ningún fragmento con esa consulta.")


# --------------------------------------------------------------------------- #
# Pestaña: ingesta
# --------------------------------------------------------------------------- #
with tabs[5]:
    st.subheader("Pre-procesamiento e indexación de evidencias")
    st.caption(
        "Fase 3.1: extracción (PDF/DOCX/XLSX) → limpieza → segmentación → base vectorial, "
        "con registro documental y clasificación por ámbito del SIG."
    )
    ext = st.multiselect("Extensiones", [".pdf", ".docx", ".xlsx"], default=[".pdf", ".docx", ".xlsx"])
    limite_docs = st.number_input("Máximo de documentos (0 = todos)", min_value=0, max_value=500, value=0)

    if st.button("▶ Ejecutar ingesta", type="primary"):
        with st.spinner("Procesando documentos..."):
            try:
                resultado = pipeline.ingerir(
                    cfg["raiz"],
                    extensiones=tuple(ext),
                    limite=int(limite_docs) or None,
                )
                pipeline.indexar_requisitos()
                st.session_state["ingesta"] = resultado.to_dict()
                st.success(
                    f"Indexados {resultado.documentos_ok} documentos "
                    f"({resultado.chunks} fragmentos) en {resultado.segundos:.1f} s"
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Error en la ingesta: {exc}")

    if "ingesta" in st.session_state:
        datos = st.session_state["ingesta"]
        c = st.columns(4)
        c[0].metric("Documentos ok", datos["documentos_ok"])
        c[1].metric("Documentos con error", datos["documentos_fallidos"])
        c[2].metric("Fragmentos", datos["chunks"])
        c[3].metric("Tiempo (s)", datos["segundos"])
        df = pd.DataFrame(datos["registros"])
        if not df.empty:
            st.dataframe(
                df[["documento", "tipo", "tipo_documento", "ambito_principal", "ambitos", "chunks", "estado"]],
                use_container_width=True,
                hide_index=True,
            )
            if datos["advertencias"]:
                with st.expander("⚠️ Advertencias"):
                    for a in datos["advertencias"][:50]:
                        st.text(a)
