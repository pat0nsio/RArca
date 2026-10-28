"""Compara la recuperación de RArca con mcp-arca-afip (github.com/faeralan/mcp-arca-afip) con las mismas
preguntas y la misma métrica: alguno de los 5 fragmentos contiene la frase de evidencia.

Las búsquedas de mcp-arca-afip se corren aparte con su propio código (embedQuery + searchDocs, topK=5) y llegan
acá como JSON; su índice SQLite se lee para saber qué evidencias conservó su extracción.

uso: uv run python -m scripts.comparar_mcp <resultados_mcp.json> <index.db> [nombre]
"""
import json
import sqlite3
import statistics
import sys
import time

import psycopg

from app.busqueda import BUSQUEDA, DB_URL, buscar
from eval.evaluar import contiene, normalizar


def en_indice(textos, evidencias):
    return any(normalizar(e) in t for e in evidencias for t in textos)


if __name__ == "__main__":
    assert en_indice(["valor 1 y 99998"], ["entre 1 y 99998", "1 y 99998"]) and not en_indice(["x"], ["y"])
    mcp = {r["id"]: r for r in json.load(open(sys.argv[1]))}
    nombre = sys.argv[3] if len(sys.argv) > 3 else "mcp-arca-afip"
    textos_mcp = [normalizar(t) for (t,) in sqlite3.connect(sys.argv[2]).execute("SELECT text FROM chunks")]
    with psycopg.connect(DB_URL) as c:
        textos_rarca = [normalizar(t) for (t,) in c.execute("SELECT texto FROM fragmentos")]

    filas = []
    for q in map(json.loads, open("eval/preguntas.jsonl")):
        if not q["evidencia"] or q["id"] not in mcp:
            continue
        t0 = time.perf_counter()
        frags = buscar(q["pregunta"], 5)
        filas.append({
            "id": q["id"], "tema": "facturación" if q["id"] <= 50 else "monotributo", "conjunto": q["conjunto"],
            "rarca": any(contiene(t, q["evidencia"]) for _, t, _, _ in frags),
            "mcp": any(contiene(f["text"], q["evidencia"]) for f in mcp[q["id"]]["frags"]),
            "en_rarca": en_indice(textos_rarca, q["evidencia"]), "en_mcp": en_indice(textos_mcp, q["evidencia"]),
            "ms_rarca": (time.perf_counter() - t0) * 1000, "ms_mcp": mcp[q["id"]]["ms"],
        })

    def tasa(sel, clave):
        return f"{sum(f[clave] for f in sel)}/{len(sel)} = {sum(f[clave] for f in sel) / len(sel):.1%}" if sel else "—"

    print(f"Comparación RArca vs {nombre} | {len(filas)} preguntas con evidencia, recuperación@5\n")
    # la reserva no se usó para ajustar RArca: es la comparación sin ventaja de haber visto las preguntas
    grupos = [("facturación", lambda f: f["tema"] == "facturación"), ("monotributo", lambda f: f["tema"] == "monotributo"),
              ("total", lambda f: True), ("solo reserva", lambda f: f["conjunto"] == "reserva")]
    for nombre_grupo, cond in grupos:
        sel = [f for f in filas if cond(f)]
        ambos = [f for f in sel if f["en_rarca"] and f["en_mcp"]]
        print(f"[{nombre_grupo}]")
        print(f"  evidencia presente en el índice    RArca {tasa(sel, 'en_rarca'):18}  {nombre} {tasa(sel, 'en_mcp')}")
        print(f"  recuperación@5 (todas)             RArca {tasa(sel, 'rarca'):18}  {nombre} {tasa(sel, 'mcp')}")
        print(f"  recuperación@5 (evidencia en ambos) RArca {tasa(ambos, 'rarca'):17}  {nombre} {tasa(ambos, 'mcp')}")
    print(f"\nlatencia mediana de búsqueda: RArca {statistics.median(f['ms_rarca'] for f in filas):.0f} ms ({BUSQUEDA}, GPU) | "
          f"{nombre} {statistics.median(f['ms_mcp'] for f in filas):.0f} ms (CPU)")
    solo_rarca = [f["id"] for f in filas if f["rarca"] and not f["mcp"]]
    solo_mcp = [f["id"] for f in filas if f["mcp"] and not f["rarca"]]
    print(f"solo RArca acierta: {solo_rarca}\nsolo {nombre} acierta: {solo_mcp}")
