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


BUSQUEDA = os.getenv("BUSQUEDA", "hibrida+rerank")
# por cada método, antes de fusionar. Con el corpus ampliado (124 documentos, manuales de servicios parecidos) 20 se
# quedaba corto: 40 por método y 30 al reranker suben la recuperación del conjunto de ajuste de 76,8% a 82,6% (+0,6 s)
CANDIDATOS = 40

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


# Ollama no sirve rerankers: bge-reranker-v2-m3 corre en llama.cpp con Vulkan (servicio reranker del compose).
# En CPU tardaba 19 s por consulta; en GPU, ~1 s. Con menos candidatos se pierde la ganancia (EXPERIMENTOS.md).
RERANKER_URL = os.getenv("RERANKER_URL", "http://localhost:8081")
CANDIDATOS_RERANK = 30


def puntuar(pregunta, textos):
    r = httpx.post(f"{RERANKER_URL}/v1/rerank", json={"query": pregunta, "documents": textos}, timeout=60)
    r.raise_for_status()
    puntajes = [0.0] * len(textos)
    for x in r.json()["results"]:
        puntajes[x["index"]] = x["relevance_score"]
    return puntajes


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
    puntajes = puntuar(pregunta, [f"{sec}\n{texto}" for sec, texto, _, _ in filas])
    orden = sorted(zip(puntajes, filas), key=lambda x: x[0], reverse=True)[:k]
    return [(sec, texto, url, p) for p, (sec, texto, url, _) in orden]
