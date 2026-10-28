import os
import re
import time

import httpx

from app.busqueda import OLLAMA, buscar

MODELO = os.getenv("MODELO", "qwen3:8b")
NUM_CTX = 8192  # 5 fragmentos de 2000 caracteres pasan los 4096 por defecto, y Ollama recorta el prompt sin avisar
NO_SE = "No sé: no encontré esto en las fuentes."

SISTEMA = f"""Sos un asistente técnico sobre facturación electrónica de ARCA (ex AFIP).
Respondés usando SOLAMENTE los fragmentos numerados que te paso. Reglas:
1. Respondé en español, breve y preciso.
2. Después de cada afirmación poné la cita del fragmento que la respalda entre corchetes, por ejemplo [2].
3. Si los fragmentos no contienen la respuesta, respondé exactamente "{NO_SE}" y nada más.
4. No uses conocimiento propio ni completes con suposiciones.
5. Si dos fuentes dicen cosas distintas, priorizá la norma o versión más reciente y aclaralo."""


def prompt(pregunta, frags):
    partes = [f"[{i}] {sec}\nFuente: {url}\n{texto}" for i, (sec, texto, url, _) in enumerate(frags, 1)]
    return "Fragmentos:\n\n" + "\n\n---\n\n".join(partes) + f"\n\nPregunta: {pregunta}"


def citas(respuesta, frags):
    nums = sorted({int(n) for n in re.findall(r"\[(\d+)\]", respuesta) if 1 <= int(n) <= len(frags)})
    return [{"n": n, "seccion": frags[n - 1][0], "url": frags[n - 1][2]} for n in nums]


def responder(pregunta, k=5, modelo=MODELO, busqueda=None):
    t0 = time.perf_counter()
    frags = buscar(pregunta, k, busqueda)
    t1 = time.perf_counter()
    r = httpx.post(f"{OLLAMA}/api/chat", timeout=600, json={
        "model": modelo, "stream": False, "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
        "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": prompt(pregunta, frags)}],
    })
    r.raise_for_status()
    datos = r.json()
    respuesta = datos["message"]["content"].strip()
    return {
        "respuesta": respuesta,
        "citas": citas(respuesta, frags),
        "fragmentos": frags,
        "tokens_prompt": datos.get("prompt_eval_count"),
        "segundos": {"busqueda": round(t1 - t0, 2), "generacion": round(time.perf_counter() - t1, 2)},
    }


if __name__ == "__main__":
    frags = [("A > B", "texto", "https://x", 0.1), ("C", "otro", "https://y", 0.2)]
    assert citas("Dice algo [2] y más [2][1] y [7].", frags) == [
        {"n": 1, "seccion": "A > B", "url": "https://x"}, {"n": 2, "seccion": "C", "url": "https://y"}]
    print("ok")
