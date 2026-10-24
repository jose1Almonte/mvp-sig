"""Cliente HTTP compartido para los proveedores locales (Ollama).

Centraliza tres decisiones que afectan a la estabilidad del pipeline:

1. **Preferencia por IPv4.** En Windows ``localhost`` resuelve primero a
   ``::1`` (IPv6). Si el servidor de Ollama escucha únicamente en
   ``127.0.0.1`` —caso habitual cuando lo levanta la app de escritorio—, el
   SYN al IPv6 se descarta en silencio y el socket queda en ``SYN_SENT``
   durante todo el periodo de reintento del sistema operativo (~20 s) antes
   de recurrir al IPv4. Con varios cientos de peticiones durante la ingesta
   del corpus completo, esa espera se acumula en horas de tiempo muerto.

2. **Sesión persistente (keep-alive).** Evita un handshake TCP por petición:
   la ingesta emite decenas de lotes de embeddings y cada uno abría antes una
   conexión nueva.

3. **Tiempos de espera diferenciados.** Un timeout de *conexión* corto hace
   fallar rápido un servicio caído (con mensaje claro) en lugar de colgar el
   proceso durante minutos sin traza, que es lo que hizo la corrida anterior
   parecer "muerta" sin llegar a producir ningún error.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit

#: Hosts que se resuelven a un literal IPv4 para evitar el penalizable
#: intento de conexión por IPv6 loopback.
_HOSTS_IPV4 = {
    "localhost": "127.0.0.1",
    "localhost.localdomain": "127.0.0.1",
    "ip6-localhost": "127.0.0.1",
}


def normalizar_url(url: str) -> str:
    """Reescribe el host de la URL a su literal IPv4 cuando es loopback.

    >>> normalizar_url("http://localhost:11434")
    'http://127.0.0.1:11434'
    >>> normalizar_url("http://ollama:11434")
    'http://ollama:11434'
    """
    if not url:
        return url
    partes = urlsplit(url)
    host = partes.hostname or ""
    destino = _HOSTS_IPV4.get(host.lower())
    if not destino:
        return url
    netloc = destino
    if partes.port:
        netloc = f"{destino}:{partes.port}"
    if partes.username:
        credenciales = partes.username
        if partes.password:
            credenciales = f"{credenciales}:{partes.password}"
        netloc = f"{credenciales}@{netloc}"
    return urlunsplit((partes.scheme, netloc, partes.path, partes.query, partes.fragment))


def timeout_conectivo(connect: int, read: int) -> tuple[int, int]:
    """Devuelve el par ``(conexión, lectura)`` que espera ``requests``."""
    return (int(connect), int(read))


def crear_sesion(
    url: str,
    *,
    timeout_conexion: int = 10,
    timeout_lectura: int = 600,
    reintentos: int = 3,
    backoff: float = 1.5,
) -> "requests.Session":
    """Crea una sesión HTTP persistente apuntando a un servidor local.

    La sesión se reutiliza para todas las peticiones (keep-alive) y reintenta
    ante fallos transitorios de conexión, con espera exponencial.
    """
    import requests
    from requests.adapters import HTTPAdapter

    destino = normalizar_url(url).rstrip("/")
    sesion = requests.Session()

    adaptador = HTTPAdapter(
        max_retries=0,  # el reintento se controla aquí, con mensajes claros
        pool_connections=4,
        pool_maxsize=8,
        pool_block=True,
    )
    sesion.mount("http://", adaptador)
    sesion.mount("https://", adaptador)

    sesion.headers.update({"Connection": "keep-alive"})

    # La URL normalizada se guarda para que las llamadas la reutilicen.
    sesion.normalized_base_url = destino  # type: ignore[attr-defined]
    sesion.timeout_config = (  # type: ignore[attr-defined]
        timeout_conectivo(timeout_conexion, timeout_lectura),
        reintentos,
        backoff,
    )
    return sesion


def pedir(
    sesion,
    metodo: str,
    ruta: str,
    *,
    json: dict | None = None,
    timeout: tuple[int, int] | None = None,
    reintentos: int | None = None,
    backoff: float | None = None,
):
    """Ejecuta una petición HTTP con reintentos y diagnóstico explícito.

    Ante un fallo devuelve el último error con el contexto de la URL, que es
    lo que permite distinguir "Ollama apagado" de "la red se cayó a mitad".
    """
    import requests

    base = getattr(sesion, "normalized_base_url", "").rstrip("/")
    url = f"{base}{ruta}" if ruta.startswith("/") else f"{base}/{ruta}"
    cfg_timeout = getattr(sesion, "timeout_config", ((10, 600), 3, 1.5))
    if timeout is None:
        timeout = cfg_timeout[0]
    intentos = reintentos if reintentos is not None else cfg_timeout[1]
    espera = backoff if backoff is not None else cfg_timeout[2]

    ultimo_error: Exception | None = None
    for intento in range(1, max(1, intentos) + 1):
        try:
            respuesta = sesion.request(metodo, url, json=json, timeout=timeout)
            respuesta.raise_for_status()
            return respuesta
        except requests.exceptions.RequestException as exc:
            ultimo_error = exc
            if intento < intentos:
                pausa = espera * (2 ** (intento - 1))
                print(
                    f"    [aviso] {url} falló ({exc.__class__.__name__}); "
                    f"reintento {intento}/{intentos - 1} en {pausa:.1f}s",
                    flush=True,
                )
                time.sleep(pausa)
    raise RuntimeError(
        f"Fallo de red al llamar a {url} tras {intentos} intentos: {ultimo_error}"
    ) from ultimo_error
