# Benchmarking de modelos de lenguaje

Comparación de motores sobre el mismo conjunto de requisitos normativos.
Métricas de costo-efectividad exigidas por el objetivo específico 3.3.c.

| Proveedor | Modelo | Estado | Requisitos | Cumplim. | No cumplim. | Trazab. | Citas verif. | Latencia prom. | Tokens in | Tokens out | Coste USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ollama | llama3.1:8b | ok | 5 | 80.0% | 20.0% | 100.0% | 100.0% | 42.222s | 2324 | 452 | 0.0 |
| ollama | llama3.2 | ok | 5 | 0.0% | 100.0% | 100.0% | 92.9% | 22.544s | 2334 | 491 | 0.0 |
| ollama | gpt-oss:120b-cloud | ok | 5 | 40.0% | 60.0% | 60.0% | 57.1% | 3.362s | 2123 | 977 | 0.0 |
| ollama | deepseek-v3 | error | - | - | - | - | - | -s | 0 | 0 | 0 |
| ollama | mistral-large | error | - | - | - | - | - | -s | 0 | 0 | 0 |
| openai | gpt-4o-mini | error | - | - | - | - | - | -s | 0 | 0 | 0 |
| openai | gpt-4o | error | - | - | - | - | - | -s | 0 | 0 | 0 |
| anthropic | claude-3-5-sonnet-latest | error | - | - | - | - | - | -s | 0 | 0 | 0 |
| anthropic | claude-3-5-opus-latest | error | - | - | - | - | - | -s | 0 | 0 | 0 |

## Ranking por costo-efectividad

Índice = trazabilidad verificada / (latencia × (1 + coste USD de la corrida)). Como los modelos ejecutados en local tienen coste de API nulo, el factor de coste no altera el orden entre ellos: el ranking mide trazabilidad por segundo de cómputo.

| # | Modelo | Índice costo-efectividad | Trazabilidad | Latencia (s) |
|---|---|---|---|---|
| 1 | ollama/gpt-oss:120b-cloud | 0.1785 | 60.0% | 3.362 |
| 2 | ollama/llama3.2 | 0.0444 | 100.0% | 22.544 |
| 3 | ollama/llama3.1:8b | 0.0237 | 100.0% | 42.222 |