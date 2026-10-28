"""Evaluación sobre eval/preguntas.jsonl.

- Recuperación: alguno de los k fragmentos que recibió el modelo contiene una frase de `evidencia`.
- Exactitud: un modelo juez compara la respuesta con la de referencia (correcta 1, parcial 0.5).
- Fidelidad: el juez verifica que lo afirmado esté respaldado por los fragmentos.
- Abstención: las preguntas fuera del corpus deben responder "No sé".
- Latencia: mediana y p95 de búsqueda + generación.

uso: uv run python -m eval.evaluar [--conjunto ajuste|reserva|todas] [--solo-recuperacion] [--k 5] [--modelo M] [--juez M] [--piensa]

Las mejoras se miden con "ajuste"; "reserva" se usa una sola vez, al final, para no inflar los números.
"""
import argparse
import datetime
import json
import statistics
import sys
from pathlib import Path

import httpx
import psycopg

from app.busqueda import BUSQUEDA, DB_URL, OLLAMA, buscar
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
        textos = [normalizar(t) for (t,) in c.execute(  # solo lo que la búsqueda puede devolver
            "SELECT f.texto FROM fragmentos f JOIN documentos d ON d.id = f.documento_id WHERE d.vigente")]
    ok = True
    for q in preguntas:
        for e in q["evidencia"]:
            n = sum(normalizar(e) in t for t in textos)
            if n == 0 or n > DEMASIADO_COMUN:
                print(f"  evidencia #{q['id']} en {n} fragmentos: {e!r}")
                ok = ok and n > 0
    return ok


def juez(modelo, sistema, usuario, esquema, piensa=False):
    r = httpx.post(f"{OLLAMA}/api/chat", timeout=900, json={
        "model": modelo, "stream": False, "think": piensa, "format": esquema,
        # con formato JSON forzado un modelo chico puede repetir ítems hasta llenar el contexto: tope de salida.
        # Razonando, el pensamiento también consume ese tope y el contexto.
        "options": {"temperature": 0, "num_ctx": 12288 if piensa else NUM_CTX, "num_predict": 4096 if piensa else 1500},
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
    })
    r.raise_for_status()
    try:
        return json.loads(r.json()["message"]["content"])
    except json.JSONDecodeError:  # cortado por num_predict
        return None


def juzgar_exactitud(modelo, q, respuesta, piensa=False):
    r = juez(modelo,
        # este prompt coincide 85% con las etiquetas manuales; uno más estricto bajó a 80% (eval/validar_juez.py)
        "Sos un evaluador estricto. Compará la respuesta de un sistema con la respuesta de referencia. "
        "'correcta': contiene la información clave de la referencia y no la contradice. "
        "'parcial': tiene parte de la información clave, o le falta un dato importante. "
        "'incorrecta': no responde, contradice la referencia o da datos equivocados.",
        f"Pregunta: {q['pregunta']}\n\nReferencia: {q['respuesta']}\n\nRespuesta del sistema: {respuesta}",
        {"type": "object", "properties": {"veredicto": {"enum": list(PUNTAJE)}, "motivo": {"type": "string"}},
         "required": ["veredicto", "motivo"]}, piensa)
    return r or {"veredicto": "incorrecta", "motivo": "juez sin salida válida"}


def juzgar_fidelidad(modelo, respuesta, frags, piensa=False):
    """Afirmación por afirmación: un modelo chico aprueba "a ojo" si se le pide un solo veredicto."""
    contexto = "\n\n".join(f"[{i}] {sec}\n{texto}" for i, (sec, texto, _, _) in enumerate(frags, 1))
    r = juez(modelo,
        "Sos un verificador estricto. 1) Separá la respuesta en afirmaciones concretas (cada dato, valor, "
        "nombre, plazo o regla que afirma). 2) Para cada una, buscá en los fragmentos el texto que la dice. "
        "Está respaldada solo si un fragmento dice lo mismo; si es plausible pero no aparece, NO está respaldada. "
        "No juzgues si la respuesta es completa: solo si lo que afirma está en los fragmentos.",
        f"Fragmentos:\n\n{contexto}\n\nRespuesta a verificar: {respuesta}",
        {"type": "object", "required": ["afirmaciones"], "properties": {"afirmaciones": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "required": ["afirmacion", "cita_textual", "respaldada"],
            "properties": {"afirmacion": {"type": "string"}, "cita_textual": {"type": "string"}, "respaldada": {"type": "boolean"}}}}}}, piensa)
    if r is None:
        print(f"\n⚠ juez {modelo}: salida JSON inválida, se cuenta como no verificada")
        return {"respaldada": False, "no_respaldado": "juez sin salida válida", "afirmaciones": []}
    afs = r["afirmaciones"]
    return {"respaldada": bool(afs) and all(a["respaldada"] for a in afs),
            "no_respaldado": "; ".join(a["afirmacion"] for a in afs if not a["respaldada"]), "afirmaciones": afs}


