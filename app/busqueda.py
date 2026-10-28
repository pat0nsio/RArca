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


def buscar(pregunta, k=5, modo=None):
    """Los k fragmentos más relevantes de documentos vigentes: por vectores o híbrida (vectores + palabras, RRF)."""
    sql = HIBRIDA if (modo or BUSQUEDA) == "hibrida" else VECTORIAL
    params = {"q": vector(embeber([pregunta])[0]), "texto": pregunta, "k": k, "n": CANDIDATOS}
    with psycopg.connect(DB_URL) as c:
        return c.execute(sql, params).fetchall()
