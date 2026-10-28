# Experimentos

Conjunto de **ajuste** (35 preguntas; las 15 de reserva se miden una sola vez al final).
Generador qwen3:8b, k = 5, RX 6650 XT (8 GB). Corridas en `eval/resultados/`.

| # | Cambio | Recuperación@5 | Exactitud | Fidelidad | Abstención | Latencia mediana / p95 |
|---|---|---|---|---|---|---|
| 0 | Búsqueda vectorial (bge-m3) | 54,8% | 62,9% | 83,9% | 100% | 5,2 s / 7,2 s |
| 1 | + híbrida: full-text en español + vectores, RRF | **64,5%** | **66,1%** | 86,7% | 100% | 5,9 s / 7,7 s |
| 2 | + reranker bge-reranker-v2-m3 sobre 20 candidatos (solo recuperación) | **80,6%** | — | — | — | +19 s por consulta en CPU |

## Cómo leer los números

- **Recuperación**: alguno de los 5 fragmentos contiene la frase de evidencia de la fuente. Es un piso: a veces
  la respuesta sale de otro fragmento que también la contiene.
- **Exactitud**: juez llama3.1:8b contra la respuesta de referencia (correcta 1, parcial 0,5). Coincide 85% con
  20 respuestas etiquetadas a mano (`eval/validacion_juez.md`); tiende a ser indulgente.
- **Fidelidad**: juez qwen3:8b afirmación por afirmación. Coincide 75% con las etiquetas manuales; no detecta
  todas las respuestas con datos inventados, así que el valor real es más bajo.

## Probado y descartado

| Cambio | Resultado | Por qué no |
|---|---|---|
| Juez de fidelidad con razonamiento (qwen3:8b think) | 70% de coincidencia | No mejora y tarda 11 min en 20 juicios |
| Reranker en CPU con 20 candidatos completos | Recuperación 80,6%, pero 19 s por consulta y 11 GB de RAM | Inviable en CPU; hay que servirlo en GPU |
| Reranker en CPU con 10 candidatos de 1000 caracteres | Recuperación 64,5% (sin ganancia), +3 a 5 s | La ganancia viene de los puestos 11 a 20 |
| Reranker en CPU con 10 candidatos de 600 caracteres | Recuperación 58,1% (peor que sin reranker), +2 a 3 s | Cortar el texto le quita la información al reranker |
