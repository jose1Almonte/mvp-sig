# MVP · Diagnóstico inteligente de Sistemas Integrados de Gestión (SIG)

> Sistema de diagnóstico de cumplimiento normativo **ISO 9001:2015 / ISO 14001:2015 /
> ISO 45001:2018** basado en **IA generativa + RAG**, con **matriz de trazabilidad
> requisito → evidencia verificada**.

Demostración funcional de la propuesta de tesis *"Propuesta de un sistema inteligente para
el diagnóstico de sistemas integrados de gestión (SIG) basados en normas ISO"* (José
Almonte, UNT). El MVP materializa la arquitectura descrita en el documento de arquitectura
del proyecto: **Llama-3 8B vía Ollama**, **ChromaDB**, **RAG**, **FastAPI/Flask** y
**Streamlit**.

> 📘 **[`DOCUMENTACION.md`](DOCUMENTACION.md)** — guía operativa completa: instalación,
> configuración, flujo de ejecución paso a paso, **cómo ejecutar las pruebas**,
> referencia de la API y solución de problemas.

---

## 1. La idea en una frase

Se ingestan las tres normas ISO y la documentación de la organización; se **recupera** la
evidencia relevante para cada requisito normativo; un LLM emite un **veredicto de
cumplimiento con cita textual**; y —el aporte central— **cada cita se re-verifica
contra el fragmento recuperado**. Si la evidencia declarada no existe, el veredicto de
cumplimiento **se degrada**. Ese es el control de *grounding* que distingue a este MVP de
una simple consulta a un LLM.

```
                    ┌──────────────┐
   Normas ISO  ───► │  Corpus de   │ ─┐
   (3 JSON semilla) │  requisitos  │  │      ┌──────────────┐
                    └──────────────┘  ├────► │  ChromaDB    │
                                         │      │  2 colecciones│
   Documentación  ─► [ Extracción ] ────┘      └──────┬───────┘
   de la organización  [ Limpieza ]                     │
   (PDF/DOCX/XLSX)   [ Segmentación ]                   │ búsqueda semántica
                                    ┌───────────────────┘
                                    ▼
                              ┌───────────┐   prompt con    ┌──────────────┐
                              │  LLM      │ ◄── contexto ── │  Requisito   │
                              │ (Ollama / │                 │  normativo   │
                              │  OpenAI / │                 └──────────────┘
                              │  Claude)  │
                              └─────┬─────┘
                                    │ veredicto + citas
                                    ▼
                    ┌───────────────────────────────────────┐
                    │  VERIFICACIÓN DE TRAZABILIDAD         │
                    │  ¿la cita existe en el fragmento?     │
                    │   SÍ → se sostiene el veredicto       │
                    │   NO → CUMPLE_PARCIAL / NO_CUMPLE     │
                    └───────────────┬───────────────────────┘
                                    ▼
              Matriz de trazabilidad (CSV · JSON · HTML) · KPIs · Métricas
                                    │
                                    ▼
                    ┌───────────────────────────────────────┐
                    │  ORQUESTADOR n8n (opcional)           │
                    │  flujo importable que conduce el     │
                    │  diagnóstico y encadena sus salidas   │
                    └───────────────────────────────────────┘
```

### Orquestación externa (n8n)

El anteproyecto define el flujo de trabajo como *«gestionado mediante un orquestador (ej.
n8n)»* y la fase 3.4.b pide integrarlo *«mediante una plataforma de automatización»*. El
MVP lo materializa en los dos sentidos:

| Sentido | Pieza | Uso |
|---|---|---|
| n8n **conduce** el flujo | `workflows/diagnostico_sig_n8n.json` | flujo importable: webhook → `POST /diagnostico` → ramificación por veredicto → respuesta |
| el MVP **notifica** a n8n | `mvp_sig/integrations/n8n.py` + `N8N_WEBHOOK` | al terminar, publica el informe (veredicto, evidencia, trazabilidad) para encadenar correo, ticket o tablero |

La notificación es *best-effort*: si el orquestador no está disponible, el diagnóstico se
conserva íntegro y sólo queda registrado el aviso. `python run.py n8n` muestra el estado.

---

## 2. Estructura del proyecto

