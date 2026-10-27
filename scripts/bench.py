"""Mide tokens/segundo de modelos en Ollama con un prompt fijo.

uso: python scripts/bench.py qwen3:8b llama3.1:8b
"""
import json
import sys
import urllib.request

OLLAMA = "http://localhost:11434"
PROMPT = "Explicá en un párrafo qué es la factura electrónica en Argentina y quién está obligado a emitirla."


def run(model):
    body = json.dumps({"model": model, "prompt": PROMPT, "stream": False, "think": False,
                       "options": {"temperature": 0, "seed": 1}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def tok_s(count, ns):
    return count / (ns / 1e9) if ns else 0.0


if __name__ == "__main__":
    assert round(tok_s(50, 2_000_000_000), 1) == 25.0
    for model in sys.argv[1:]:
        run(model)  # calentamiento: carga el modelo en VRAM
        r = run(model)
        print(f"{model:20} gen {tok_s(r['eval_count'], r['eval_duration']):6.1f} tok/s | "
              f"prompt {tok_s(r['prompt_eval_count'], r['prompt_eval_duration']):7.1f} tok/s | "
              f"total {r['total_duration'] / 1e9:5.1f} s")
        print("  ", r["response"][:200].replace("\n", " "), "...\n")
