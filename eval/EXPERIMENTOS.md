# Experimentos

Conjunto de **ajuste** (35 preguntas; las 15 de reserva se miden una sola vez al final).
Generador qwen3:8b, k = 5, RX 6650 XT (8 GB). Corridas en `eval/resultados/`.

| # | Cambio | Recuperación@5 | Exactitud | Fidelidad | Abstención | Latencia mediana / p95 |
|---|---|---|---|---|---|---|
| 0 | Búsqueda vectorial (bge-m3) | 54,8% | 62,9% | 83,9% | 100% | 5,2 s / 7,2 s |
| 1 | + híbrida: full-text en español + vectores, RRF | **64,5%** | **66,1%** | 86,7% | 100% | 5,9 s / 7,7 s |
| 2 | + reranker bge-reranker-v2-m3 (GGUF Q8, llama.cpp Vulkan en GPU) sobre 20 candidatos | **74,2%** | **72,6%** | **90,0%** | 100% | 7,0 s / 8,4 s |
| 3a | Variante de 2: generador llama3.1:8b en vez de qwen3:8b | 74,2% | 66,1% | 82,8% | 75% | 6,9 s / 10,4 s |
| 3b | Variante de 2: partición fija (2000 caracteres, 200 de solapamiento) en vez de por sección | 77,4% | 72,6% | 90,0% | 100% | 8,2 s / 9,8 s |

El reranker cuesta ~1 s por consulta en GPU (la generación, 3,5 a 7 s). Con los tres modelos en la placa
(qwen3:8b 6,2 GB, bge-m3 0,7 GB, reranker 0,8 GB) no entra el escritorio: las mediciones son sin sesión gráfica.

**Conclusiones de 3a y 3b.** qwen3:8b queda como generador: con la misma recuperación es mejor en exactitud,
fidelidad y abstención (llama respondió 1 de 4 preguntas fuera del corpus), aunque el juez de exactitud sea llama.
La partición por sección no le gana a la fija en calidad (77,4% contra 74,2% de recuperación es 1 pregunta de 31),
pero los fragmentos fijos miden siempre ~2000 caracteres y los de sección ~1000 de mediana: la fija le da más texto
al modelo, y eso cuesta 1,2 s más por consulta. Se mantiene por sección: más rápida y con citas que nombran la
sección exacta ("FEDummy > Mensaje de respuesta") en lugar de solo el documento.

## Etapa 5: monotributo (37 páginas del micrositio) y 30 preguntas más

Conjunto de ajuste: 56 preguntas (31 de facturación con evidencia, 19 de monotributo, 6 fuera del corpus).
Configuración 2 (híbrida + reranker en GPU). Dos corridas idénticas para medir el ruido:

| Tema | Recuperación@5 | Exactitud (corrida 1 / 2) | Fidelidad (1 / 2) |
|---|---|---|---|
| Facturación | 74,2% | 62,9% / 66,1% | 90,0% / 87,1% |
| Monotributo | 100% | 78,9% / 78,9% | 89,5% / 89,5% |
| Total | 84,0% | 69,0% / 71,0% | 89,8% / 88,0% |

Abstención 100% en ambas; latencia mediana 6,2 s (con el escritorio abierto).

**Ruido.** Con la misma configuración e índice, 6 de 56 respuestas cambian entre corridas: la inferencia en GPU no
es determinista aun con temperatura 0. En facturación, una pregunta vale 3,2 puntos; diferencias menores a ~10 no
son concluyentes. La exactitud de facturación antes de monotributo (72,6%) era una sola corrida.

**¿Monotributo le resta a facturación?** No se encontró evidencia: la recuperación de facturación no cambia (74,2%),
solo el 4% de los candidatos que llegan al reranker en preguntas de facturación son de monotributo, y la pregunta
que más empeoró (#15) no tiene ninguno. Las páginas de monotributo son cortas y temáticas: 100% de recuperación,
pero es la parte fácil del set.

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
| Reranker en CPU (ONNX INT8, fastembed) con 20 candidatos | Recuperación 80,6%, pero 19 s por consulta y 11 GB de RAM | Inviable en CPU. La versión GGUF en GPU da 74,2%: 2 preguntas de 31, dentro del ruido |
| Reranker en CPU con 10 candidatos de 1000 caracteres | Recuperación 64,5% (sin ganancia), +3 a 5 s | La ganancia viene de los puestos 11 a 20 |
| Reranker en CPU con 10 candidatos de 600 caracteres | Recuperación 58,1% (peor que sin reranker), +2 a 3 s | Cortar el texto le quita la información al reranker |