```
mvp-sig/
├── README.md                   # arquitectura, resultados medidos y limitaciones
├── DOCUMENTACION.md            # guía operativa: instalación, ejecución y pruebas
├── run.py                      # CLI: estado, ingesta, evidencia, diagnóstico, matriz,
│                               #       kpis, metricas, benchmark, api, ui
├── requirements.txt
├── .env.example
├── pytest.ini
├── data/
│   ├── seed/iso_fragments/     # fragmentos pre-segmentados de las 3 normas (semilla)
│   ├── storage/chroma/         # base vectorial persistente
│   ├── catalog/                # catálogo documental + exclusiones persistentes
│   ├── evidencias_manuales/    # evidencia registrada a mano (auditable en disco)
│   └── reports/                # informes exportados (CSV / JSON / HTML / MD)
├── mvp_sig/
│   ├── settings.py             # configuración central (normas, rutas, modelos)
│   ├── pipeline.py             # orquestador end-to-end (equivalente al flujo n8n)
│   ├── knowledge/
│   │   ├── requirements.py     # segmentación por cláusula + corpus de requisitos
│   │   ├── coherencia.py       # métrica de coherencia cláusula ↔ texto (A–F)
│   │   ├── arbol_oficial.py    # árbol canónico extraído de los PDF oficiales (F)
│   │   ├── vectorstore.py      # ChromaDB: colecciones y búsqueda con filtro de ámbito
│   │   └── embeddings.py       # embeddings Ollama + respaldo determinista (hash)
│   ├── ingestion/
│   │   ├── extractors.py       # PDF (pypdf) · DOCX (python-docx) · XLSX (openpyxl) · XLS (xlrd) · TXT/MD
│   │   ├── cleaner.py          # limpieza, detección de pies, segmentación, citas
│   │   ├── catalog.py          # clasificación de ámbitos, tipo de documento, id/clave
│   │   └── manual.py           # registro de evidencia manual (texto pegado / archivo)
│   ├── diagnosis/
│   │   ├── engine.py           # motor de diagnóstico + verificación de trazabilidad
│   │   ├── prompts.py          # contrato de salida JSON del auditor LLM
│   │   ├── traceability.py     # matriz de trazabilidad (CSV / JSON / HTML)
│   │   └── kpis.py             # matriz de indicadores por ámbito
│   ├── llm/provider.py         # Ollama · OpenAI · Anthropic · OpenRouter
│   ├── evaluation/
│   │   ├── goldset.py          # 20 casos de referencia con archivos reales del corpus
│   │   ├── metrics.py          # P@k, R@k, MRR, nDCG (nivel fragmento y documento)
│   │   ├── benchmark.py        # comparación de modelos
│   │   └── costos.py           # precios de referencia y costo-efectividad
│   ├── integrations/n8n.py     # cliente del orquestador n8n + validación del flujo
│   ├── api/                    # API REST (FastAPI)
│   └── ui/                     # interfaz web (Streamlit)
├── workflows/
│   └── diagnostico_sig_n8n.json  # flujo de n8n importable (fase 3.4.b)
├── scripts/
│   ├── medir_coherencia.py     # CLI de la métrica de coherencia
│   ├── generar_arbol_oficial.py  # extrae el árbol canónico de los PDF oficiales
│   ├── verificar_semilla_vs_oficial.py  # cotejo de la semilla contra las normas
│   ├── experimento_recuperacion.py  # sensibilidad a k y recuperación híbrida
│   ├── experimento_bd_vectorial.py  # latencia y filtrado: ChromaDB vs Qdrant
│   └── experimento_embeddings.py   # comparación de modelos de embeddings
└── tests/                      # 346 pruebas, sin dependencia de Ollama ni de red
```

---

## 3. Requisitos previos

1. **Python 3.10+** (probado en 3.13).
2. **Ollama** con el modelo de chat y el de embeddings:

```bash
ollama pull llama3.1:8b
ollama pull mxbai-embed-large
ollama serve
```

3. El corpus documental de la organización. Por defecto el sistema apunta al corpus
   **CIL ONG** incluido en `Tesis\material de estudio\...` (273 archivos: 162 DOCX,
   80 XLSX, 28 PDF, 3 XLS heredados). Se puede cambiar con la variable `CORPUS_EVIDENCIAS`.

### Instalación

```bash
cd mvp-sig
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # opcional: ajusta modelo, corpus o claves
```

---

## 4. Uso

### 4.1 Línea de comandos

```bash
python run.py estado                      # estado del sistema (colecciones, modelos)
python run.py ingesta                     # procesa e indexa el corpus completo (~6 min)
python run.py ingesta --limite 20         # prueba rápida con 20 documentos
python run.py evidencia --listar          # inventario completo (corpus + manual)
python run.py evidencia --listar --origen corpus   # sólo el corpus
python run.py evidencia --nombre "Acta de revisión" --texto "..." --ambitos calidad
python run.py evidencia --archivo "C:\ruta\informe.pdf" --ambitos ambiente
python run.py evidencia --documento 2cab97bd9138 --ambitos calidad --codigo SIG-ACTA-01
python run.py evidencia --reindexar 2cab97bd9138   # relee el archivo y conserva los metadatos
python run.py evidencia --excluir 2cab97bd9138 --motivo "duplicado del manual"
python run.py evidencia --reincorporar 2cab97bd9138
python run.py evidencia --eliminar "Acta de revisión.txt"
python run.py diagnostico --limite 10     # diagnostica 10 requisitos
python run.py diagnostico --normas ISO45001 --top-k 8
python run.py matriz                      # sólo la matriz de trazabilidad
python run.py kpis                        # matriz de indicadores
python run.py metricas                    # P@k, R@k, MRR, nDCG sobre el gold set
python scripts/medir_coherencia.py        # coherencia cláusula ↔ texto de las 3 normas
python scripts/experimento_recuperacion.py  # sensibilidad a k y recuperación híbrida
python scripts/experimento_bd_vectorial.py  # latencia y filtrado: ChromaDB vs Qdrant
python scripts/experimento_embeddings.py   # comparación de modelos de embeddings
python run.py benchmark --modelos ollama/llama3.1:8b ollama/llama3.2:latest --limite 5
python run.py n8n                         # estado del orquestador y del flujo exportable
python run.py diagnostico --notificar-n8n # publica el informe en el webhook de n8n
python run.py api                         # API en http://127.0.0.1:8000/docs
python run.py ui                          # interfaz en http://127.0.0.1:8501
```

