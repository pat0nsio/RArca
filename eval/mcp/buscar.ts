// Usa la búsqueda de mcp-arca-afip tal cual (embedQuery + searchDocs) y devuelve los fragmentos crudos.
import { readFileSync } from 'fs';
import { embedQuery } from './src/services/embedder.js';
import { searchDocs } from './src/services/vector-store.js';

const preguntas = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = [];
await embedQuery('calentar');  // carga del modelo fuera de la medición
for (const q of preguntas) {
  const t0 = performance.now();
  const r = searchDocs(await embedQuery(q.pregunta), q.pregunta, undefined, 5);
  out.push({ id: q.id, ms: Math.round(performance.now() - t0), frags: r.map((x) => ({ source: x.source, section: x.section, text: x.text })) });
}
console.log(JSON.stringify(out));
