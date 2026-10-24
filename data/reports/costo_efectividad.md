# Costo-efectividad de los modelos de lenguaje

Diagnóstico completo = **154 requisitos normativos** (catálogo vigente).

Consumo de referencia medido en local: **2261 tokens de entrada** y **640 de salida por requisito**.

Las filas marcadas *ejecutado* son mediciones reales del MVP. Las marcadas *no ejecutado* son **estimaciones**: se aplica el precio de referencia del modelo al mismo consumo de tokens medido en local, ya que el prompt es idéntico para todos los modelos.

| Modelo | Vía | Familia | Estado | Trazabilidad | Latencia (s) | Tokens in | Tokens out | Coste diagnosis (USD) | USD / 1000 req. |
|---|---|---|---|---|---|---|---|---|---|
| Llama 3.1 8B | ollama/llama3.1:8b | abierta | ejecutado | 100.0% | 42.2 | 2324 | 453 | 0.0000 | 0.000 |
| Llama 3.2 | ollama/llama3.2 | abierta | ejecutado | 100.0% | 22.5 | 2334 | 491 | 0.0000 | 0.000 |
| GPT-OSS 120B | ollama/gpt-oss:120b-cloud | abierta | ejecutado | 60.0% | 3.4 | 2123 | 978 | 0.0000 | 0.000 |
| DeepSeek-V3 | ollama/deepseek-v3 | abierta | no ejecutado | - | - | - | - | 0.2025 | 1.315 |
| Mistral Large 2 | ollama/mistral-large | abierta | no ejecutado | - | - | - | - | 1.2880 | 8.364 |
| GPT-4o mini | openai/gpt-4o-mini | comercial | no ejecutado | - | - | - | - | 0.1114 | 0.723 |
| GPT-4o | openai/gpt-4o | comercial | no ejecutado | - | - | - | - | 1.8566 | 12.056 |
| Claude 3.5 Sonnet | anthropic/claude-3-5-sonnet-latest | comercial | no ejecutado | - | - | - | - | 2.5238 | 16.388 |
| Claude 3.5 Opus | anthropic/claude-3-5-opus-latest | comercial | no ejecutado | - | - | - | - | 12.6188 | 81.940 |

## Notas

- **Llama 3.1 8B**: Ejecutado en local.
- **Llama 3.2**: Ejecutado en local; el coste es el del equipo, no de API.
- **GPT-OSS 120B**: Pesado abierto (MoE) servido por Ollama en la nube sin coste.
- **DeepSeek-V3**: Estimado con el consumo de tokens medido en local. 671B parámetros: no cabe en el equipo de evaluación. Motivo de no ejecución: el modelo 'deepseek-v3' no está instalado en Ollama.
- **Mistral Large 2**: Estimado con el consumo de tokens medido en local. 123B parámetros: no cabe en el equipo de evaluación. Motivo de no ejecución: el modelo 'mistral-large' no está instalado en Ollama.
- **GPT-4o mini**: Estimado con el consumo de tokens medido en local. Requiere OPENAI_API_KEY. Motivo de no ejecución: falta la clave de API (OPENAI_API_KEY).
- **Claude 3.5 Sonnet**: Estimado con el consumo de tokens medido en local. Requiere ANTHROPIC_API_KEY. Motivo de no ejecución: falta la clave de API (ANTHROPIC_API_KEY).

## Conclusión

Los 3 modelos ejecutados en el equipo tienen **coste de API nulo** y atacan el requisito de diagnóstico sin salida a internet; su límite es la calidad del veredicto y la latencia.
Los modelos comerciales estiman el diagnóstico completo de 154 requisitos entre **0.11 USD** (GPT-4o mini) y **12.62 USD** (Claude 3.5 Opus), con un máximo de 81.94 USD por cada 1000 requisitos diagnosticados. Sólo se justifican si el veredicto que producen es sustantivamente mejor: dato que este MVP deja medido y no supuesto.