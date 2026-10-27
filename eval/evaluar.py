"""Evaluación sobre eval/preguntas.jsonl.

Recuperación: porcentaje de preguntas donde alguno de los k primeros fragmentos contiene
una frase de `evidencia` (el texto de la fuente que responde la pregunta).

uso: uv run python -m eval.evaluar [k]
"""
import json
import re
import sys

import psycopg

from app.busqueda import DB_URL, buscar

DEMASIADO_COMUN = 15  # una evidencia en más fragmentos que esto vuelve la métrica demasiado fácil


def normalizar(t):
    t = t.lower().translate(str.maketrans("“”«»–—", '""""--'))
    return " ".join(t.split())


def contiene(texto, evidencias):
    t = normalizar(texto)
    return any(normalizar(e) in t for e in evidencias)


def verificar_evidencias(preguntas):
    """Cada evidencia tiene que estar en el índice; si no, el error es del set de evaluación."""
    with psycopg.connect(DB_URL) as c:
        textos = [normalizar(t) for (t,) in c.execute("SELECT texto FROM fragmentos")]
    ok = True
    for q in preguntas:
        for e in q["evidencia"]:
            n = sum(normalizar(e) in t for t in textos)
            if n == 0 or n > DEMASIADO_COMUN:
                print(f"  evidencia #{q['id']} en {n} fragmentos: {e!r}")
                ok = ok and n > 0
    return ok


def recuperacion(preguntas, k):
    fallas = []
    for q in preguntas:
        frags = buscar(q["pregunta"], k)
        if not any(contiene(texto, q["evidencia"]) for _, texto, _, _ in frags):
            fallas.append((q, frags))
    return 1 - len(fallas) / len(preguntas), fallas


if __name__ == "__main__":
    assert contiene("Valor “WSFEX”  y   más", ['valor "wsfex"']) and not contiene("otra cosa", ["valor"])
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    preguntas = [q for q in map(json.loads, open("eval/preguntas.jsonl")) if q["evidencia"]]
    if not verificar_evidencias(preguntas):
        sys.exit("hay evidencias que no están en el índice: corregir el set antes de medir")
    tasa, fallas = recuperacion(preguntas, k)
    print(f"\nRecuperación@{k}: {tasa:.0%} ({len(preguntas) - len(fallas)}/{len(preguntas)})")
    for q, frags in fallas:
        print(f"\n✗ #{q['id']} [{q['tipo']}] {q['pregunta']}")
        for sec, _, _, d in frags[:3]:
            print(f"    {d:.3f} {sec[-100:]}")