### 4.2 API REST

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | comprobación de vida |
| GET | `/estado` | estado de la base vectorial y del LLM |
| GET | `/proveedores` | inventario de motores y su disponibilidad real |
| GET | `/normas` | catálogo de normas soportadas |
| GET | `/requisitos` | requisitos indexados (filtro por norma/ámbito) |
| POST | `/ingesta` | procesa e indexa un corpus |
| GET | `/evidencias` | inventario completo: corpus + manual + excluidas (filtros `origen`, `q`, `incluir_excluidas`) |
| GET | `/evidencias/manuales` | sólo la evidencia registrada a mano |
| POST | `/evidencias` | registra evidencia a partir de un texto pegado |
| POST | `/evidencias/archivo` | registra evidencia a partir de un archivo (multipart) |
| PUT | `/evidencias/{documento}` | corrige la clasificación de un documento y lo reindexa |
| POST | `/evidencias/{documento}/reindexar` | relee el archivo origen conservando los metadatos |
| POST | `/evidencias/{documento}/excluir` | retira el documento del diagnóstico sin borrar el archivo |
| POST | `/evidencias/{documento}/reincorporar` | devuelve al diagnóstico un documento excluido |
| DELETE | `/evidencias/{documento}` | da de baja una evidencia manual (borra el archivo) |
| POST | `/diagnostico` | ejecuta el diagnóstico |
| GET | `/diagnostico/matriz.csv` | matriz de trazabilidad en CSV |
| GET | `/diagnostico/informe.html` | informe autocontenido |
| GET | `/kpis` | matriz de indicadores + análisis de consistencia |
| GET | `/metricas/recuperacion` | métricas del gold set |
| POST | `/benchmark` | comparación de modelos de lenguaje |

Documentación interactiva: `http://127.0.0.1:8000/docs`.

### 4.3 Interfaz web (Streamlit)

`python run.py ui` levanta seis pestañas: **Diagnóstico**, **Matriz de trazabilidad**,
**KPI**, **Evaluación**, **Evidencia** e **Ingesta**.

### 4.4 Registro y edición de la evidencia

El corpus del expediente no lo es todo: en una auditoría real llega evidencia por vías
que no son un archivo del expediente (un acta que llega por correo, un reporte
exportado del sistema de gestión, un acta de reunión que sólo existe en papel).
El MVP permite incorporarla **sin rehacer la ingesta completa** (~6 min).

Tres decisiones de diseño que importan:

1. **La evidencia manual se materializa como archivo** en `data/evidencias_manuales/`.
   Una evidencia que no existe en ningún archivo no es evidencia: el sistema tiene que
   poder citarla, volver a indexarla y mostrar su origen. El texto pegado se guarda
   como `.txt`; el archivo subido se copia tal cual.
2. **El indexado es incremental.** Se añaden los fragmentos del documento al corpus ya
   indexado; la colección de evidencias **no se recrea**. Registrar evidencia tarda
   segundos, no minutos.
3. **La metadata la decide quien registra.** Una evidencia pegada a mano no tiene un
   nombre de archivo del que inferir el ámbito, así que en la interfaz se elige
   explícitamente el ámbito (calidad / ambiente / seguridad / integral), el tipo
   documental, la organización responsable y el código. Si no se indica, el sistema los
   infiere del nombre y del texto.

Desde la interfaz (pestaña **📥 Evidencia**) se puede pegar texto o subir un
archivo, ver el inventario, dar de baja una evidencia y **comprobar que la evidencia es
recuperable** antes de lanzar el diagnóstico (si el fragmento no aparece entre los
recuperados, el LLM no podrá citarla).

Desde la CLI:

```bash
python run.py evidencia --nombre "Acta de revisión por la dirección 2026-02" \
                        --texto "La dirección revisó el sistema integrado de gestión…" \
                        --ambitos calidad integral --tipo acta
python run.py evidencia --listar
python run.py evidencia --eliminar "Acta de revisión por la dirección 2026-02.txt"
```

Dos detalles que evitan sorpresas:

- Si el nombre coincide con un documento **del corpus**, la copia manual se registra
  como «… (manual)» para que la matriz de trazabilidad no muestre dos fuentes
  indistinguibles.
- Si el nombre coincide con **otra evidencia manual**, se trata como una actualización:
  se conservan el nombre y los fragmentos anteriores se sustituyen (registro idempotente).

La ingesta completa **recrea** la colección de evidencias, de modo que la evidencia
manual se perdería; por eso `Pipeline.ingerir` la reindexa automáticamente al terminar.

### 4.5 Edición del corpus sin rehacer la ingesta

La clasificación automática (ámbito, tipo documental, organización, código) se infiere
del nombre y del texto del archivo; con 272 documentos reales, algunas inferencias
fallan. Volver a lanzar la ingesta para corregir una etiqueta costaría ~6 minutos y
reindexaría 12 669 fragmentos. La pestaña **🗂️ Inventario y edición del corpus**
(presente en **📥 Evidencia**) resuelve el caso con cuatro operaciones quirúrgicas:

| Operación | Qué hace | Qué conserva |
|---|---|---|
| **Corregir la clasificación** | cambia ámbito(s), tipo documental, organización y código | los campos no indicados mantienen su valor |
| **Reindexar** | vuelve a leer el archivo origen | los metadatos ya corregidos |
| **Excluir del diagnóstico** | retira los fragmentos del índice y el documento del catálogo | **el archivo original** y una copia congelada de sus metadatos |
| **Reincorporar** | reindexa el documento desde su archivo | la clasificación que el auditor había corregido |

