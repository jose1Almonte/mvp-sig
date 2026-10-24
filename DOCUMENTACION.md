# Documentación de operación · MVP de diagnóstico inteligente de SIG

Guía completa para **instalar, ejecutar y verificar** el MVP del sistema de diagnóstico
de Sistemas Integrados de Gestión (ISO 9001 / 14001 / 45001) basado en IA generativa + RAG.

- **Estado verificado**: 310 pruebas · 310 pasan en ~30 s · corpus de 272 documentos.
- **Entorno de referencia**: Windows 11 · Python 3.13.14 · Ollama 0.40.6 · 15.71 GB RAM.
- **Documento complementario**: `README.md` (arquitectura, resultados y limitaciones).

> Los comandos de esta guía se escriben para **Windows / PowerShell**. En Linux o macOS
> las equivalencias son `source .venv/bin/activate` y `export VAR=valor`.

---

## Índice

1. [Qué hace el proyecto](#1-qué-hace-el-proyecto)
2. [Requisitos previos](#2-requisitos-previos)
3. [Instalación](#3-instalación)
4. [Configuración](#4-configuración)
5. [Estructura de datos generada](#5-estructura-de-datos-generada)
6. [Ejecución: flujo completo](#6-ejecución-flujo-completo)
7. [Cómo ejecutar las pruebas](#7-cómo-ejecutar-las-pruebas)
8. [API REST](#8-api-rest)
9. [Interfaz web](#9-interfaz-web)
10. [Solución de problemas](#10-solución-de-problemas)
11. [Checklist de reproducibilidad](#11-checklist-de-reproducibilidad)

---

## 1. Qué hace el proyecto

El sistema recorre seis fases encadenadas y deja traza de cada una en
`Runtime.pasos_completados`:

```
ingesta → indexación → recuperación → generación → verificación → informe
```

| Fase | Qué ocurre | Artefacto |
|---|---|---|
| **Ingesta** | Extrae texto de PDF/DOCX/XLSX/XLS, limpia y segmenta | 12 669 fragmentos en ChromaDB |
| **Indexación** | Reconstruye las 154 unidades exigibles de las 3 normas | colección `iso_requisitos` |
| **Recuperación** | Búsqueda semántica por requisito normativo | top-`k` fragmentos con metadatos |
| **Generación** | El LLM emite veredicto + citas textuales | JSON validado |
| **Verificación** | Cada cita se re-chequea contra el fragmento recuperado | veredicto degradado si no se sostiene |
| **Informe** | Matriz de trazabilidad, KPIs y métricas | CSV · JSON · HTML · MD |

El **aporte central** es la fase de verificación: si el modelo afirma una cita que no
existe en el fragmento recuperado, el veredicto de cumplimiento se degrada
(`CUMPLE` → `CUMPLE_PARCIAL` → `NO_CUMPLE`). Es lo que separa este MVP de una simple
consulta a un LLM.

---

## 2. Requisitos previos

### 2.1 Software

| Componente | Versión verificada | Obligatorio |
|---|---|---|
| Python | 3.13.14 (mínimo 3.10) | sí |
| Ollama | 0.40.6 | sí |
| Git | cualquiera | no |

### 2.2 Modelos (descargados desde Ollama)

```bash
ollama pull llama3.1:8b        # modelo de chat  (~4.9 GB) — el prescrito por el tutor
ollama pull mxbai-embed-large  # embeddings     (~669 MB, 1024 dimensiones)
```

Modelos alternativos ya probados en el benchmarking: `llama3.2:latest` (3 B, ~2.0 GB).

### 2.3 Hardware

| Recurso | Mínimo | Recomendado | Nota |
|---|---|---|---|
| RAM | 8 GB | 16 GB | con `llama3.1:8b` cargado quedan ~4 GB libres |
| Disco | 2 GB | 5 GB | corpus + ChromaDB + informes |
| GPU | no requerida | cualquiera | el modelo corre en CPU (más lento) |

### 2.4 Corpus de evidencias

Por defecto el sistema resuelve el corpus **CIL ONG** incluido en
`Tesis\material de estudio\material de estudio_\Documentos para implementación, auditoría
y gerencia del SGI` (273 archivos: 162 DOCX · 80 XLSX · 28 PDF · 3 XLS heredados).

La ruta se resuelve en este orden (`mvp_sig/settings.py::resolver_corpus`):

1. variable de entorno `CORPUS_EVIDENCIAS`
2. ruta por defecto bajo `TESIS_ROOT`
3. alternativas `Evidencias\ejemplo\modificadas pdf` y `...\modificadas word`
4. búsqueda automática de una carpeta que empiece por *«Documentos para implementaci…»*

> Para usar **otro** corpus basta con `CORPUS_EVIDENCIAS` (ver §4).

### 2.5 Semilla normativa

Los tres JSON de `data/seed/iso_fragments/` (395 fragmentos: 106 + 129 + 160) son el
material de entrada del corpus normativo. **Ya vienen en el repositorio**: no hay que
descargarlos.

---

## 3. Instalación

### 3.1 Opción A — entorno virtual (recomendado)

```powershell
cd "C:\Users\josey\OneDrive\Desktop\Tesis\programacion\mvp-sig"

python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 Opción B — Python del sistema

Si no se quiere usar un entorno virtual (así está configurada esta máquina):

```powershell
cd "C:\Users\josey\OneDrive\Desktop\Tesis\programacion\mvp-sig"
python -m pip install -r requirements.txt
```

Versiones efectivamente instaladas y verificadas contra `requirements.txt`:

```
pytest==9.1.1          chromadb==1.5.9      fastapi==0.139.0     uvicorn==0.47.0
streamlit==1.66.0      ollama==0.6.1        requests==2.32.5     pydantic==2.12.5
pypdf==6.9.2           python-docx==1.2.0   openpyxl==3.1.5      xlrd==2.0.2
olefile==0.47          numpy==2.4.2         pandas==2.3.3
```

### 3.3 Verificación de la instalación

```powershell
python -c "import chromadb, fastapi, streamlit, docx, openpyxl, xlrd, pypdf; print('dependencias OK')"
python -m pytest --collect-only -q | Select-Object -Last 3   # debe listar 310 pruebas
```

### 3.4 Arrancar Ollama

```powershell
ollama serve            # deja el servidor escuchando en 127.0.0.1:11434
```

En Windows, la app de escritorio de Ollama ya levanta el servicio; para trabajar por
consola conviene cerrar la app o usar `ollama serve` en una terminal aparte.

Comprobación:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags | ConvertTo-Json -Depth 3
```

Debe listar `llama3.1:8b` y `mxbai-embed-large`.

---

## 4. Configuración

Todo se controla por variables de entorno. Copiar `.env.example` a `.env` y ajustar lo
que se necesite; **todos los valores tienen un default funcional**, así que `.env` es
opcional.

```powershell
copy .env.example .env
```

### 4.1 Variables principales

| Variable | Default | Efecto |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | servidor de Ollama. **Usar el literal IPv4** (ver §10.1) |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | modelo de embeddings |
| `EMBEDDING_DIM` | `1024` | debe coincidir con la dimensión real del modelo |
| `CHAT_MODEL` | `llama3.1:8b` | modelo de chat |
| `LLM_PROVIDER` | `ollama` | `ollama` · `openai` · `anthropic` · `openrouter` |
| `LLM_TEMPERATURE` | `0.0` | 0 para respuestas reproducibles |
| `LLM_MAX_TOKENS` | `1200` | tope de tokens por respuesta |
| `CORPUS_EVIDENCIAS` | corpus CIL ONG | carpeta de documentación a indexar |
| `TESIS_ROOT` | `C:\Users\josey\OneDrive\Desktop\Tesis` | raíz para resolver rutas por defecto |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `200` | segmentación de la evidencia |
| `TOP_K` | `5` | fragmentos recuperados por requisito |
| `SCORE_MIN` | `0.15` | umbral de similitud coseno |
| `CONTEXT_CHARS` | `6000` | presupuesto de contexto enviado al LLM |
| `OLLAMA_CONNECT_TIMEOUT` | `10` | segundos de espera al conectar |
| `HTTP_RETRIES` | `3` | reintentos ante fallos de red transitorios |

### 4.2 Proveedores en la nube (intercambiables)

El sistema no está atado a Ollama. Para usar una API en la nube basta con cambiar tres
variables en `.env`:

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

También están soportados `anthropic` (`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`) y
`openrouter` (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`).

> Los **embeddings** siguen siendo locales en todos los casos: sólo el modelo de chat es
> intercambiable, porque el corpus ya está vectorizado con `mxbai-embed-large`.

### 4.3 Comprobar la configuración efectiva

```powershell
python run.py estado
```

```json
{
  "base_vectorial": { "requisitos": 154, "evidencias": 12669,
                      "embeddings": "ollama", "modelo_embeddings": "mxbai-embed-large" },
  "llm": { "proveedor": "ollama", "modelo": "llama3.1:8b", "temperatura": 0.0 }
}
```

---

## 5. Estructura de datos generada

`data/` es la única carpeta que el sistema escribe. Todo lo demás es código.

```
data/
├── seed/iso_fragments/          # (entradas) JSON de las 3 normas — NO se regenera
│   ├── ISO 45001_2018_fragmentos.json
│   ├── UNE-EN ISO 14001_2015_fragmentos.json
│   └── UNE-EN ISO 9001 2015_fragmentos.json
├── seed/arbol_oficial.json      # árbol canónico de cláusulas extraído de los PDF oficiales
├── storage/
│   ├── chroma/                  # base vectorial persistente (2 colecciones)
│   │   ├── iso_requisitos/      #   154 unidades exigibles
│   │   └── evidencias/          #   12 669 fragmentos del corpus
│   └── cache/
├── catalog/
│   ├── catalogo_evidencias.json # inventario del corpus ingerido (273 registros)
│   └── exclusiones.json         # documentos retirados del diagnóstico (persistente)
├── evidencias_manuales/         # evidencia registrada a mano (auditable en disco)
└── reports/                     # informes exportados
    ├── diagnostico_<timestamp>.{csv,json,html}
    ├── matriz_kpis.{csv,json}
    ├── benchmark.{csv,md,json}
    ├── costo_efectividad.md
    ├── experimento_bd_vectorial.json
    └── experimento_embeddings.json
```

### 5.1 Cómo se borra y se regenera

```powershell
# Reinicio total de la base vectorial (se reconstruye con `ingesta`)
Remove-Item -Recurse -Force data\storage\chroma
Remove-Item -Force data\catalog\catalogo_evidencias.json
Remove-Item -Force data\catalog\exclusiones.json   # si se quieren revocar las exclusiones
python run.py ingesta
```

> `exclusiones.json` **no** se borra al reindexar: es justamente lo que hace que una
> ingesta completa respete los documentos que el auditor retiró.

### 5.2 Catálogo documental

`data/catalog/catalogo_evidencias.json` es el inventario de lo ingerido: un registro por
documento con ruta, hash SHA-256, tipo, ámbitos y número de fragmentos. Cada registro
lleva además dos identificadores derivados de la ruta —`id` (12 hexadecimales, seguro en
una URL) y `clave` (legible, `nombre#resumen`)— porque el corpus contiene 17 pares de
documentos **homónimos** y el nombre no basta para distinguirlos.

```powershell
python -c "import json;from pathlib import Path;c=json.loads(Path('data/catalog/catalogo_evidencias.json').read_text(encoding='utf-8'));print(c['documentos_ok'],'ok /',c['documentos_fallidos'],'fallidos')"
```

### 5.2b Exclusiones persistentes

`data/catalog/exclusiones.json` guarda los documentos retirados del diagnóstico. Cada
entrada conserva la `clave`, el `id`, la ruta, el motivo, la fecha y una **copia congelada
de los metadatos** que tenía el documento al excluirlo, de modo que al reincorporarlo
recupera la clasificación que el auditor había corregido:

```json
{
  "documentos": [
    {
      "id": "2cab97bd9138",
      "clave": "1. Organigrama.docx#2cab97",
      "documento": "1. Organigrama.docx",
      "ruta": "C:\\…\\1. Organigrama.docx",
      "excluido": "2026-10-22T11:20:00",
      "motivo": "duplicado del manual de calidad",
      "metadatos": { "tipo_documento": "documento", "ambitos": ["calidad"], "chunks": 1, "…": "…" }
    }
  ],
  "actualizado": "2026-10-22T11:20:00"
}
```

`Pipeline.ingerir` lee ese archivo y omite las rutas excluidas, así que volver a procesar
el corpus entero **no resucita** un documento retirado. El archivo original nunca se
borra: excluir no es dar de baja.

### 5.3 Árbol canónico de cláusulas

`data/seed/arbol_oficial.json` contiene, para cada norma, la lista de cláusulas con su
título oficial y la ruta del PDF de origen. Es la referencia contra la que se valida la
atribución de cláusulas (comprobación **F** de la coherencia).

Se regenera desde los PDF oficiales:

```powershell
python scripts\generar_arbol_oficial.py
```

Si el archivo no está, la comprobación F se omite (no falla) y el resto del sistema
funciona con normalidad.

### 5.4 Evidencia registrada a mano

`data/evidencias_manuales/` guarda el archivo de cada evidencia registrada a mano: el
texto pegado se materializa como `.txt` y el archivo subido se copia tal cual. El
motivo es auditable: **una evidencia que no existe en ningún archivo no es evidencia**,
el sistema tiene que poder citarla, reindexarla y mostrar su origen.

La carpeta no se borra al reindexar el corpus: la ingesta completa recrea la colección
vectorial, pero `Pipeline.ingerir` reindexa al final la evidencia manual que hubiera.

---

## 6. Ejecución: flujo completo

Orden recomendado para una corrida limpia. Los pasos 1–3 no necesitan el LLM; del 4 en
adelante sí.

### Paso 0 — Verificar Ollama

```powershell
ollama list
```

### Paso 1 — Ingesta del corpus

```powershell
python run.py ingesta
```

- Extrae, limpia, segmenta y vectoriza los 273 documentos.
- Recrea las colecciones `evidencias` (12 669 fragmentos) e `iso_requisitos` (154).
- Escribe `data/catalog/catalogo_evidencias.json`.
- **Duración medida: ≈ 322 s** (5–6 min).

Variantes:

```powershell
python run.py ingesta --limite 20                 # prueba rápida con 20 documentos
python run.py ingesta --ruta "D:\mi\corpus"       # otro corpus
python run.py ingesta --extensiones .pdf .docx     # sólo certain extensiones
```

> ⚠️ **No abra la base vectorial desde otro proceso mientras corre la ingesta.** La
> colección queda invalidada y la corrida muere con `NotFoundError`. Ver §10.3.

### Paso 2 — Comprobar el estado

```powershell
python run.py estado
```

Debe mostrar `requisitos: 154`, `evidencias: 12669`, `catalogo: 272`.

### Paso 3 — Verificar la coherencia de la atribución de cláusulas

```powershell
python scripts\medir_coherencia.py
```

Re-deriva de forma independiente los anclajes de cada requisito sobre el documento
continuo y comprueba el re-anclaje, los encabezados, la numeración, la cobertura y la
unicidad de identificadores. Referencia actual: **874/874 → 100.0 %**, de las cuales
**181/181** corresponden a la comprobación **F** (conformidad con el árbol oficial de las
tres normas).

### Paso 3b — Registrar evidencia que no viene del corpus

Opcional, pero es el paso que explica por qué la ingesta completa (~6 min) no hay que
repetir cada vez que llega un acta nueva.

```powershell
# Texto pegado (un acta, un correo, el acta de una reunión)
python run.py evidencia --nombre "Acta de revisión por la dirección 2026-02" `
                        --texto "La dirección revisó el sistema integrado de gestión…" `
                        --ambitos calidad integral --tipo acta

# Archivo suelto (PDF, DOCX, XLSX, XLS, TXT)
python run.py evidencia --archivo "D:\evidencias\informe-ambiental.pdf" --ambitos ambiente

# Inventario y baja
python run.py evidencia --listar
python run.py evidencia --listar --origen corpus      # sólo el corpus
python run.py evidencia --eliminar "Acta de revisión por la dirección 2026-02.txt"
```

Lo que hace y lo que **no** hace:

| Aspecto | Comportamiento |
|---|---|
| Indexado | **Incremental**: añade los fragmentos del documento; la colección de evidencias **no** se recrea |
| Materialización | el texto se guarda como `.txt` en `data/evidencias_manuales/`; el archivo se copia tal cual |
| Metadatos | los decide quien registra (ámbito, tipo documental, organización, código); si no, se infieren del nombre y del texto |
| Colisión con el corpus | si el nombre ya existe en el corpus, se registra como «… (manual)» |
| Re-registro | con el mismo nombre **actualiza** la evidencia (idempotente, no duplica) |
| Ingesta completa posterior | la evidencia manual se **reindexa automáticamente** al terminar |
| Baja | borra los fragmentos, la entrada del catálogo y el archivo; el corpus nunca se borra desde la interfaz |

En la interfaz web (pestaña **📥 Evidencia**) hay además un cuadro de
**comprobación de recuperabilidad**: antes de lanzar el diagnóstico, se consulta el
índice y se verifica que el fragmento de la evidencia aparece entre los recuperados. Si
no aparece, el LLM no podrá citarla.

### Paso 3c — Corregir la clasificación del corpus

La clasificación de ámbitos, tipo documental, organización y código se infiere del nombre
y del texto. Con 272 documentos reales hay inferencias que fallan, y rehacer la ingesta
para arreglar una etiqueta cuesta ~6 minutos y 12 669 fragmentos. Estas cuatro
operaciones son **quirúrgicas**: tocan un solo documento.

```powershell
# 1) Localizar el documento y su id
python run.py evidencia --listar --origen corpus

# 2) Corregir la clasificación (los campos no indicados se conservan)
python run.py evidencia --documento 2cab97bd9138 --ambitos calidad --tipo documento `
                        --organizacion "CIL ONG" --codigo "SIG-ORG-01"

# 3) Releer el archivo (p. ej. tras corregir el .docx) conservando la clasificación
python run.py evidencia --reindexar 2cab97bd9138

# 4) Retirar del diagnóstico sin borrar el archivo, y devolverlo después
python run.py evidencia --excluir 2cab97bd9138 --motivo "duplicado del manual de calidad"
python run.py evidencia --reincorporar 2cab97bd9138
```

| Operación | Efecto en el índice | Efecto en el catálogo | Archivo en disco |
|---|---|---|---|
| Corregir clasificación | reindexa **sólo** ese documento | actualiza los campos indicados | intacto |
| Reindexar | sustituye sus fragmentos | actualiza hash y recuento; conserva la clasificación | intacto |
| Excluir | elimina sus fragmentos | lo saca del catálogo y lo anota en `exclusiones.json` | **se conserva** |
| Reincorporar | vuelve a indexarlo | vuelve al catálogo con la clasificación congelada | intacto |
| Dar de baja (sólo manual) | elimina sus fragmentos | lo saca del catálogo | **se borra** |

Todas las operaciones aceptan el `id`, la `clave` (`nombre#resumen`) o el nombre del
documento. **Si el nombre es ambiguo, la orden falla** y devuelve los candidatos: el
corpus tiene 17 pares de documentos homónimos y elegir uno al azar sería peor que
negarse.

```text
Hay 2 documentos llamados 'Revisión por la Dirección_CIL ONG.docx'.
Indique el id de uno de ellos: … [74ca3ecc2aa2], … [ab16fe9afa85]
```

**La exclusión persiste.** Se guarda en `data/catalog/exclusiones.json` y
`Pipeline.ingerir` la respeta: una ingesta completa no devuelve al índice un documento
que el auditor retiró. Para revocarla, `--reincorporar` o borrar la entrada del archivo.

### Paso 4 — Diagnóstico de cumplimiento

```powershell
python run.py diagnostico --limite 10 --organizacion "METUNIMET"
```

Ejecuta requisito por requisito: recuperación → prompt → LLM → verificación de citas.
Imprime el veredicto por requisito, la tasa de cumplimiento, la trazabilidad verificada y
la latencia media, y exporta `diagnostico_<timestamp>.{csv,json,html}`.

Opciones:

```powershell
python run.py diagnostico --normas ISO45001            # sólo una norma
python run.py diagnostico --ambitos calidad ambiente     # sólo dos ámbitos
python run.py diagnostico --top-k 8                     # más evidencia por requisito
python run.py diagnostico --sin-resumen                 # sin el resumen ejecutivo
python run.py diagnostico --proveedor openai --modelo gpt-4o-mini
```

Sólo la matriz de trazabilidad, sin generar informe:

```powershell
python run.py matriz --limite 20
```

### Paso 5 — Matriz de indicadores (KPI)

```powershell
python run.py kpis
```

Genera `matriz_kpis.csv` / `.json` con 37 indicadores y su análisis de consistencia
(redundancias potenciales, cobertura por norma y ámbito, frecuencias).

### Paso 6 — Métricas de recuperación sobre el gold set

```powershell
python run.py metricas --k 5
```

Reporta P@k, R@k, MRR y nDCG en dos niveles: **fragmento** (lo que devuelve Chroma) y
**documento** (lo que se cita como evidencia). Referencia actual @5:
P 0.230 / R 0.325 / MRR 0.266 / nDCG 0.333 (fragmento) y
P 0.213 / R 0.325 / MRR 0.268 / nDCG 0.327 (documento).

### Paso 7 — Experimentos de recuperación

```powershell
python scripts\experimento_recuperacion.py
python scripts\experimento_recuperacion.py --k 5 10 20 50 100
```

Sensibilidad de la recuperación al número de fragmentos y comparación de la recuperación
densa frente a la híbrida (fusión RRF).

### Paso 7b — Base de datos vectorial: latencia y filtrado (fase 3.3.a)

```powershell
python scripts\experimento_bd_vectorial.py
```

Mide la latencia de consulta (media, p50, p95) de ChromaDB y Qdrant sobre los mismos
12 669 vectores, con y sin filtro por metadatos, y calcula el solapamiento de resultados
entre ambos motores. Escribe `data/reports/experimento_bd_vectorial.json`.

> Requiere `qdrant-client` (opcional): `pip install qdrant-client`. Sin él, el script mide
> sólo ChromaDB y lo declara en el informe.

### Paso 7c — Modelos de embeddings (fase 4.1)

```powershell
python scripts\experimento_embeddings.py
```

Reindexa el corpus con un modelo de embeddings alternativo (`nomic-embed-text`, multilingüe)
en una base temporal y compara los indicadores de recuperación con los del modelo en
producción (`mxbai-embed-large`). Escribe `data/reports/experimento_embeddings.json`.

> Requiere el modelo alternativo descargado: `ollama pull nomic-embed-text`.
> Tarda ≈ 25 min (reindexa 12 669 fragmentos) y no toca la base de producción.

### Paso 8 — Benchmarking de modelos

```powershell
python run.py benchmark --modelos ollama/llama3.1:8b ollama/llama3.2:latest --limite 5
```

Compara motores sobre el mismo conjunto de requisitos en veredicto, trazabilidad
verificada, latencia, tokens y coste. Escribe `benchmark.csv`, `benchmark.md` y
`benchmark.json`, y además `costo_efectividad.md`: el cuadro que responde la pregunta de
investigación nº 4 del anteproyecto («¿cuál es el modelo más costo-efectivo?»), con el
precio de referencia de cada modelo y el coste estimado de un diagnóstico completo
(154 requisitos).

Para ejecutar **la comparativa completa del anteproyecto** (los siete modelos nombrados en
la fase 3.3.c más los dos abiertos del MVP):

```powershell
python run.py benchmark --limite 5 --modelos `
  ollama/llama3.1:8b ollama/llama3.2 ollama/gpt-oss:120b-cloud `
  ollama/deepseek-v3 ollama/mistral-large `
  openai/gpt-4o-mini openai/gpt-4o `
  anthropic/claude-3-5-sonnet-latest anthropic/claude-3-5-opus-latest
```

Los modelos que no pueden ejecutarse en la máquina se declaran como tales, con el motivo
(`falta la clave de API`, `el modelo no está instalado en Ollama`) y su coste **estimado**
a partir del consumo de tokens medido en local.

### Paso 8b — Orquestador n8n (fase 3.4.b)

```powershell
python run.py n8n                          # estado del flujo y del webhook
python run.py diagnostico --notificar-n8n  # publica el informe en N8N_WEBHOOK
```

El flujo importable está en `workflows/diagnostico_sig_n8n.json`: en n8n, «Workflows →
Import from File». El flujo es el que **conduce** el diagnóstico (recibe un webhook,
llama a `POST /diagnostico` de la API del MVP y ramifica por veredicto). A la inversa,
`--notificar-n8n` hace que el MVP publique el informe terminado en `N8N_WEBHOOK` para
encadenar pasos posteriores. La notificación es *best-effort*: si el orquestador no
responde, el diagnóstico no se pierde.

### Paso 9 — Levantar los servicios

```powershell
python run.py api --puerto 8000     # API en http://127.0.0.1:8000/docs
python run.py ui  --puerto 8501     # interfaz en http://127.0.0.1:8501
```

---

## 7. Cómo ejecutar las pruebas

### 7.1 Características de la suite

| Aspecto | Valor |
|---|---|
| Total de pruebas | **346** |
| Duración | ~30 s |
| Requiere Ollama | **no** |
| Requiere red | **no** |
| Requiere el corpus real | **no** (una prueba se salta si el catálogo no existe) |
| Escribe en `data/` | **no** — Chroma, el catálogo y la carpeta de manuales van a `tmp_path` |

La suite usa **embeddings deterministas de respaldo** (`HashEmbeddings`) y un
**proveedor de lenguaje simulado** (`LLMFalso`), definidos en `tests/conftest.py`. Por eso
es reproducible y no depende de que Ollama esté encendido.

### 7.2 Comandos

```powershell
# Suite completa
python -m pytest

# Con detalle de cada prueba
python -m pytest -v

# Sólo un archivo
python -m pytest tests\test_requirements.py -v

# Sólo una clase
python -m pytest tests\test_requirements.py::TestCasosLimite -v

# Sólo una prueba
python -m pytest tests\test_engine.py::TestVerificacionDeCitas::test_cita_inventada_degrada_el_veredicto -v

# Por nombre (subcadena)
python -m pytest -k "coherencia"

# Listar sin ejecutar
python -m pytest --collect-only -q

# Parar en el primer fallo y reintentar sólo los que fallaron
python -m pytest -x
python -m pytest --lf

# Ver los 10 más lentos
python -m pytest --durations=10
```

`pytest.ini` ya define `addopts = -q --strict-markers` y filtra los `DeprecationWarning`
y `UserWarning` de las dependencias.

### 7.3 Qué cubre cada archivo

| Archivo | Pruebas | Cobertura |
|---|---|---|
| `tests/test_requirements.py` | 29 | Detección de cláusulas: sub-numeración, referencias cruzadas, títulos de anexo, enumeraciones pegadas, acrónimos, títulos anunciados por dos puntos, palabras partidas por el PDF, listas numeradas, NOTA, diagnóstico de rechazos. Segmentación, corpus de requisitos y coherencia. |
| `tests/test_text.py` | 26 | Normalización (acentos, mayúsculas), limpieza de ruido ISO, similitud, `contiene_frase` (base de la verificación de citas) y división de oraciones. |
| `tests/test_api.py` | 27 | Endpoints básicos, `VectorStore`, contrato del esquema de respuesta y diagnóstico end-to-end con pipeline simulado. |
| `tests/test_kpis_y_metricas.py` | 25 | Catálogo y matriz de KPIs, gold set (incluye que los documentos esperados existan en el corpus real), métricas de recuperación en los dos niveles y acuerdo inter-modelo. |
| `tests/test_edicion_corpus.py` | 36 | Edición del corpus: `id`/`clave` frente a homónimos, resolución de referencias (incluido el rechazo de nombres ambiguos), inventario, exclusión persistente frente a la ingesta completa, reincorporación con los metadatos congelados, corrección de metadatos sin perder los campos no indicados, reindexado de un archivo modificado y endpoints REST. |
| `tests/test_evidencia_manual.py` | 35 | Registro de evidencia manual: materialización del archivo, idempotencia, colisión de nombres con el corpus, **no recreación de la colección**, aislamiento entre documentos homónimos, baja selectiva, conservación tras la ingesta completa y endpoints REST. |
| `tests/test_ingestion.py` | 23 | Extractores PDF/DOCX/XLSX/XLS/TXT, `sniff_mime`, diagnóstico de contenedores OLE2, clasificación de ámbitos y catálogos. |
| `tests/test_llm_provider.py` | 21 | Parseo de JSON del LLM, estructura de la respuesta y los cuatro proveedores (Ollama, OpenAI, Anthropic, OpenRouter). |
| `tests/test_arbol_oficial.py` | 24 | Árbol canónico de las tres normas: extracción, carga, coincidencia de títulos y **comprobación F** de conformidad con las versiones oficiales. |
| `tests/test_n8n.py` | 15 | Integración con el orquestador n8n: notificación *best-effort*, payload del diagnóstico y validación del flujo exportable. |
| `tests/test_cleaner.py` | 17 | Limpieza de documentos, segmentación en bloques, verificación y pre-limpieza de citas. |
| `tests/test_costos.py` | 17 | Modelo de costes, cuadro de costo-efectividad (medición vs estimación) y motivos de indisponibilidad. |
| `tests/test_engine.py` | 14 | **Verificación de citas** (alucinación → degradación del veredicto), robustez del motor, corrida completa y métricas. |
| `tests/test_resiliencia.py` | 14 | Normalización de URL, sesión persistente, reintentos, volcado incremental y **aislamiento del catálogo**. |
| `tests/test_traceability.py` | 9 | Filas de la matriz y exportaciones CSV/JSON/HTML. |
| `tests/test_benchmark.py` | 7 | Corrida del benchmark y exportaciones. |
| `tests/test_ui_y_prompts.py` | 7 | Contrato de los prompts del auditor e interfaz de Streamlit. |

### 7.4 Las tres pruebas que sostienen el aporte metodológico

```powershell
python -m pytest tests\test_engine.py::TestVerificacionDeCitas -v
python -m pytest tests\test_requirements.py::TestCoherencia -v
python -m pytest tests\test_resiliencia.py::TestAislamientoDelCatalogo -v
```

1. **`TestVerificacionDeCitas`** — comprueba que una cita inexistente degrada el
   veredicto (`CUMPLE` → `CUMPLE_PARCIAL`, confianza ≤ 0.40) y que una cita real lo
   sostiene.
2. **`TestCoherencia`** — verifica que la atribución de cláusulas sea internamente
   consistente (re-anclaje, encabezados, numeración, cobertura, identificadores únicos).
3. **`TestAislamientoDelCatalogo`** — falla si una prueba sobrescribe
   `data/catalog/catalogo_evidencias.json`. Existe porque una versión anterior del
   código escribía el catálogo real desde las pruebas y destruía el inventario del
   corpus ingerido.

### 7.5 Cobertura de código (opcional)

`pytest-cov` no viene en `requirements.txt` porque es una herramienta de desarrollo:

```powershell
pip install pytest-cov
python -m pytest --cov=mvp_sig --cov-report=term-missing
python -m pytest --cov=mvp_sig --cov-report=html     # informe en htmlcov/index.html
```

### 7.6 Escribir una prueba nueva

1. Localice la clase de pruebas del módulo correspondiente en `tests/`.
2. Use los fixtures ya definidos en `tests/conftest.py`:

   | Fixture | Qué aporta |
   |---|---|
   | `store` | ChromaDB temporal con embeddings hash (`tmp_path/chroma`) |
   | `store_con_evidencias` | el mismo store con 2 documentos de evidencia |
   | `llm` | proveedor de lenguaje simulado, con `llm.llamadas` para inspeccionar los prompts |
   | `embeddings` | `HashEmbeddings` determinista |
   | `requisitos_ejemplo` | dos requisitos normativos sintéticos |

3. **Nunca** escriba en `data/`: use `tmp_path` para todo artefacto.
4. Si la prueba necesita el corpus real, use `pytest.skip()` cuando no exista, como hace
   `test_los_documentos_esperados_existen_en_el_corpus_real`.

```powershell
python -m pytest tests\test_nuevo.py -v
python -m pytest --lf --tb=long     # reintentar los fallos con traza completa
```

---

## 8. API REST

```powershell
python run.py api --host 127.0.0.1 --puerto 8000
# o directamente:
python -m uvicorn mvp_sig.api.main:app --host 127.0.0.1 --port 8000
```

Documentación interactiva: **http://127.0.0.1:8000/docs** (Swagger) y `/redoc`.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | comprobación de vida |
| GET | `/estado` | estado de la base vectorial y del LLM |
| GET | `/proveedores` | inventario de motores y su disponibilidad real |
| GET | `/normas` | catálogo de normas soportadas |
| GET | `/docs-json` | especificación OpenAPI |
| GET | `/catalogo` | catálogo documental ingerido |
| GET | `/requisitos` | requisitos indexados (filtro por norma/ámbito) |
| POST | `/ingesta` | procesa e indexa un corpus |
| GET | `/evidencias` | **inventario completo** (corpus + manual + excluidas) |
| GET | `/evidencias/manuales` | sólo la evidencia registrada a mano |
| POST | `/evidencias` | registra evidencia a partir de un texto pegado |
| POST | `/evidencias/archivo` | registra evidencia a partir de un archivo (multipart) |
| PUT | `/evidencias/{documento}` | corrige la clasificación de un documento y lo reindexa |
| POST | `/evidencias/{documento}/reindexar` | relee el archivo origen conservando los metadatos |
| POST | `/evidencias/{documento}/excluir` | retira el documento del diagnóstico (conserva el archivo) |
| POST | `/evidencias/{documento}/reincorporar` | devuelve al diagnóstico un documento excluido |
| DELETE | `/evidencias/{documento}` | da de baja una evidencia manual (borra el archivo) |
| POST | `/diagnostico` | ejecuta el diagnóstico |
| GET | `/diagnostico/ultimo` | último diagnóstico, en memoria |
| GET | `/diagnostico/matriz.csv` | matriz de trazabilidad en CSV |
| GET | `/diagnostico/informe.html` | informe autocontenido |
| GET | `/diagnostico/informe.json` | informe en JSON |
| GET | `/kpis` | matriz de indicadores + análisis de consistencia |
| GET | `/metricas/recuperacion` | métricas del gold set (`?k=5`) |
| GET | `/metricas/diagnostico` | métricas del último diagnóstico |
| POST | `/benchmark` | comparación de modelos de lenguaje |

**El parámetro `{documento}` acepta tres formas:** el `id` corto (12 hexadecimales, seguro
para URL), la `clave` legible (`nombre#resumen`, que hay que escapar como `%23`) o el
nombre del documento **si es único**. Con un nombre ambiguo devuelve `404` con la lista
de candidatos, no elige.

`GET /evidencias` filtra por `origen` (`todos` · `corpus` · `manual`), por `q` (nombre,
código u organización) y por `incluir_excluidas`, y devuelve un `resumen` con los
contadores:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/evidencias?origen=corpus&q=organigrama" |
  ConvertTo-Json -Depth 5
```

### 8.1 Ejemplos

```powershell
# Estado
Invoke-RestMethod http://127.0.0.1:8000/estado | ConvertTo-Json -Depth 4

# Diagnóstico de 3 requisitos
$body = @{ limite = 3; organizacion = "METUNIMET"; con_resumen = $false } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/diagnostico -Method Post `
  -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6

# KPIs
Invoke-RestMethod http://127.0.0.1:8000/kpis | ConvertTo-Json -Depth 4

# Descargar la matriz de trazabilidad
Invoke-WebRequest http://127.0.0.1:8000/diagnostico/matriz.csv -OutFile matriz.csv

# Registrar evidencia a partir de un texto pegado
$ev = @{ texto = "La dirección revisó el sistema integrado de gestión…"
         nombre = "Acta de revisión 2026-02"; ambitos = @("calidad") } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/evidencias -Method Post `
  -ContentType "application/json" -Body $ev | ConvertTo-Json -Depth 4

# Registrar evidencia a partir de un archivo
Invoke-RestMethod -Uri http://127.0.0.1:8000/evidencias/archivo -Method Post `
  -Form @{ archivo = Get-Item "D:\evidencias\informe.pdf"; ambitos = "ambiente" } |
  ConvertTo-Json -Depth 4

# Inventario y baja
Invoke-RestMethod http://127.0.0.1:8000/evidencias | ConvertTo-Json -Depth 4
Invoke-RestMethod -Uri http://127.0.0.1:8000/evidencias/"Acta de revisión 2026-02.txt" `
  -Method Delete | ConvertTo-Json -Depth 4

# Corregir la clasificación de un documento del corpus (por id)
$meta = @{ ambitos = @("calidad"); tipo_documento = "documento"; codigo = "SIG-ORG-01" } |
  ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/evidencias/2cab97bd9138 -Method Put `
  -ContentType "application/json" -Body $meta | ConvertTo-Json -Depth 4

# Excluir del diagnóstico y reincorporar después
$motivo = @{ motivo = "duplicado del manual de calidad" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/evidencias/2cab97bd9138/excluir -Method Post `
  -ContentType "application/json" -Body $motivo | ConvertTo-Json -Depth 4
Invoke-RestMethod -Uri http://127.0.0.1:8000/evidencias/2cab97bd9138/reincorporar -Method Post |
  ConvertTo-Json -Depth 4
```

Con `curl`:

```bash
curl -X POST http://127.0.0.1:8000/diagnostico \
  -H "Content-Type: application/json" \
  -d '{"limite":3,"organizacion":"METUNIMET"}'
```

---

## 9. Interfaz web

```powershell
python run.py ui --puerto 8501
```

O directamente:

```powershell
python -m streamlit run mvp_sig\ui\app.py --server.port 8501
```

Seis pestañas:

| Pestaña | Contenido |
|---|---|
| **Diagnóstico** | selección de normas/ámbitos, ejecución y veredicto por requisito |
| **Matriz de trazabilidad** | tabla requisito → evidencia verificada, con exportación |
| **KPI** | matriz de indicadores por ámbito y análisis de consistencia |
| **Evaluación** | métricas del gold set y benchmarking de modelos |
| **Evidencia** | dos vistas: registrar evidencia manual (texto o archivo) y **editar el corpus** (inventario, corrección de metadatos, reindexado, exclusión y reincorporación) |
| **Ingesta** | estado del corpus y reindexación |

---

## 10. Solución de problemas

### 10.1 La ingesta se detiene sin error aparente

**Síntoma**: la consola se queda quieta durante minutos y parece colgada.

**Causa**: `OLLAMA_URL` con `localhost` o `http://[::1]:11434`. En Windows, `localhost`
resuelve primero a `::1` (IPv6); si Ollama sólo escucha en `127.0.0.1`, el SYN al IPv6 se
descarta en silencio y el socket queda en `SYN_SENT` durante todo el periodo de reintento
(~20 s por petición). Con los cientos de peticiones de la ingesta completa, esa espera se
acumulaba en **horas** de tiempo muerto.

**Solución**: usar el literal IPv4.

```ini
OLLAMA_URL=http://127.0.0.1:11434
```

`mvp_sig/utils/http.py` normaliza además cualquier URL con `localhost` y usa una sesión
persistente (*keep-alive*). Aun así, conviene fijar la variable explícitamente.

### 10.2 `NotFoundError` de ChromaDB durante la ingesta

**Causa**: otro proceso abrió la base vectorial persistente mientras corría la ingesta.
La colección queda invalidada.

**Solución**: cerrar cualquier proceso que use `data/storage/chroma` (otra API, la UI,
un `python -c` explorando la base) y volver a ejecutar la ingesta.

### 10.3 Caracteres raros en la salida de consola

**Síntoma**: `┌`, `─` o las tildes aparecen como `╬┤┬á` o `?`.

**Causa**: la consola de Windows usa `cp1252`.

**Solución**:

```powershell
$env:PYTHONIOENCODING="utf-8"
```

> Con rutas acentuadas pasadas como argumento, el problema es distinto: `argv` se
> corrompe. Localice el fichero **dentro** de Python en lugar de pasarlo por la línea de
> órdenes.

### 10.4 El LLM tarda mucho o se queda sin memoria

**Síntoma**: latencias altísimas, errores de memoria, el equipo se ralentiza.

**Causa**: `llama3.1:8b` en CPU con poca RAM libre.

**Solución**: usar `llama3.2:latest` (3 B, ~2.0 GB) o reducir `--limite`:

```powershell
python run.py diagnostico --limite 3 --modelo llama3.2:latest
```

También conviene cerrar la UI de Streamlit y la API mientras corre una ingesta pesada:
entre `mxbai-embed-large` (669 MB) y el modelo de chat (4.9 GB) la memoria es el
recurso escaso.

### 10.5 Un documento del corpus no se procesa

**Síntoma**: `documentos_fallidos: 1` y un aviso en la consola.

En el corpus CIL ONG hay **un `.docx` cifrado con contraseña**: no es posible extraerlo
sin la clave y el pipeline lo reporta como fallido, sin interrumpir el resto. Es el
comportamiento esperado (272/273). Un `.rar` (`Gestión HSEQ.rar`) tampoco se extrae: el
pipeline procesa PDF, DOCX, XLSX y XLS.

### 10.6 El diagnóstico devuelve `NO_CUMPLE` en todo

**Causa probable**: el modelo de chat no distingue la evidencia, o `TOP_K` es demasiado
bajo para el corpus.

**Diagnóstico**:

```powershell
python run.py diagnostico --limite 5 --top-k 10
python run.py metricas --k 10
```

En el benchmarking, `llama3.2:latest` devolvió `NO_CUMPLE` en el 100 % de los casos:
es una limitación del modelo de 3 B, no del pipeline. Con `llama3.1:8b` el mismo flujo
produce 80 % de cumplimiento.

### 10.7 `ModuleNotFoundError` al arrancar

**Causa**: el intérprete activo no es el del entorno donde se instalaron las
dependencias.

**Solución**:

```powershell
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Compruebe siempre con `python -m pip list`, no con `pip list`: pueden ser distintos.

### 10.8 Una exclusión «desapareció» tras mover el corpus

**Síntoma**: `data/catalog/exclusiones.json` contiene el documento, pero la ingesta lo
vuelve a indexar.

**Causa**: la exclusión se ancla a la **ruta absoluta** del archivo. Si se movió el corpus
de carpeta, de unidad o se renombró una carpeta intermedia, la ruta guardada ya no
coincide con la del archivo y `Pipeline.ingerir` deja de reconocerlo.

**Solución**:

```powershell
python run.py evidencia --listar --origen corpus   # localizar el documento
python run.py evidencia --excluir <id> --motivo "reasignada tras mover el corpus"
```

Y limpiar las entradas huérfanas:

```powershell
python -c "import json;from pathlib import Path;p=Path('data/catalog/exclusiones.json');d=json.loads(p.read_text(encoding='utf-8'));d['documentos']=[x for x in d['documentos'] if Path(x['ruta']).is_file()];p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')"
```

### 10.9 «Hay 2 documentos llamados …» al editar un documento

**Causa**: el corpus contiene **17 pares de documentos homónimos** (el mismo nombre de
archivo en dos carpetas). El sistema se niega a elegir uno al azar.

**Solución**: repetir la operación con el `id` que devuelve el error (o el que muestra
`python run.py evidencia --listar`):

```powershell
python run.py evidencia --documento 74ca3ecc2aa2 --ambitos calidad
```

---

## 11. Checklist de reproducibilidad

Para reproducir los resultados de la tesis desde cero:

```powershell
# 1. Entorno
ollama serve
ollama pull llama3.1:8b
ollama pull mxbai-embed-large
pip install -r requirements.txt
copy .env.example .env

# 2. Verificación de la suite (no necesita Ollama ni corpus)
python -m pytest
#    esperado: 346 passed

# 3. Ingesta (≈ 322 s)
python run.py ingesta

# 4. Comprobaciones del estado
python run.py estado                       # 154 requisitos · 12 669 evidencias · 272 catálogo
python scripts\medir_coherencia.py        # 874/874 → 100.0 % (F: 181/181)

# 5. Evidencia manual (opcional; indexado incremental, no reindexa el corpus)
python run.py evidencia --listar
python run.py evidencia --nombre "Acta de prueba" `
                        --texto "La dirección revisó el sistema integrado de gestión…" `
                        --ambitos calidad
python run.py evidencia --eliminar "Acta de prueba.txt"

# 6. Edición del corpus (opcional; corrige un documento sin reindexar el corpus)
python run.py evidencia --listar --origen corpus     # anota el id del documento
python run.py evidencia --documento <id> --ambitos calidad --codigo SIG-ORG-01
python run.py evidencia --excluir <id> --motivo "duplicado"
python run.py evidencia --reincorporar <id>

# 7. Resultados
python run.py diagnostico --limite 10 --organizacion "METUNIMET"
python run.py kpis                        # 37 indicadores
python run.py metricas                    # P@5 0.230 · R@5 0.325 (fragmento)
python run.py benchmark --modelos ollama/llama3.1:8b ollama/llama3.2:latest --limite 5
python scripts\experimento_recuperacion.py
```

Valores de referencia obtenidos en esta máquina (Windows 11 · Python 3.13.14 · Ollama
0.40.6 · 15.71 GB RAM):

| Medida | Valor |
|---|---|
| Documentos ingeridos | 272 / 273 |
| Fragmentos indexados | 12 669 |
| Requisitos exigibles | 154 (ISO9001 67 · ISO14001 38 · ISO45001 49) |
| Índice de coherencia | 100.0 % (874/874) |
| Recuperación @5 (fragmento) | P 0.230 · R 0.325 · MRR 0.266 · nDCG 0.333 |
| Recuperación @5 (documento) | P 0.213 · R 0.325 · MRR 0.268 · nDCG 0.327 |
| Indicadores KPI | 37 |
| Diagnóstico end-to-end | 100 % de trazabilidad verificada · 13.8 s de latencia media |
| Pruebas | 346 pasan en ~30 s |
