"""Evaluación sobre eval/preguntas.jsonl.

- Recuperación: alguno de los k fragmentos que recibió el modelo contiene una frase de `evidencia`.
- Exactitud: un modelo juez compara la respuesta con la de referencia (correcta 1, parcial 0.5).
- Fidelidad: el juez verifica que lo afirmado esté respaldado por los fragmentos.
- Abstención: las preguntas fuera del corpus deben responder "No sé".
- Latencia: mediana y p95 de búsqueda + generación.

uso: uv run python -m eval.evaluar [--solo-recuperacion] [--k 5] [--modelo qwen3:8b] [--juez llama3.1:8b]
"""
import argparse
import datetime
import json
import statistics
import sys
from pathlib import Path

import httpx
import psycopg

from app.busqueda import DB_URL, OLLAMA, buscar
from app.rag import MODELO, NUM_CTX, responder

DEMASIADO_COMUN = 15  # una evidencia en más fragmentos que esto vuelve la métrica demasiado fácil
RESULTADOS = Path("eval/resultados")
PUNTAJE = {"correcta": 1.0, "parcial": 0.5, "incorrecta": 0.0}


def normalizar(t):
    t = t.lower().translate(str.maketrans("“”«»–—", '""""--'))
    return " ".join(t.split())


def contiene(texto, evidencias):
    t = normalizar(texto)
    return any(normalizar(e) in t for e in evidencias)


def es_abstencion(respuesta):
    return normalizar(respuesta).startswith("no sé")


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


def juez(modelo, sistema, usuario, esquema):
    r = httpx.post(f"{OLLAMA}/api/chat", timeout=600, json={
        "model": modelo, "stream": False, "think": False, "format": esquema,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
    })
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def juzgar_exactitud(modelo, q, respuesta):
    return juez(modelo,
        "Sos un evaluador estricto. Compará la respuesta de un sistema con la respuesta de referencia. "
        "'correcta': contiene la información clave de la referencia y no la contradice. "
        "'parcial': tiene parte de la información clave, o le falta un dato importante. "
        "'incorrecta': no responde, contradice la referencia o da datos equivocados.",
        f"Pregunta: {q['pregunta']}\n\nReferencia: {q['respuesta']}\n\nRespuesta del sistema: {respuesta}",
        {"type": "object", "properties": {"veredicto": {"enum": list(PUNTAJE)}, "motivo": {"type": "string"}},
         "required": ["veredicto", "motivo"]})


def juzgar_fidelidad(modelo, respuesta, frags):
    contexto = "\n\n".join(f"[{i}] {texto}" for i, (_, texto, _, _) in enumerate(frags, 1))
    return juez(modelo,
        "Sos un verificador estricto. Decidí si TODAS las afirmaciones de la respuesta están respaldadas "
        "por los fragmentos. Un dato que no aparece en los fragmentos (un valor, un nombre, un plazo) "
        "cuenta como no respaldado, aunque sea plausible.",
        f"Fragmentos:\n\n{contexto}\n\nRespuesta a verificar: {respuesta}",
        {"type": "object", "properties": {"respaldada": {"type": "boolean"}, "no_respaldado": {"type": "string"}},
         "required": ["respaldada", "no_respaldado"]})


def evaluar(preguntas, modelo, modelo_juez, k):
    filas = []
    for q in preguntas:  # fase 1: todas las respuestas con el generador cargado
        r = responder(q["pregunta"], k, modelo)
        filas.append({**q, "salida": r["respuesta"], "citas": r["citas"], "tokens_prompt": r["tokens_prompt"],
                      "segundos": sum(r["segundos"].values()), "abstiene": es_abstencion(r["respuesta"]),
                      "recupera": contiene("\n".join(t for _, t, _, _ in r["fragmentos"]), q["evidencia"]) if q["evidencia"] else None,
                      "_frags": r["fragmentos"]})
        print(".", end="", flush=True)
    print()
    for f in filas:  # fase 2: todos los juicios con el juez cargado
        if f["tipo"] != "fuera" and not f["abstiene"]:
            f["exactitud"] = juzgar_exactitud(modelo_juez, f, f["salida"])
            f["fidelidad"] = juzgar_fidelidad(modelo_juez, f["salida"], f.pop("_frags"))
        f.pop("_frags", None)
        print(".", end="", flush=True)
    print()
    return filas


def resumen(filas, k):
    dentro = [f for f in filas if f["tipo"] != "fuera"]
    respondidas = [f for f in dentro if not f["abstiene"]]
    fuera = [f for f in filas if f["tipo"] == "fuera"]
    segs = sorted(f["segundos"] for f in filas)
    return {
        f"recuperacion@{k}": sum(f["recupera"] for f in dentro) / len(dentro),
        "exactitud": sum(PUNTAJE[f["exactitud"]["veredicto"]] for f in respondidas) / len(dentro),
        "fidelidad": sum(f["fidelidad"]["respaldada"] for f in respondidas) / max(len(respondidas), 1),
        "abstencion_correcta": sum(f["abstiene"] for f in fuera) / len(fuera),
        "abstencion_indebida": len(dentro) - len(respondidas),
        "latencia_mediana_s": statistics.median(segs),
        "latencia_p95_s": segs[min(len(segs) - 1, round(0.95 * (len(segs) - 1)))],
        "tokens_prompt_max": max(f["tokens_prompt"] or 0 for f in filas),
    }


if __name__ == "__main__":
    assert contiene("Valor “WSFEX”  y   más", ['valor "wsfex"']) and not contiene("otra cosa", ["valor"])
    assert es_abstencion("No sé: no encontré esto") and not es_abstencion("Sé que no")
    a = argparse.ArgumentParser()
    a.add_argument("--solo-recuperacion", action="store_true")
    a.add_argument("--k", type=int, default=5)
    a.add_argument("--modelo", default=MODELO)
    a.add_argument("--juez", default="llama3.1:8b")
    args = a.parse_args()

    preguntas = list(map(json.loads, open("eval/preguntas.jsonl")))
    con_evidencia = [q for q in preguntas if q["evidencia"]]
    if not verificar_evidencias(con_evidencia):
        sys.exit("hay evidencias que no están en el índice: corregir el set antes de medir")

    if args.solo_recuperacion:
        fallas = [q for q in con_evidencia if not any(contiene(t, q["evidencia"]) for _, t, _, _ in buscar(q["pregunta"], args.k))]
        print(f"Recuperación@{args.k}: {1 - len(fallas) / len(con_evidencia):.0%}  fallan: {[q['id'] for q in fallas]}")
        sys.exit()

    filas = evaluar(preguntas, args.modelo, args.juez, args.k)
    res = {"fecha": datetime.datetime.now().isoformat(timespec="seconds"), "modelo": args.modelo, "juez": args.juez, "k": args.k, **resumen(filas, args.k)}
    RESULTADOS.mkdir(exist_ok=True)
    nombre = f"{res['fecha'][:16].replace(':', '')}_{args.modelo.replace(':', '-')}"
    (RESULTADOS / f"{nombre}.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas))
    with open(RESULTADOS / "resumen.jsonl", "a") as out:
        out.write(json.dumps(res, ensure_ascii=False) + "\n")
    porcentajes = {f"recuperacion@{args.k}", "exactitud", "fidelidad", "abstencion_correcta"}
    for clave, v in res.items():
        print(f"{clave:22} {v:.1%}" if clave in porcentajes else f"{clave:22} {v}")
    if res["tokens_prompt_max"] >= NUM_CTX:
        print(f"⚠ algún prompt llegó a {NUM_CTX} tokens: Ollama pudo haberlo recortado")