La **exclusión es persistente**: se guarda en `data/catalog/exclusiones.json` y
`Pipeline.ingerir` la respeta, de modo que una ingesta completa **no resucita** un
documento que el auditor retiró. Excluir no es dar de baja: el archivo sigue en su
carpeta y el documento puede volver al diagnóstico cuando se quiera. Sólo la evidencia
**manual** se puede dar de baja (borra el archivo), porque es la única que el sistema
creó.

#### Identidad del documento: `id`, `clave` y homónimos

El corpus contiene **17 pares de documentos homónimos** (el mismo nombre de archivo en
dos carpetas distintas). Por eso el nombre **no** identifica un documento, y el
catálogo les asigna dos identificadores derivados de la ruta:

| Campo | Ejemplo | Uso |
|---|---|---|
| `id` | `2cab97bd9138` | 12 hexadecimales, seguro en una URL; lo usan la API y la CLI |
| `clave` | `1. Organigrama.docx#2cab97` | legible, para mostrar en pantalla y depurar el catálogo |

Toda operación acepta el `id`, la `clave` o el nombre. Si el nombre es ambiguo, el
sistema **rechaza la operación** y devuelve la lista de candidatos en lugar de elegir
uno arbitrariamente:

```text
Hay 2 documentos llamados 'Revisión por la Dirección_CIL ONG.docx'.
Indique el id de uno de ellos: Revisión por la Dirección_CIL ONG.docx [74ca3ecc2aa2], …
```

Los catálogos anteriores a este cambio no tenían identificadores; `Pipeline.cargar_catalogo`
los calcula al vuelo, así que no hace falta migrar el archivo a mano.

**Limitación conocida:** la exclusión se ancla a la ruta absoluta del archivo. Si se
mueve el corpus de carpeta, las exclusiones anteriores dejan de aplicarse y hay que
volver a marcarlas.

---

## 5. El aporte metodológico: verificación de trazabilidad

El riesgo clásico de un sistema RAG es que el modelo **afirme** una cita que no existe
(alucinación) o que **resuma** la evidencia sin sustentarla. Este MVP cierra el circuito:

1. El LLM responde con un JSON que **debe** incluir, por cada evidencia citada, la
   referencia (`E1`, `E2`…) y la **cita literal**.
2. El motor recupera el fragmento asociado a esa referencia y comprueba que la cita
   **aparece realmente** en él (`contiene_frase`, con normalización de acentos y
   comparación por ventanas para tolerar truncamientos).
3. Si **ninguna** cita se verifica, el veredicto de cumplimiento **se degrada**:

   | Cita verificable | Resultado |
   |---|---|
   | Al menos una verificada | Se sostiene el veredicto del modelo |
   | Ninguna verificada | `CUMPLE` → `CUMPLE_PARCIAL`, confianza ≤ 0.40 |
   | `CUMPLE` sin ninguna cita | → `NO_CUMPLE`, confianza ≤ 0.40 |

Este control está cubierto por pruebas dedicadas en `tests/test_engine.py`.

---

## 6. Atribución de cláusulas: segmentación y métrica de coherencia

### 6.1 Por qué segmentar y no clasificar

El MVP no *clasifica* fragmentos de la norma en cláusulas: **reconstruye la cláusula**
mediante segmentación sobre el texto continuo. El procedimiento es:

1. Se reconstruye el texto continuo de la norma a partir de los fragmentos semilla
   (`texto_continuo`).
2. Se localizan **todos** los encabezados de cláusula (`escanear_encabezados`). Un
   encabezado se acepta sólo si cumple simultáneamente:
   - el número es un número de cláusula válido (raíz 0–10, hasta 4 componentes);
   - le sigue un **título** (letra mayúscula);
   - no está introducido por una palabra de referencia cruzada (`véase`, `según`, `en`);
   - respeta el orden jerárquico ISO (profundidad primero: `_compatible`).
3. El texto se **parte** en los puntos de encabezado y cada segmento hereda la cláusula
   de su encabezado (`segmentar_por_clausula`).
4. Cada segmento se subdivide en unidades exigibles / informativas
   (`_separar_normativas`), conservando el anclaje documental (página y posición).

Ventaja: la atribución es **objetiva y reproducible** —no depende de un LLM ni de
expresiones regulares aplicadas bloque a bloque— y es auditable: cada requisito
conserva el intervalo de caracteres del documento del que procede.

### 6.2 La métrica de coherencia

Para no evaluar la atribución con la misma lógica que la produce, `mvp_sig/knowledge/coherencia.py`
implementa una **re-derivación independiente**: vuelve a localizar los encabezados en el
documento continuo, vuelve a encontrar el texto de cada requisito en el documento crudo y
comprueba que cae **dentro** del intervalo de su cláusula declarada.

| Comprobación | Qué mide |
|---|---|
| **A · Re-anclaje** | el texto de la unidad está dentro del intervalo de su cláusula |
| **B · Encabezado abre el segmento** | cada segmento empieza por su encabezado |
| **C · Numeración** | existencia de la cláusula padre y contigüidad de los hijos |
| **D · Cobertura** | todo el texto de la norma queda asignado a alguna cláusula |
| **E · Identificadores** | los identificadores de requisito son únicos |
| **F · Árbol oficial** | la cláusula detectada existe en el índice de la norma oficial **y su título coincide** |

