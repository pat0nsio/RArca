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


def buscar(pregunta, k=5):
    """Los k fragmentos más cercanos por distancia coseno, solo de documentos vigentes."""
    q = vector(embeber([pregunta])[0])
    with psycopg.connect(DB_URL) as c:
        return c.execute(
            """SELECT f.seccion, f.texto, d.url, f.embedding <=> %s::vector AS distancia
               FROM fragmentos f JOIN documentos d ON d.id = f.documento_id
               WHERE d.vigente
               ORDER BY distancia LIMIT %s""",
            (q, k),
        ).fetchall()
