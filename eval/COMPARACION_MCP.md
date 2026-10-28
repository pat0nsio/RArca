# Comparación con mcp-arca-afip

[mcp-arca-afip](https://github.com/faeralan/mcp-arca-afip) (MIT, v0.1.0, commit en `mcp/commit-mcp.txt`) es un
servidor MCP open source que indexa la documentación de los web services de ARCA con búsqueda híbrida: BM25 en
cascada (prioriza códigos y nombres como `10015` o `FECAESolicitar`) + vectores multilingual-e5-small + RRF,
sobre fragmentos de 1800 caracteres con 200 de solapamiento extraídos con pdfjs.

**Resultado: sobre el mismo corpus y las mismas preguntas, RArca recupera la evidencia en el 80,8% de los casos
contra 50,5% de mcp-arca-afip (+30,3 puntos) con el corpus ampliado de 124 documentos, y 81,9% contra 61,1% con el
corpus inicial de 42. En las preguntas de reserva: 76,7% contra 40,0% y 77,3% contra 50,0%.**

## Método (igual para los dos corpus)

- **Mismo corpus.** Se corrió la ingesta de mcp-arca-afip, sin cambios en extracción, partición, embeddings ni
  búsqueda, sobre las mismas URLs de RArca (`mcp/sources-inicial.json`: 42; `mcp/sources-ampliado.json`: 124). Su crawler además sigue los PDF enlazados desde
  las páginas: con el corpus inicial su índice quedó con 46 documentos y 445 fragmentos (RArca: 42 y 619).
- **Un parche de robustez** (`mcp/parche-build-index.diff`): dos anexos enlazados desde la RG 4291 terminan en
  `.pdf` pero devuelven HTML, y su ingesta procesa todo con `Promise.all`, así que un archivo roto abortaba el build
  completo. Se cambió a `Promise.allSettled` para saltear esos dos; no toca nada de la recuperación.
- **Misma búsqueda que expone su herramienta**: `embedQuery` + `searchDocs` llamados directamente
  (`mcp/buscar.ts`), con `topK = 5` (su valor por defecto es 8) para comparar contra los 5 fragmentos de RArca.
- **Misma métrica**: la pregunta cuenta como acierto si alguno de los 5 fragmentos contiene la frase de evidencia
  (`eval/preguntas.jsonl`). Se informa también sobre las preguntas cuya evidencia existe en ambos índices, para
  separar "la extracción perdió el texto" de "la búsqueda no lo encontró".
- Todo corrió en un contenedor `node:20` descartable. Resultados crudos en `mcp/resultados-corpus-inicial.json`, `mcp/resultados-corpus-ampliado.json` y `mcp/resultados-publicado.json`.

## Corpus ampliado (124 documentos, 99 preguntas)

El corpus de RArca se amplió tomando como base las 84 entradas del de mcp-arca-afip (`mcp/sources.original.json`):
`scripts/descubrir_ws.py` las valida (3 estaban caídas; 2 se reemplazaron por su versión vigente según el catálogo
de ARCA), sigue los PDF enlazados con su misma regla y marca como no vigentes las versiones viejas de manuales
duplicados. Se corrió su ingesta sobre las mismas 124 URLs (`mcp/sources-ampliado.json`): 142 documentos y 4821
fragmentos (sigue los enlaces de las páginas). RArca: 124 documentos y 6361 fragmentos, 5539 vigentes.

| | Facturación (45) | Monotributo (27) | Web services (27) | Total (99) | Solo reserva (30) |
|---|---|---|---|---|---|
| Evidencia en el índice: mcp | 97,8% | 88,9% | 96,3% | 94,9% | 93,3% |
| **Recuperación: RArca** | **66,7%** | **100%** | **85,2%** | **80,8%** | **76,7%** |
| Recuperación: mcp | 37,8% | 81,5% | 40,7% | 50,5% | 40,0% |
| Recuperación, evidencia en ambos: RArca | 65,9% | 100% | 84,6% | 79,8% | 75,0% |
| Recuperación, evidencia en ambos: mcp | 38,6% | 91,7% | 42,3% | 53,2% | 42,9% |

Al ampliar el corpus, mcp-arca-afip pierde 10,6 puntos (61,1% → 50,5%) y RArca 1,1 (81,9% → 80,8%). Su índice no
distingue versiones vigentes: los manuales duplicados (WSBFEv1 v3.0 y v3.2, MTXCA v0.25.6 y v0.25.8) compiten entre
sí. Latencia mediana de búsqueda: RArca ~1,5 s (GPU, reranker con 30 candidatos), mcp ~9 ms (CPU).

## Corpus inicial (42 documentos, 72 preguntas)

| | Facturación (45) | Monotributo (27) | Total (72) | Solo reserva (22) |
|---|---|---|---|---|
| Evidencia presente en el índice: RArca | 100% | 100% | 100% | 100% |
| Evidencia presente en el índice: mcp | 97,8% | 88,9% | 94,4% | 90,9% |
| **Recuperación: RArca** | **71,1%** | **100%** | **81,9%** | **77,3%** |
| Recuperación: mcp | 46,7% | 85,2% | 61,1% | 50,0% |
| Recuperación, evidencia en ambos: RArca | 70,5% | 100% | 80,9% | 75,0% |
| Recuperación, evidencia en ambos: mcp | 47,7% | 95,8% | 64,7% | 55,0% |

De dónde sale la diferencia: configuraciones intermedias de RArca contra el mismo índice de mcp-arca-afip.

| RArca | Recuperación (72) | vs mcp (61,1%) |
|---|---|---|
| Solo vectores (bge-m3, partición por sección) | 72,2% | +11,1 |
| Híbrida (full-text + vectores, RRF) | 76,4% | +15,3 |
| Híbrida + reranker (configuración final) | 81,9% | +20,8 |

RArca con búsqueda solo vectorial ya supera a la híbrida de mcp-arca-afip: la mayor parte de la ventaja viene de
antes de buscar. Sus fragmentos de los PDF no tienen sección (pdfjs no recupera los títulos de estos manuales),
mientras que los de RArca llevan la ruta de títulos ("FEDummy > Mensaje de respuesta") y las tablas conservadas;
bge-m3 también es un modelo de embeddings más grande que e5-small. El reranker suma el resto.

Solo mcp-arca-afip acierta en 2 preguntas (#26 y #37); solo RArca, en 17.

## Contra su índice publicado

El `index.db` del paquete npm (abril de 2026: 51 web services, 3832 fragmentos) tiene el manual WSFEv1 **v4.1** y
no tiene las normas ni el micrositio de monotributo: recupera 22,2% del total y 35,6% de facturación. No es una
comparación de búsqueda sino de cobertura, y se informa solo como contexto.

## Limitaciones de la comparación

- **Las preguntas y sus evidencias las escribí para RArca.** Las frases de evidencia salieron del texto de las
  fuentes, pero se verificaron contra el índice de RArca; por eso se informa también la columna "evidencia en
  ambos".
- **Las preguntas de ajuste se usaron para ajustar RArca** (69 de 99 con evidencia en el corpus ampliado); la columna
  "solo reserva" (30) no. Es una muestra chica: una pregunta vale 3,3 puntos.
- **Costos distintos.** mcp-arca-afip busca en 4–9 ms en CPU con un modelo de 120 MB; RArca tarda 1–1,5 s porque
  el reranker corre en una GPU de 8 GB. Son herramientas pensadas para usos distintos: la suya se instala con un
  `npx` y le entrega fragmentos a un agente que puede pedir el documento completo (`get_document`).
- Se compara solo la recuperación: mcp-arca-afip no genera respuestas.

## Cómo reproducirlo

```bash
git clone https://github.com/faeralan/mcp-arca-afip && cd mcp-arca-afip
git checkout $(cat ../RArca/eval/mcp/commit-mcp.txt)
git apply ../RArca/eval/mcp/parche-build-index.diff
cp ../RArca/eval/mcp/sources-ampliado.json ingest/sources.json && cp ../RArca/eval/mcp/buscar.ts .
uv run --project ../RArca python -c "import json; json.dump([{'id': q['id'], 'pregunta': q['pregunta']} \
  for q in map(json.loads, open('../RArca/eval/preguntas.jsonl'))], open('preguntas.json', 'w'), ensure_ascii=False)"
podman run --rm -v $PWD:/w:Z -e HOME=/w/.home -w /w docker.io/library/node:20-bookworm \
  sh -c "npm ci && npx tsx ingest/build-index.ts && npx tsx buscar.ts preguntas.json > resultados.json"
cd ../RArca && uv run python -m scripts.comparar_mcp ../mcp-arca-afip/resultados.json ../mcp-arca-afip/data/index.db
```