Las cinco primeras son **coherencia interna**: el pre-procesamiento es consistente consigo
mismo. La sexta es **conformidad con las versiones oficiales**: no se contrasta contra un
árbol memorizado, sino contra el índice extraído automáticamente de los PDF oficiales
(`scripts/generar_arbol_oficial.py` → `data/seed/arbol_oficial.json`), y exige *dos* cosas
a la vez —que el número de cláusula se detecte y que el segmento empiece por el título
oficial de esa cláusula. Es la comprobación que exige el objetivo específico 5 del
anteproyecto («validar … mediante pruebas funcionales usando las versiones oficiales de
las normas»).

Resultado sobre el corpus de las tres normas:

```
ÍNDICE GLOBAL DE COHERENCIA      874/874 comprobaciones superadas → 100.0 %
  ISO9001    106 encabezados    A 67/67   B 106/106   D 79/79   F 76/76
  ISO14001    99 encabezados    A 38/38   B  99/99   D 71/71   F 52/52
  ISO45001   106 encabezados    A 49/49   B 106/106   D 78/78   F 53/53
  C · huecos de numeración: 1 (informativo) → ISO9001 faltan 0.1, 0.2, 0.3
```

F = cláusulas del índice oficial detectadas **con su título coincidente**. El 100 % se
extiende también a las sub-cláusulas de 4º nivel que el índice no lista (`4.4.1`, `6.1.1`,
`8.1.4.1`…), que se reportan aparte como *adicionales* y no como fallos.

### 6.3 Sólo lo exigible entra al diagnóstico

Una unidad es **normativa** si su texto contiene modalidad exigible (*debe*, *shall*).
Las notas, ejemplos, la bibliografía y las formulaciones de recomendación (*debería*)
quedan como `tipo='informativo'` y **no se indexan**. La Introducción (cláusula 0) se
excluye por definición: es informativa por naturaleza.

Resultado: de **325** unidades detectadas se indexan **154 exigibles**
(ISO9001 67 · ISO14001 38 · ISO45001 49). Los identificadores son únicos por construcción
(`{norma}-{clausula}`, con sufijo `-n` cuando la cláusula tiene varias partes normativas y
`-i`/`-i{n}` para las informativas), lo que elimina las colisiones entre una unidad
normativa y una informativa de la misma cláusula.

---

## 7. Resultados medidos

Todas las cifras de esta sección son reproducibles con los comandos indicados y se
obtienen sobre el corpus CIL ONG ingerido (272 documentos · 12 669 fragmentos).

### 7.1 Estado tras la ingesta

| Métrica | Valor |
|---|---|
| Documentos leídos con éxito | 272 / 273 |
| Fragmentos indexados (`evidencias`) | 12 669 |
| Requisitos exigibles indexados (`iso_requisitos`) | 154 |
| Unidades totales detectadas en las 3 normas | 325 |
| Tiempo de ingesta | ≈ 322 s |
| Embeddings | `mxbai-embed-large` (1024 dim., Ollama) |

### 7.2 Recuperación semántica sobre el gold set (20 casos)

`python run.py metricas --k 5`

| Nivel | P@5 | R@5 | MRR | nDCG@5 |
|---|---|---|---|---|
| **Fragmento** (lo que devuelve Chroma) | 0.2300 | 0.3250 | 0.2658 | 0.3325 |
| **Documento** (lo que se cita como evidencia) | 0.2133 | 0.3250 | 0.2683 | 0.3274 |

Se reportan los dos niveles porque miden cosas distintas: la unidad de relevancia del
*gold set* es el **documento**, y el sistema entrega al evaluador una cita que apunta a
un documento; el nivel de fragmento mide la precisión deltroceo de la base vectorial.

### 7.3 Sensibilidad a `k`

`python scripts/experimento_recuperacion.py`

| k | P@k (doc) | R@k (doc) | MRR | nDCG@k |
|---|---|---|---|---|
| 5 | 0.213 | 0.325 | 0.268 | 0.327 |
| 10 | 0.183 | 0.425 | 0.280 | 0.360 |
| 20 | 0.164 | 0.550 | 0.291 | 0.406 |
| 50 | 0.107 | 0.650 | 0.297 | 0.441 |
| 100 | 0.077 | 0.700 | 0.298 | 0.456 |

El *recall* crece de forma monótona con `k` (0.33 → 0.70) mientras la precisión baja:
el documento esperado **sí está en la base**, pero suele quedar enterrado entre los
fragmentos de documentos genéricos. Es el comportamiento típico de la recuperación densa
y explica por qué el motor entrega **varios** fragmentos al LLM y deja que sea el modelo
—junto con la verificación posterior— quien discrimine.

### 7.4 Matriz de indicadores (KPI)

`python run.py kpis` → **37 indicadores** (calidad 11 · ambiente 12 · seguridad 12 ·
integral 2), con cobertura normativa ISO9001 13 · ISO14001 12 · ISO45001 12 y
frecuencias trimestral 21 · mensual 8 · semestral 5 · anual 3.

### 7.5 Benchmarking de modelos

`python run.py benchmark --limite 5 --modelos …` (los nueve modelos de la comparativa;
ver §4.1 para la línea completa).

| Modelo | Cumplim. | Trazab. | Citas verif. | Latencia prom. | Tokens in | Tokens out |
|---|---|---|---|---|---|---|
| `ollama/llama3.1:8b` | 80.0 % | 100 % | 100 % | 42.2 s | 2324 | 452 |
| `ollama/llama3.2` | 0.0 % | 100 % | 92.9 % | 22.5 s | 2334 | 491 |
| `ollama/gpt-oss:120b-cloud` | 40.0 % | 60 % | 57.1 % | 3.4 s | 2123 | 977 |

