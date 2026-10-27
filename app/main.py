import os

import httpx
import psycopg
from fastapi import FastAPI, Response

DB_URL = os.getenv("DATABASE_URL", "postgresql://rarca:rarca@localhost:5432/rarca")
OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")

app = FastAPI(title="RArca")


@app.get("/health")
async def health(response: Response):
    status = {}
    try:
        async with await psycopg.AsyncConnection.connect(DB_URL, connect_timeout=3) as conn:
            row = await (await conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).fetchone()
            status["db"] = f"pgvector {row[0]}" if row else "sin pgvector"
    except Exception as e:
        status["db"] = f"error: {e}"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA}/api/tags")
            status["ollama"] = [m["name"] for m in r.json()["models"]]
    except Exception as e:
        status["ollama"] = f"error: {e}"
    ok = status["db"].startswith("pgvector") and isinstance(status["ollama"], list)
    response.status_code = 200 if ok else 503
    return {"ok": ok, **status}