def evaluar(preguntas, modelo, juez_exactitud, juez_fidelidad, k, piensa=False, busqueda=None):
    filas = []
    for q in preguntas:  # fase 1: todas las respuestas con el generador cargado
        r = responder(q["pregunta"], k, modelo, busqueda)
        filas.append({**q, "salida": r["respuesta"], "citas": r["citas"], "tokens_prompt": r["tokens_prompt"],
                      "segundos": sum(r["segundos"].values()), "abstiene": es_abstencion(r["respuesta"]),
                      "recupera": contiene("\n".join(t for _, t, _, _ in r["fragmentos"]), q["evidencia"]) if q["evidencia"] else None,
                      "_frags": r["fragmentos"]})
        print(".", end="", flush=True)
    print()
    juzgar = [f for f in filas if f["tipo"] != "fuera" and not f["abstiene"]]
    for f in juzgar:  # fase 2 y 3: cada juez con su modelo cargado, sin alternar en la VRAM
        f["exactitud"] = juzgar_exactitud(juez_exactitud, f, f["salida"], piensa)
        print(".", end="", flush=True)
    for f in juzgar:
        f["fidelidad"] = juzgar_fidelidad(juez_fidelidad, f["salida"], f["_frags"], piensa)
        print(".", end="", flush=True)
    for f in filas:
        f.pop("_frags")
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
        "latencia_mediana_s": round(statistics.median(segs), 2),
        "latencia_p95_s": round(segs[min(len(segs) - 1, round(0.95 * (len(segs) - 1)))], 2),
        "tokens_prompt_max": max(f["tokens_prompt"] or 0 for f in filas),
    }


if __name__ == "__main__":
    assert contiene("Valor “WSFEX”  y   más", ['valor "wsfex"']) and not contiene("otra cosa", ["valor"])
    assert es_abstencion("No sé: no encontré esto") and not es_abstencion("Sé que no")
    a = argparse.ArgumentParser()
    a.add_argument("--conjunto", choices=["ajuste", "reserva", "todas"], default="ajuste")
    a.add_argument("--solo-recuperacion", action="store_true")
    a.add_argument("--sin-verificar", action="store_true", help="no exigir que cada evidencia esté en el índice (experimentos de partición)")
    a.add_argument("--busqueda", choices=["vectorial", "hibrida", "hibrida+rerank"])
    a.add_argument("--k", type=int, default=5)
    a.add_argument("--modelo", default=MODELO)
    # elegidos por coincidencia con las etiquetas manuales: exactitud 85%, fidelidad 75% (eval/validacion_juez.md)
    a.add_argument("--juez", default="llama3.1:8b", help="juez de exactitud")
    a.add_argument("--juez-fidelidad", default="qwen3:8b")
    a.add_argument("--piensa", action="store_true", help="el juez razona antes de responder")
    args = a.parse_args()

    preguntas = [q for q in map(json.loads, open("eval/preguntas.jsonl")) if args.conjunto in ("todas", q["conjunto"])]
    con_evidencia = [q for q in preguntas if q["evidencia"]]
    if not verificar_evidencias(con_evidencia) and not args.sin_verificar:
        sys.exit("hay evidencias que no están en el índice: corregir el set antes de medir")

    if args.solo_recuperacion:
        fallas = [q for q in con_evidencia if not any(contiene(t, q["evidencia"]) for _, t, _, _ in buscar(q["pregunta"], args.k, args.busqueda))]
        print(f"[{args.busqueda or BUSQUEDA}] Recuperación@{args.k}: {1 - len(fallas) / len(con_evidencia):.0%}  fallan: {[q['id'] for q in fallas]}")
        sys.exit()

    filas = evaluar(preguntas, args.modelo, args.juez, args.juez_fidelidad, args.k, args.piensa, args.busqueda)
    res = {"fecha": datetime.datetime.now().isoformat(timespec="seconds"), "conjunto": args.conjunto, "modelo": args.modelo, "juez": args.juez, "juez_fidelidad": args.juez_fidelidad + (" (piensa)" if args.piensa else ""),
           "busqueda": args.busqueda or BUSQUEDA, "k": args.k, **resumen(filas, args.k)}
    RESULTADOS.mkdir(exist_ok=True)
    nombre = f"{res['fecha'][:16].replace(':', '')}_{args.conjunto}_{args.modelo.replace(':', '-')}"
    (RESULTADOS / f"{nombre}.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas))
    with open(RESULTADOS / "resumen.jsonl", "a") as out:
        out.write(json.dumps(res, ensure_ascii=False) + "\n")
    porcentajes = {f"recuperacion@{args.k}", "exactitud", "fidelidad", "abstencion_correcta"}
    for clave, v in res.items():
        print(f"{clave:22} {v:.1%}" if clave in porcentajes else f"{clave:22} {v}")
    if res["tokens_prompt_max"] >= NUM_CTX:
        print(f"⚠ algún prompt llegó a {NUM_CTX} tokens: Ollama pudo haberlo recortado")