Lectura: el modelo de 8 B **sostiene** el veredicto con citas verificadas al 100 %; el de
3 B es más rápido pero degenera en `NO_CUMPLE` sistemático y pierde el 7 % de citas que no
pudo respaldar — se degrada antes de que la verificación lo degrade. El modelo pesado de
120 B (MoE) es **7–12× más rápido** porque corre en la nube de Ollama, pero su trazabilidad
verificada baja al 60 %: emite el veredicto antes de haber respaldado la cita, que es
justo el comportamiento que el control de *grounding* del MVP está diseñado para detectar.

> **La latencia es la única columna dependiente de la máquina.** En una corrida con la RAM
> libre, los mismos dos modelos locales respondieron en 13,2 s y 7,5 s (≈ 3× menos). El
> resto de columnas —veredicto, trazabilidad, citas verificadas y tokens— es estable entre
> corridas, porque depende del modelo y no de la carga del equipo. Las cifras de latencia
> de esta tabla deben leerse como *sobre un equipo saturado*.

Los seis modelos restantes de la comparativa (DeepSeek-V3, Mistral Large 2, GPT-4o mini,
GPT-4o, Claude 3.5 Sonnet y Claude 3.5 Opus) **no se pudieron ejecutar en este entorno**,
y el informe declara el motivo de cada uno (§7.7).

### 7.6 Base de datos vectorial: latencia y filtrado (fase 3.3.a)

`python scripts/experimento_bd_vectorial.py` — los dos motores indexan **los mismos
12 669 vectores**, de modo que la diferencia es atribuible al motor y no al modelo de
embeddings. 20 consultas del *gold set* × 20 repeticiones.

| Motor | k | Filtro | media (ms) | p50 (ms) | p95 (ms) |
|---|---|---|---|---|---|
| ChromaDB | 5 | sin filtro | 12.1 | 11.6 | 15.3 |
| ChromaDB | 5 | `calidad` | 37.4 | 40.4 | 49.2 |
| ChromaDB | 5 | `seguridad` | 107.5 | 108.2 | 124.4 |
| ChromaDB | 10 | sin filtro | 11.4 | 11.2 | 12.7 |
| Qdrant | 5 | sin filtro | 121.0 | 123.1 | 130.1 |
| Qdrant | 5 | `calidad` | 427.5 | 428.4 | 445.4 |
| Qdrant | 5 | `seguridad` | 374.1 | 376.3 | 425.6 |

- **ChromaDB es ~10× más rápido** en la configuración medida (local, en memoria).
- **El filtrado por metadatos es lo caro**, y en ChromaDB se aplica *después* de la
  búsqueda aproximada: su coste crece cuanto más selectivo es el filtro (`seguridad` es
  más restrictivo que `calidad`).
- **Los dos motores recuperan casi lo mismo**: el solapamiento medio de los `top-k` es
  **90,7 %** (mínimo 33,3 %). La elección del motor es, por tanto, indiferente para la
  calidad del diagnóstico y se decide por coste operativo y complejidad.

Caveat honesto: Qdrant se midió en modo local en memoria (`:memory:`), sin servidor ni
índices de payload planificados. Un servidor Qdrant sería más rápido en el filtrado, pero
añade infraestructura que el MVP no necesita.

### 7.7 Costo-efectividad de los modelos (pregunta de investigación nº 4)

`python run.py benchmark …` escribe además `data/reports/costo_efectividad.md`: el precio
de referencia de cada modelo, el coste de un diagnóstico completo (154 requisitos) y la
columna de trazabilidad verificada. Consumo de referencia de esta corrida: **2 261
tokens de entrada** y **640 de salida por requisito**.

| Modelo | Familia | Vía | Estado en esta máquina | Precio ref. (in/out por 1M, USD) | Coste 154 req. | USD / 1000 req. |
|---|---|---|---|---|---|---|
| Llama 3.1 8B | abierta | Ollama | **ejecutado** | 0 / 0 | **0 USD** | 0 |
| Llama 3.2 | abierta | Ollama | **ejecutado** | 0 / 0 | **0 USD** | 0 |
| GPT-OSS 120B | abierta | Ollama cloud | **ejecutado** | 0 / 0 | **0 USD** | 0 |
| DeepSeek-V3 | abierta | Ollama | no ejecutado (671 B: no cabe en el equipo) | 0,27 / 1,10 | ≈ 0,20 USD | 1,32 |
| Mistral Large 2 | abierta | Ollama | no ejecutado (123 B: no cabe en el equipo) | 2,00 / 6,00 | ≈ 1,29 USD | 8,36 |
| GPT-4o mini | comercial | OpenAI | no ejecutado (falta `OPENAI_API_KEY`) | 0,15 / 0,60 | ≈ 0,11 USD | 0,72 |
| GPT-4o | comercial | OpenAI | no ejecutado (falta `OPENAI_API_KEY`) | 2,50 / 10,00 | ≈ 1,86 USD | 12,06 |
| Claude 3.5 Sonnet | comercial | Anthropic | no ejecutado (falta `ANTHROPIC_API_KEY`) | 3,00 / 15,00 | ≈ 2,52 USD | 16,39 |
| Claude 3.5 Opus | comercial | Anthropic | no ejecutado (falta `ANTHROPIC_API_KEY`) | 15,00 / 75,00 | ≈ 12,62 USD | 81,94 |

