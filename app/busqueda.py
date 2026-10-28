import functools
import os

import httpx
import psycopg

DB_URL = os.getenv("DATABASE_URL", "postgresql://rarca:rarca@localhost:5432/rarca")
OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODELO_EMBEDDING = "bge-m3"


def embeber(textos):
    r = httpx.post(f"{OLLAMA}/api/embed", json={"model": MODELO_EMBEDDING, "input": textos}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"]


def vector(v):
    return "[" + ",".join(map(str, v)) + "]"


BUSQUEDA = os.getenv("BUSQUEDA", "hibrida")
CANDIDATOS = 20  # por cada método, antes de fusionar

VECTORIAL = """
SELECT f.seccion, f.texto, d.url, f.embedding <=> %(q)s::vector AS puntaje
FROM fragmentos f JOIN documentos d ON d.id = f.documento_id
WHERE d.vigente ORDER BY puntaje LIMIT %(k)s"""

# Reciprocal Rank Fusion (Cormack et al. 2009): suma 1/(60 + puesto) de cada lista.
HIBRIDA = """
WITH consulta AS (SELECT replace(plainto_tsquery('spanish', %(texto)s)::text, '&', '|')::tsquery AS tq),
vec AS (
    SELECT f.id, row_number() OVER (ORDER BY f.embedding <=> %(q)s::vector) AS puesto
    FROM fragmentos f JOIN documentos d ON d.id = f.documento_id
    WHERE d.vigente ORDER BY f.embedding <=> %(q)s::vector LIMIT %(n)s),
pal AS (
    SELECT f.id, row_number() OVER (ORDER BY ts_rank_cd(f.tsv, c.tq) DESC) AS puesto
    FROM fragmentos f JOIN documentos d ON d.id = f.documento_id, consulta c
    WHERE d.vigente AND f.tsv @@ c.tq ORDER BY ts_rank_cd(f.tsv, c.tq) DESC LIMIT %(n)s),
rrf AS (SELECT id, sum(1.0 / (60 + puesto)) AS puntaje FROM (SELECT * FROM vec UNION ALL SELECT * FROM pal) x GROUP BY id)
SELECT f.seccion, f.texto, d.url, rrf.puntaje
FROM rrf JOIN fragmentos f USING (id) JOIN documentos d ON d.id = f.documento_id
ORDER BY rrf.puntaje DESC LIMIT %(k)s"""


MODELO_RERANKER = "BAAI/bge-reranker-v2-m3-int8"  # Ollama no sirve rerankers: ONNX en CPU vía fastembed
# El costo en CPU crece con el largo: se reordenan menos candidatos y solo el comienzo de cada uno.
CANDIDATOS_RERANK = int(os.getenv("CANDIDATOS_RERANK", 20))  # con 10 se pierde toda la ganancia (EXPERIMENTOS.md)
CHARS_RERANK = int(os.getenv("CHARS_RERANK", 2000))


@functools.cache
def reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(model_name=MODELO_RERANKER, cache_dir="data/modelos")


def buscar(pregunta, k=5, modo=None):
    """Los k fragmentos más relevantes de documentos vigentes.
    modo: "vectorial", "hibrida" (vectores + palabras, RRF) o "hibrida+rerank" (reordena los candidatos con un modelo cruzado)."""
    modo = modo or BUSQUEDA
    sql = VECTORIAL if modo == "vectorial" else HIBRIDA
    rerank = modo.endswith("+rerank")
    params = {"q": vector(embeber([pregunta])[0]), "texto": pregunta, "k": CANDIDATOS_RERANK if rerank else k, "n": CANDIDATOS}
    with psycopg.connect(DB_URL) as c:
        filas = c.execute(sql, params).fetchall()
    if not rerank:
        return filas
    puntajes = list(reranker().rerank(pregunta, [f"{sec}\n{texto}"[:CHARS_RERANK] for sec, texto, _, _ in filas]))
    orden = sorted(zip(puntajes, filas), key=lambda x: x[0], reverse=True)[:k]
    return [(sec, texto, url, p) for p, (sec, texto, url, _) in orden]
