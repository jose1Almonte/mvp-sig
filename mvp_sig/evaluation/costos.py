"""Coste de referencia y análisis de costo-efectividad (objetivo 3.3.c).

El anteproyecto formula la pregunta de investigación nº 4: *«¿Cuál es el
modelo de lenguaje más costo-efectivo?»*.  Responderla exige tres cosas:

1. **medir** la calidad y el consumo de tokens de cada modelo sobre el mismo
   conjunto de requisitos (lo hace `benchmark.py`);
2. **conocer** el precio de cada modelo (lo que aporta este módulo);
3. **extrapolar** el coste a un diagnóstico completo, porque el coste por
   requisito es lo que decide si el sistema es viable en producción.

Los modelos abiertos ejecutados en local no tienen precio de API: su coste es
el del equipo (electricidad y amortización).  Los comerciales sí, y su precio
se aplica sobre los tokens realmente medidos.

Los precios de la tabla son **valores de referencia publicados por cada
proveedor**; el informe los declara como tales y no los presenta como una
medición.  Un diagnóstico completo son los 154 requisitos normativos del
catálogo vigente.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Catálogo de modelos
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModeloReferencia:
    """Un modelo de la comparativa, con su precio y su vía de ejecución."""

    clave: str
    nombre: str
    familia: str  # "abierta" | "comercial"
    proveedor: str  # vía de ejecución en el MVP
    modelo: str
    precio_entrada: float  # USD por 1M de tokens de entrada
    precio_salida: float  # USD por 1M de tokens de salida
    disponible_local: bool = False
    nota: str = ""

    @property
    def etiqueta(self) -> str:
        return f"{self.proveedor}/{self.modelo}"

    @property
    def coste_por_millon(self) -> float:
        """Coste de 1M de tokens de entrada + 1M de salida."""
        return self.precio_entrada + self.precio_salida


# Los siete modelos que nombra el anteproyecto (fase 3.3.c) más los dos
# modelos abiertos que sí están declarados en el MVP.
MODELOS: tuple[ModeloReferencia, ...] = (
    ModeloReferencia(
        clave="llama3.2",
        nombre="Llama 3.2",
        familia="abierta",
        proveedor="ollama",
        modelo="llama3.2",
        precio_entrada=0.0,
        precio_salida=0.0,
        disponible_local=True,
        nota="Ejecutado en local; el coste es el del equipo, no de API.",
    ),
    ModeloReferencia(
        clave="llama3.1:8b",
        nombre="Llama 3.1 8B",
        familia="abierta",
        proveedor="ollama",
        modelo="llama3.1:8b",
        precio_entrada=0.0,
        precio_salida=0.0,
        disponible_local=True,
        nota="Ejecutado en local.",
    ),
    ModeloReferencia(
        clave="gpt-oss-120b",
        nombre="GPT-OSS 120B",
        familia="abierta",
        proveedor="ollama",
        modelo="gpt-oss:120b-cloud",
        precio_entrada=0.0,
        precio_salida=0.0,
        disponible_local=True,
        nota="Pesado abierto (MoE) servido por Ollama en la nube sin coste.",
    ),
    ModeloReferencia(
        clave="deepseek-v3",
        nombre="DeepSeek-V3",
        familia="abierta",
        proveedor="ollama",
        modelo="deepseek-v3",
        precio_entrada=0.27,
        precio_salida=1.10,
        disponible_local=False,
        nota="671B parámetros: no cabe en el equipo de evaluación.",
    ),
    ModeloReferencia(
        clave="mistral-large-2",
        nombre="Mistral Large 2",
        familia="abierta",
        proveedor="ollama",
        modelo="mistral-large",
        precio_entrada=2.00,
        precio_salida=6.00,
        disponible_local=False,
        nota="123B parámetros: no cabe en el equipo de evaluación.",
    ),
    ModeloReferencia(
        clave="gpt-4o-mini",
        nombre="GPT-4o mini",
        familia="comercial",
        proveedor="openai",
        modelo="gpt-4o-mini",
        precio_entrada=0.15,
        precio_salida=0.60,
        nota="Requiere OPENAI_API_KEY.",
    ),
    ModeloReferencia(
        clave="gpt-4o",
        nombre="GPT-4o",
        familia="comercial",
        proveedor="openai",
        modelo="gpt-4o",
        precio_entrada=2.50,
        precio_salida=10.00,
        nota="Requiere OPENAI_API_KEY.",
    ),
    ModeloReferencia(
        clave="claude-3-5-sonnet",
        nombre="Claude 3.5 Sonnet",
        familia="comercial",
        proveedor="anthropic",
        modelo="claude-3-5-sonnet-latest",
        precio_entrada=3.00,
        precio_salida=15.00,
        nota="Requiere ANTHROPIC_API_KEY.",
    ),
    ModeloReferencia(
        clave="claude-3-5-opus",
        nombre="Claude 3.5 Opus",
        familia="comercial",
        proveedor="anthropic",
        modelo="claude-3-5-opus-latest",
        precio_entrada=15.00,
        precio_salida=75.00,
        nota="Requiere ANTHROPIC_API_KEY.",
    ),
)

# Los siete modelos citados en el anteproyecto, en su orden.
CLAVES_ANTEPROYECTO = (
    "llama3.2",
    "deepseek-v3",
    "mistral-large-2",
    "gpt-4o-mini",
    "gpt-4o",
    "claude-3-5-sonnet",
    "claude-3-5-opus",
)


def buscar(clave: str) -> ModeloReferencia | None:
    """Localiza la referencia de un modelo por clave, modelo o nombre.

    Tolera la etiqueta de Ollama (``llama3.2:latest`` ~ ``llama3.2``), que es
    como aparecen los modelos en las corridas del benchmarking.
    """
    if not clave:
        return None
    objetivo = clave.lower().strip()
    for m in MODELOS:
        if (
            m.clave.lower() == objetivo
            or m.modelo.lower() == objetivo
            or m.nombre.lower() == objetivo
        ):
            return m
    base = objetivo.split(":")[0]
    for m in MODELOS:
        if m.clave.lower().split(":")[0] == base or m.modelo.lower().split(":")[0] == base:
            return m
    return None


def por_clave(clave: str) -> ModeloReferencia | None:
    for m in MODELOS:
        if m.clave == clave:
            return m
    return None


def ejecutar_modelos_anteproyecto() -> list[tuple[str, str]]:
    """Lista ``(proveedor, modelo)`` de los siete modelos del anteproyecto."""
    return [(m.proveedor, m.modelo) for m in MODELOS if m.clave in CLAVES_ANTEPROYECTO]


# --------------------------------------------------------------------------- #
# Cálculo de coste
# --------------------------------------------------------------------------- #
def estimar_coste(
    tokens_entrada: float,
    tokens_salida: float,
    referencia: ModeloReferencia | str,
) -> float:
    """Coste en USD de una llamada con el consumo de tokens indicado."""
    ref = referencia if isinstance(referencia, ModeloReferencia) else por_clave(referencia)
    if ref is None:
        raise KeyError(f"Modelo sin referencia de precio: {referencia}")
    return (
        tokens_entrada * ref.precio_entrada + tokens_salida * ref.precio_salida
    ) / 1_000_000


def coste_diagnosis_completo(
    tokens_entrada_por_requisito: float,
    tokens_salida_por_requisito: float,
    requisitos: int,
    referencia: ModeloReferencia | str,
) -> dict:
    """Coste de diagnosticar los ``requisitos`` requisitos con un modelo.

    El consumo por requisito es el medido en la corrida de referencia: el
    prompt es idéntico para todos los modelos, por lo que el número de
    tokens de entrada es comparable (la tokenización puede variar
    mínimamente entre modelos).
    """
    ref = referencia if isinstance(referencia, ModeloReferencia) else por_clave(referencia)
    if ref is None:
        raise KeyError(f"Modelo sin referencia de precio: {referencia}")
    t_in = tokens_entrada_por_requisito * requisitos
    t_out = tokens_salida_por_requisito * requisitos
    coste = estimar_coste(t_in, t_out, ref)
    return {
        "modelo": ref.nombre,
        "clave": ref.clave,
        "familia": ref.familia,
        "requisitos": requisitos,
        "tokens_entrada": round(t_in),
        "tokens_salida": round(t_out),
        "coste_usd": round(coste, 4),
        "coste_usd_por_requisito": round(coste / requisitos, 6) if requisitos else 0.0,
        "coste_usd_por_mil_requisitos": round(coste / requisitos * 1000, 3) if requisitos else 0.0,
    }


@dataclass
class FilaCostoEfectividad:
    """Fila del cuadro de costo-efectividad."""

    modelo: str
    etiqueta: str
    familia: str
    estado: str
    trazabilidad: float | None = None
    latencia_s: float | None = None
    tokens_in: float | None = None
    tokens_out: float | None = None
    coste_usd: float = 0.0
    coste_por_mil: float = 0.0
    nota: str = ""
    extras: dict = field(default_factory=dict)


def filas_costo_efectividad(
    corridas: list,
    requisitos_totales: int = 154,
    *,
    tokens_referencia: tuple[float, float] | None = None,
    solo_anteproyecto: bool = False,
) -> list[FilaCostoEfectividad]:
    """Construye el cuadro de costo-efectividad a partir de las corridas.

    Para los modelos **no ejecutados** (sin clave de API o sin hardware
    suficiente) se estima el coste con el consumo de tokens medido en las
    corridas que sí se ejecutaron, y se marca como estimación en la nota.
    """
    claves_anteproyecto = set(CLAVES_ANTEPROYECTO)

    # Consumo de referencia: media de los tokens medidos en las corridas ok.
    consumos: list[tuple[float, float]] = []
    for c in corridas:
        r = c.resumen()
        if r.get("estado") != "ok":
            continue
        consumos.append(
            (r.get("tokens_promedio_entrada", 0), r.get("tokens_promedio_salida", 0))
        )
    if tokens_referencia:
        t_in, t_out = tokens_referencia
    elif consumos:
        t_in = sum(c[0] for c in consumos) / len(consumos)
        t_out = sum(c[1] for c in consumos) / len(consumos)
    else:
        t_in, t_out = 0.0, 0.0

    ejecutados: set[str] = set()
    no_ejecutados: dict[str, str] = {}
    filas: list[FilaCostoEfectividad] = []

    for c in corridas:
        r = c.resumen()
        etiqueta = f"{c.proveedor}/{c.modelo}"
        ref = buscar(c.modelo) or buscar(c.proveedor) or _por_etiqueta(etiqueta)
        clave = ref.clave if ref else c.modelo

        # Una corrida que no terminó bien **no es una medición**: el modelo no
        # pudo ejecutarse en este entorno (falta la clave de API, no cabe en
        # la máquina, el proveedor no responde).  Se registra el motivo y su
        # coste se estima más abajo con el precio de referencia.
        if r.get("estado") != "ok":
            no_ejecutados[clave] = r.get("error") or c.error or "no se pudo ejecutar"
            if ref is None:
                filas.append(
                    FilaCostoEfectividad(
                        modelo=c.modelo,
                        etiqueta=etiqueta,
                        familia="-",
                        estado="no ejecutado",
                        nota=f"{no_ejecutados[clave]}. Sin precio de referencia: coste no estimable.",
                    )
                )
            continue

        ejecutados.add(clave)
        coste_real = float(r.get("costo_usd_total", 0) or 0)
        fila = FilaCostoEfectividad(
            modelo=ref.nombre if ref else c.modelo,
            etiqueta=etiqueta,
            familia=ref.familia if ref else "-",
            estado="ejecutado",
            trazabilidad=r.get("tasa_trazabilidad_verificada"),
            latencia_s=r.get("latencia_media_s"),
            tokens_in=r.get("tokens_promedio_entrada"),
            tokens_out=r.get("tokens_promedio_salida"),
            coste_usd=coste_real,
            nota=ref.nota if ref else "",
        )
        if requisitos_totales:
            fila.coste_por_mil = round(coste_real / requisitos_totales * 1000, 3)
        filas.append(fila)

    # Modelos del anteproyecto que no se pudieron ejecutar: coste estimado.
    for ref in MODELOS:
        if ref.clave in ejecutados:
            continue
        if solo_anteproyecto and ref.clave not in claves_anteproyecto:
            continue
        if t_in or t_out:
            coste = coste_diagnosis_completo(t_in, t_out, requisitos_totales, ref)
            coste_total = coste["coste_usd"]
            por_mil = coste["coste_usd_por_mil_requisitos"]
        else:
            coste_total = 0.0
            por_mil = 0.0
        nota = "Estimado con el consumo de tokens medido en local. " + ref.nota
        motivo = no_ejecutados.get(ref.clave)
        if motivo:
            nota += f" Motivo de no ejecución: {motivo}."
        filas.append(
            FilaCostoEfectividad(
                modelo=ref.nombre,
                etiqueta=ref.etiqueta,
                familia=ref.familia,
                estado="no ejecutado",
                coste_usd=coste_total,
                coste_por_mil=por_mil,
                nota=nota,
            )
        )
    return filas


def _por_etiqueta(etiqueta: str) -> ModeloReferencia | None:
    for m in MODELOS:
        if m.etiqueta == etiqueta:
            return m
    return None


def informe_markdown(
    filas: list[FilaCostoEfectividad],
    requisitos_totales: int = 154,
    *,
    tokens_referencia: tuple[float, float] | None = None,
) -> str:
    """Informe Markdown del cuadro de costo-efectividad."""
    lineas = [
        "# Costo-efectividad de los modelos de lenguaje",
        "",
        f"Diagnóstico completo = **{requisitos_totales} requisitos normativos** "
        "(catálogo vigente).",
        "",
    ]
    if tokens_referencia:
        t_in, t_out = tokens_referencia
        lineas += [
            f"Consumo de referencia medido en local: **{t_in:.0f} tokens de entrada** y "
            f"**{t_out:.0f} de salida por requisito**.",
            "",
        ]
    lineas += [
        "Las filas marcadas *ejecutado* son mediciones reales del MVP. Las marcadas "
        "*no ejecutado* son **estimaciones**: se aplica el precio de referencia del "
        "modelo al mismo consumo de tokens medido en local, ya que el prompt es "
        "idéntico para todos los modelos.",
        "",
        "| Modelo | Vía | Familia | Estado | Trazabilidad | Latencia (s) | "
        "Tokens in | Tokens out | Coste diagnosis (USD) | USD / 1000 req. |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in filas:
        lat = f"{f.latencia_s:.1f}" if f.latencia_s is not None else "-"
        tin = f"{f.tokens_in:.0f}" if f.tokens_in is not None else "-"
        tout = f"{f.tokens_out:.0f}" if f.tokens_out is not None else "-"
        traz = f"{f.trazabilidad * 100:.1f}%" if f.trazabilidad is not None else "-"
        lineas.append(
            f"| {f.modelo} | {f.etiqueta} | {f.familia} | {f.estado} | {traz} | {lat} | "
            f"{tin} | {tout} | {f.coste_usd:.4f} | {f.coste_por_mil:.3f} |"
        )

    lineas += ["", "## Notas", ""]
    vistos: set[str] = set()
    for f in filas:
        if f.nota and f.nota not in vistos:
            vistos.add(f.nota)
            lineas.append(f"- **{f.modelo}**: {f.nota}")

    # Conclusión redactada con las cifras del propio cuadro, no con cifras
    # escritas a mano: así el texto no puede desincronizarse de la tabla.
    locales = [f for f in filas if f.estado == "ejecutado" and f.coste_usd == 0.0]
    estimados = [f for f in filas if f.estado == "no ejecutado" and f.coste_usd > 0.0]
    lineas += [
        "",
        "## Conclusión",
        "",
        (
            f"Los {len(locales)} modelos ejecutados en el equipo tienen **coste de API "
            "nulo** y atacan el requisito de diagnóstico sin salida a internet; su límite "
            "es la calidad del veredicto y la latencia."
            if locales
            else "Los modelos ejecutados en el equipo tienen coste de API nulo."
        ),
    ]
    if estimados:
        barato = min(estimados, key=lambda f: f.coste_usd)
        caro = max(estimados, key=lambda f: f.coste_usd)
        lineas.append(
            f"Los modelos comerciales estiman el diagnóstico completo de "
            f"{requisitos_totales} requisitos entre **{barato.coste_usd:.2f} USD** "
            f"({barato.modelo}) y **{caro.coste_usd:.2f} USD** ({caro.modelo}), "
            f"con un máximo de {caro.coste_por_mil:.2f} USD por cada 1000 requisitos "
            f"diagnosticados. Sólo se justifican si el veredicto que producen es "
            f"sustantivamente mejor: dato que este MVP deja medido y no supuesto."
        )
    return "\n".join(lineas)