Los costes de los modelos no ejecutados son **estimaciones**: se aplica el precio de
referencia al mismo consumo de tokens medido en local (el prompt es idéntico para todos
los modelos). El informe distingue explícitamente *medición* de *estimación*, y declara
el motivo por el que cada modelo no pudo ejecutarse.

Conclusión del cuadro: el diagnóstico completo cuesta **0 USD de API** con los tres
modelos abiertos ejecutados (su coste es el del equipo) y entre **0,11 USD** (GPT-4o
mini) y **12,62 USD** (Claude 3.5 Opus) con los comerciales, sobre el mismo consumo de
tokens. La diferencia de **dos órdenes de magnitud** sólo se justifica si el veredicto
del modelo comercial es sustantivamente mejor —y eso es exactamente lo que este MVP
mide y deja publicado en `data/reports/benchmark.md`, en vez de suponerlo.

---

## 8. Limitaciones conocidas

Documentadas de forma explícita porque acotan lo que puede afirmarse en la tesis:

1. **Un documento no se pudo leer.** Un `.docx` del corpus está cifrado con contraseña;
   el extractor lo reporta como fallido (272/273).
2. **Un archivo comprimido queda fuera.** `Gestión HSEQ.rar` no se extrae (el pipeline
   procesa PDF/DOCX/XLSX/XLS). Junto con los `desktop.ini`, `.DS_Store` y demás ruido,
   el índice real es de 272 documentos sobre 273 candidatos.
3. **La Introducción de la ISO 9001 está incompleta en la semilla.** Sólo está la
   cláusula 0.4; faltan 0.1, 0.2, 0.3 y 0.5. No afecta al diagnóstico (la Introducción
   es informativa y se excluye por diseño) pero sí aparece como hueco de numeración en
   la comprobación **C**.
4. **Sólo se indexa lo exigible.** 154 de 325 unidades. Las definiciones de términos de
   la ISO 14001 (p. ej. 3.2.8) se clasifican `normativo` porque su redacción contiene
   *debe*; una depuración posterior de la modalidad exigible sería una mejora del
   clasificador.
5. **El corpus normativo no es el texto íntegro de las normas.** La semilla conserva
   entre el 70 % y el 79 % del texto de cada norma (se pierden anexos y bibliografía),
   pero **sí se verificó contra las versiones oficiales**: la atribución de cláusulas
   coincide con el índice de los PDF oficiales de ISO 9001:2015, ISO 14001:2015 e
   ISO 45001:2018 en el **100 %** de las cláusulas y de sus títulos (comprobación **F** de
   §6.2). Lo que no se verificó es el *contenido literal* de cada sub-cláusula, que
   exigiría un cotejo frase a frase.
6. **La recuperación densa es sensible al idioma y al tipo de texto.** `mxbai-embed-large`
   es un modelo orientado al inglés, mientras que la consulta es normativa
   («La organización debe…») y el corpus es procedimental («Manual de…»). La
   similitud coseno se concentra en una banda estrecha (0.76–0.91) y el discriminante se
   pierde. Se evaluó una recuperación **híbrida** (fusión RRF de la señal densa con una
   señal léxica ponderada por IDF sobre título + cuerpo): el recall@5 mejora de 0.325 a
   0.383 pero el MRR y el nDCG no mejoran, por lo que **no se adopta** en el MVP (la
   evidencia reproducible está en `scripts/experimento_recuperacion.py`).
7. **El modelo de embeddings por defecto es English-only, y su impacto ya está medido.**
   Es la primera causa del punto 6. `scripts/experimento_embeddings.py` indexa los
   **mismos 12 669 fragmentos** con `nomic-embed-text` (768 dim., multilingüe) y lo
   contrasta con `mxbai-embed-large` (1024 dim.) sobre los mismos 20 casos del *gold set*:

   | Métrica (k = 5) | mxbai-embed-large | nomic-embed-text | Δ |
   |---|---|---|---|
   | P@5 (fragmento) | 0.2300 | 0.2600 | +13,0 % |
   | R@5 (fragmento) | 0.3250 | 0.3750 | +15,4 % |
   | MRR (fragmento) | 0.2658 | 0.2825 | +6,3 % |
   | nDCG@5 (fragmento) | 0.3325 | 0.3646 | +9,7 % |
   | P@5 (documento) | 0.2133 | 0.2375 | +11,3 % |
   | R@5 (documento) | 0.3250 | 0.3750 | +15,4 % |
   | MRR (documento) | 0.2683 | 0.3017 | +12,5 % |
   | nDCG@5 (documento) | 0.3274 | 0.3734 | +14,1 % |

   El modelo multilingüe **mejora las ocho métricas**. El MVP conserva
   `mxbai-embed-large` como modelo por defecto porque es el que acompaña a todas las
   cifras publicadas en este documento (y porque el anteproyecto lo nombra), pero el
   cambio está soportado y es reproducible con dos variables de entorno y una
   re-indexación (≈ 730 s):

   ```bash
   set EMBEDDING_MODEL=nomic-embed-text
   set EMBEDDING_DIM=768
   python run.py ingesta        # recrea ambas colecciones con la nueva dimensión
   python run.py metricas
   ```

   La evidencia queda en `data/reports/experimento_embeddings.json`.
8. **La exclusión de un documento está anclada a su ruta absoluta.** Si el corpus se
   mueve o se renombra una carpeta, las exclusiones registradas dejan de aplicarse
   silenciosamente y hay que volver a marcar los documentos. Es el precio de no guardar
   un identificador derivado del contenido: si se guardara el `sha256`, un archivo
   corregido cambiaría de identidad y la exclusión se perdería igual. La decisión está
   documentada en §4.5.
