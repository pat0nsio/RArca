"""Coincidencia del juez con las etiquetas manuales de eval/validacion_juez.md.

uso: uv run python -m eval.validar_juez eval/resultados/<corrida>.jsonl [--juez otro-modelo]
     sin --juez compara los veredictos guardados en la corrida; con --juez vuelve a juzgar las mismas respuestas.
"""
import argparse
import json
import re

from app.busqueda import buscar
from eval.evaluar import juzgar_exactitud, juzgar_fidelidad


def etiquetas(md):
    out = {}
    for b in re.split(r"(?m)^(?=## #)", md)[1:]:
        ex, fi = re.search(r"Tu exactitud: (\w+)", b), re.search(r"Tu fiel: (\w+)", b)
        if ex and fi:
            out[int(re.match(r"## #(\d+)", b)[1])] = (ex[1], fi[1] == "si")
    return out


if __name__ == "__main__":
    assert etiquetas("x\n## #3 p\n- Tu exactitud: parcial\n- Tu fiel: no\n## #4 q\n- Tu exactitud: \n") == {3: ("parcial", False)}
    a = argparse.ArgumentParser()
    a.add_argument("corrida")
    a.add_argument("--juez")
    a.add_argument("--piensa", action="store_true")
    args = a.parse_args()

    manual = etiquetas(open("eval/validacion_juez.md").read())
    filas = {f["id"]: f for f in map(json.loads, open(args.corrida)) if f["id"] in manual}
    acuerdo_ex = acuerdo_fi = 0
    for i, (ex, fi) in sorted(manual.items()):
        f = filas[i]
        if args.juez:  # mismo índice → misma recuperación que vio el generador
            j_ex = juzgar_exactitud(args.juez, f, f["salida"], args.piensa)["veredicto"]
            j_fi = juzgar_fidelidad(args.juez, f["salida"], buscar(f["pregunta"]), args.piensa)["respaldada"]
        else:
            j_ex, j_fi = f["exactitud"]["veredicto"], f["fidelidad"]["respaldada"]
        acuerdo_ex += j_ex == ex
        acuerdo_fi += j_fi == fi
        if j_ex != ex or j_fi != fi:
            print(f"#{i:2}  exactitud manual {ex:10} juez {j_ex:10} | fiel manual {fi!s:5} juez {j_fi}")
    n = len(manual)
    print(f"\nJuez {args.juez or 'de la corrida'}{' (piensa)' if args.piensa else ''}: exactitud {acuerdo_ex}/{n} ({acuerdo_ex / n:.0%}) | fidelidad {acuerdo_fi}/{n} ({acuerdo_fi / n:.0%})")
