"""Configuración central del MVP de diagnóstico de SIG (ISO 9001/14001/45001).

Todos los valores pueden sobreescribirse con variables de entorno o con un
archivo `.env` en la raíz del proyecto (formato KEY=VALUE).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Raíz del proyecto
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _load_dotenv(path: Path | None = None) -> None:
    """Carga un .env sencillo sin dependencias externas."""
    env_file = path or (PROJECT_ROOT / ".env")
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


# --------------------------------------------------------------------------- #
# Catálogo de normas
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NormaSpec:
    """Metadatos de una norma ISO soportada por el sistema."""

    key: str                 # identificador corto: ISO9001
    nombre_archivo: str      # nombre del PDF semilla
    fragmentos_json: str     # archivo de fragmentos pre-segmentados
    ambito: str              # calidad | ambiente | seguridad
    color: str


NORMAS: dict[str, NormaSpec] = {
    "ISO9001": NormaSpec(
        key="ISO9001",
        nombre_archivo="UNE-EN ISO 9001 2015",
        fragmentos_json="UNE-EN ISO 9001 2015_fragmentos.json",
        ambito="calidad",
        color="#2E7D32",
    ),
    "ISO14001": NormaSpec(
        key="ISO14001",
        nombre_archivo="UNE-EN ISO 14001_2015",
        fragmentos_json="UNE-EN ISO 14001_2015_fragmentos.json",
        ambito="ambiente",
        color="#1565C0",
    ),
    "ISO45001": NormaSpec(
        key="ISO45001",
        nombre_archivo="ISO 45001_2018",
        fragmentos_json="ISO 45001_2018_fragmentos.json",
        ambito="seguridad",
        color="#EF6C00",
    ),
}

# Mapeo de las claves de fragmento original -> identificador corto de norma
FRAGMENTO_A_NORMA: dict[str, str] = {
    "UNE-EN ISO 9001 2015": "ISO9001",
    "UNE-EN ISO 14001_2015": "ISO14001",
    "ISO 45001_2018": "ISO45001",
}

AMBITOS = ("calidad", "ambiente", "seguridad", "integral")


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Paths:
    root: Path = PROJECT_ROOT
    data: Path = DATA_DIR
    seed_fragments: Path = DATA_DIR / "seed" / "iso_fragments"
    storage: Path = DATA_DIR / "storage"
    chroma: Path = DATA_DIR / "storage" / "chroma"
    catalog: Path = DATA_DIR / "catalog"
    reports: Path = DATA_DIR / "reports"
    cache: Path = DATA_DIR / "storage" / "cache"
    # Evidencias registradas a mano (pegadas o subidas) desde la interfaz.
    # Se guardan como archivos para que la evidencia sea auditable en disco.
    manuales: Path = DATA_DIR / "evidencias_manuales"

    def ensure(self) -> None:
        for p in (
            self.data,
            self.storage,
            self.chroma,
            self.catalog,
            self.reports,
            self.cache,
            self.manuales,
        ):
            p.mkdir(parents=True, exist_ok=True)


PATHS = Paths()


# --------------------------------------------------------------------------- #
# Corpus de evidencias por defecto (CIL ONG)
# --------------------------------------------------------------------------- #
_TESIS_ROOT = Path(_env("TESIS_ROOT", r"C:\Users\josey\OneDrive\Desktop\Tesis"))

CORPUS_EVIDENCIAS_DEFAULT = _env(
    "CORPUS_EVIDENCIAS",
    str(
        _TESIS_ROOT
        / "material de estudio"
        / "material de estudio_"
        / "Documentos para implementación, auditoría y gerencia del SGI"
    ),
)

CORPUS_EVIDENCIAS_ALTERNATIVOS = [
    str(_TESIS_ROOT / "Evidencias" / "ejemplo" / "modificadas pdf"),
    str(_TESIS_ROOT / "Evidencias" / "ejemplo" / "modificadas word"),
]


def resolver_corpus() -> Path:
    """Devuelve el primer corpus de evidencias que exista en disco.

    Prioridad: variable de entorno -> ruta por defecto -> alternativas ->
    búsqueda automática bajo la raíz de la tesis.
    """
    candidatos = [Path(CORPUS_EVIDENCIAS_DEFAULT)]
    candidatos += [Path(p) for p in CORPUS_EVIDENCIAS_ALTERNATIVOS]
    for c in candidatos:
        if c.is_dir():
            return c

    # Búsqueda automática: cualquier carpeta "Documentos para implementación..."
    for base in (_TESIS_ROOT, _TESIS_ROOT / "material de estudio"):
        if not base.is_dir():
            continue
        for dirpath, dirnames, _ in os.walk(base):
            for d in dirnames:
                if d.lower().startswith("documentos para implementaci"):
                    return Path(dirpath) / d
    return candidatos[0]


CORPUS_EVIDENCIAS = resolver_corpus()

# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelSpec:
    # Se usa el literal IPv4: `localhost` resuelve primero a `::1` y, si el
    # servidor de Ollama sólo escucha en `127.0.0.1`, el SYN al IPv6 queda
    # colgado ~20 s por petición (ver `mvp_sig.utils.http`).
    ollama_url: str = _env("OLLAMA_URL", "http://127.0.0.1:11434")
    embedding_model: str = _env("EMBEDDING_MODEL", "mxbai-embed-large")
    chat_model: str = _env("CHAT_MODEL", "llama3.1:8b")
    embedding_dim: int = _env_int("EMBEDDING_DIM", 1024)
    temperature: float = _env_float("LLM_TEMPERATURE", 0.0)
    max_tokens: int = _env_int("LLM_MAX_TOKENS", 1200)
    request_timeout: int = _env_int("LLM_TIMEOUT", 300)
    connect_timeout: int = _env_int("OLLAMA_CONNECT_TIMEOUT", 10)
    http_retries: int = _env_int("HTTP_RETRIES", 3)


MODELS = ModelSpec()

LLM_PROVIDER = _env("LLM_PROVIDER", "ollama")
OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = _env("OPENROUTER_MODEL", "openai/gpt-4o-mini")

# --------------------------------------------------------------------------- #
# Pre-procesamiento
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IngestSpec:
    chunk_size: int = _env_int("CHUNK_SIZE", 1200)
    chunk_overlap: int = _env_int("CHUNK_OVERLAP", 200)
    min_chunk_chars: int = _env_int("MIN_CHUNK_CHARS", 80)
    max_chunk_chars: int = _env_int("MAX_CHUNK_CHARS", 3000)
    # Un encabezado/pie que aparece en más de este ratio de páginas se descarta.
    header_footer_ratio: float = _env_float("HEADER_FOOTER_RATIO", 0.35)
    # Longitud mínima del encabezado de un requisito ISO para considerarlo válido.
    requisito_min_chars: int = _env_int("REQUISITO_MIN_CHARS", 60)


INGEST = IngestSpec()


# --------------------------------------------------------------------------- #
# Recuperación / diagnóstico
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RetrievalSpec:
    top_k: int = _env_int("TOP_K", 5)
    # Umbral de similitud coseno para descartar fragmentos irrelevantes.
    score_min: float = _env_float("SCORE_MIN", 0.15)
    # Longitud del contexto (caracteres) enviado al LLM.
    context_chars: int = _env_int("CONTEXT_CHARS", 6000)


RETRIEVAL = RetrievalSpec()


# --------------------------------------------------------------------------- #
# Orquestador
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PipelineSpec:
    """Parámetros del orquestador end-to-end (equivalente al flujo n8n)."""

    pasos = (
        "ingesta",
        "indexacion_requisitos",
        "indexacion_evidencias",
        "consulta_requisito",
        "recuperacion_semantica",
        "generacion_llm",
        "verificacion_trazabilidad",
        "consolidacion_diagnostico",
    )
    n8n_webhook: str = _env("N8N_WEBHOOK", "")


PIPELINE = PipelineSpec()


@dataclass
class Runtime:
    """Estado mutable de la ejecución (lo que el orquestador va encadenando)."""

    pasos_completados: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def completar(self, paso: str, detalle: str = "") -> None:
        self.pasos_completados.append(paso)
        print(f"  [pipeline] {paso}" + (f" -> {detalle}" if detalle else ""), flush=True)

    def advertir(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  [aviso] {msg}", flush=True)