9. **La edición del corpus no versiona los cambios.** Corregir un metadato sobrescribe
   el valor anterior en `catalogo_evidencias.json`; no hay historial de quién cambió qué
   ni cuándo. Para la trazabilidad de la auditoría se conserva la copia congelada de los
   metadatos de los documentos **excluidos**, pero no de los editados.

---

## 9. Pruebas

```bash
python -m pytest
```

**346 pruebas** que **no requieren Ollama ni conexión**: usan embeddings deterministas de
respaldo y un proveedor de lenguaje simulado. Cubren la limpieza y segmentación, la
detección de cláusulas (29 casos límite: referencias cruzadas, listas pegadas, acrónimos,
títulos anunciados por dos puntos, palabras partidas del PDF, NOTA, numeración de
sub-cláusulas), la coherencia cláusula ↔ texto, la **conformidad con el árbol oficial de
las normas**, el filtrado normativo, la verificación de trazabilidad, la matriz de
trazabilidad, los KPIs, las métricas de recuperación, el modelo de costes, la integración
con n8n, los extractores, la API, el **registro manual de evidencia** (idempotencia,
colisión de nombres con el corpus, aislamiento entre homónimos, baja selectiva), la
**edición del corpus** (resolución por `id`/`clave`, corrección de metadatos sin perder
los campos no indicados, reindexado, exclusión persistente frente a la ingesta completa,
reincorporación con los metadatos corregidos) y el **aislamiento del catálogo** (una
prueba nunca puede sobrescribir `data/catalog/catalogo_evidencias.json` ni
`data/catalog/exclusiones.json`; `Pipeline` recibe `catalogo_dir` y `manuales_dir`).

---

## 10. Configuración

Todo se ajusta por variables de entorno (o `.env`, ver `.env.example`):

| Variable | Por defecto | Descripción |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | servidor de Ollama (literal IPv4, ver nota) |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | modelo de embeddings (1024 dim.) |
| `CHAT_MODEL` | `llama3.1:8b` | modelo de chat |
| `LLM_PROVIDER` | `ollama` | `ollama`, `openai`, `anthropic`, `openrouter` |
| `CORPUS_EVIDENCIAS` | corpus CIL ONG | carpeta de documentación a indexar |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 1200 / 200 | segmentación de la evidencia |
| `TOP_K` | 5 | fragmentos recuperados por requisito |
| `SCORE_MIN` | 0.15 | umbral de similitud coseno |
| `CONTEXT_CHARS` | 6000 | presupuesto de contexto enviado al LLM |
| `OLLAMA_CONNECT_TIMEOUT` | 10 | segundos de espera para conectar con Ollama |
| `HTTP_RETRIES` | 3 | reintentos ante fallos de red transitorios |
| `N8N_WEBHOOK` | *(vacío)* | webhook del orquestador n8n al que se publica el informe terminado |

> **Nota sobre `OLLAMA_URL`.** Se usa el literal `127.0.0.1` y no `localhost`
> a propósito. En Windows `localhost` resuelve primero a `::1` (IPv6); si el
> servidor de Ollama sólo escucha en `127.0.0.1` —como ocurre cuando lo
> levanta la app de escritorio— el SYN al IPv6 se descarta en silencio y el
> socket queda en `SYN_SENT` durante todo el periodo de reintento del
> sistema (~20 s) antes de recurrir al IPv4. Con los cientos de peticiones
> de la ingesta completa, esa espera se acumulaba en horas de tiempo muerto
> y la corrida parecía detenerse sin dejar traza. `mvp_sig/utils/http.py`
> normaliza además cualquier URL con `localhost` y usa una sesión
> persistente (*keep-alive*).

> **Nota operativa.** No abra la base vectorial persistente desde un segundo proceso
> mientras corre la ingesta: la colección queda invalidada y la corrida muere con
> `NotFoundError`.

---

## 11. Relación con las fases del anteproyecto

| Fase del anteproyecto | Componente del MVP |
|---|---|
| 3.1 Pre-procesamiento | `ingestion/` (extracción, limpieza, segmentación) |
| 3.2 Indicadores por ámbito | `diagnosis/kpis.py` (catálogo curado + derivados de 9.1) |
| 3.3 Infraestructura vectorial | `knowledge/` (ChromaDB, embeddings, corpus de requisitos) + `scripts/experimento_bd_vectorial.py` + `scripts/experimento_embeddings.py` |
| 3.3 Flujo RAG | `diagnosis/engine.py` + `llm/provider.py` |
| 3.4.a Módulo de pre-procesamiento | `ingestion/` (extracción, limpieza, segmentación) + `ingestion/manual.py` (registro de evidencia manual, indexado incremental) + `knowledge/requirements.py` (segmentación por cláusula) + `knowledge/arbol_oficial.py` (árbol canónico) |
| 3.4 Automatización del flujo | `integrations/n8n.py` + `workflows/diagnostico_sig_n8n.json` |
| 3.3.c Benchmarking de modelos | `evaluation/benchmark.py` + `evaluation/costos.py` (costo-efectividad) |
| 4.1 / 4.2 Evaluación | `evaluation/` (gold set, métricas) + `knowledge/coherencia.py` (comprobación F contra las normas oficiales) |
| 5. Documentación | `diagnosis/traceability.py` (matriz CSV/JSON/HTML) + API + UI |
