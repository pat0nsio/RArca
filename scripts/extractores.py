"""Compara extractores de PDF sobre el manual de WSFEv1: ¿cuántas filas de tabla conocidas
quedan con todas sus celdas en la misma línea? Es lo que necesita un fragmento para
tener sentido solo.

uso: uv run python scripts/extractores.py data/raw/wsfev1.pdf
"""
import subprocess
import sys
import time

# Filas de tablas del manual, cada una con tokens que deberían quedar juntos.
SONDAS = [
    ("<PtoVta>", "10004", "99998"),                        # validación de punto de venta
    ("CbteTipo", "Int (3)", "Tipo de comprobante"),        # tabla FeCabReq
    ("CantReg", "Int (4)", "Cantidad de registros"),       # tabla FeCabReq
    ("Concepto", "Int(2)", "Productos"),                   # tabla FeDetReq
    ("DocNro", "Long (11)", "identificación del comprador"),
    ("AppServer", "String (2)", "Servidor de aplicaciones"),  # FEDummy
    ("RegXReq", "Int (4)", "Cantidad máxima"),             # FECompTotXRequest
    ("600", "No se corresponden token y firma"),           # errores de infraestructura
    ("602", "No existen datos en nuestros registros"),
    ("5", "Consumidor Final", "X"),                        # anexo condición IVA
    ("6", "Responsable Monotributo", "X"),
    ("<Orden>", "15005", "Debe ser igual a 1"),            # validación CAEA
    ("CbteFchHsGen", "1440", "CONTINGENCIAS"),             # CAEA RegInformativo
    ("<CbteTipo> / <DocTipo>", "10013"),                   # factura A con CUIT
]


def pdftotext(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout


def pymupdf4llm(path):
    from pymupdf import pymupdf4llm  # en pymupdf 2.x vive acá; el paquete pymupdf4llm 2.0 está vacío
    return unir_filas_partidas(pymupdf4llm.to_markdown(path, show_progress=False))


def unir_filas_partidas(md):
    """pymupdf4llm parte en dos filas una celda centrada verticalmente: la primera sale
    sin campo (`|||Cantidad máxima...||`). Se pega cada celda a la de la fila siguiente."""
    out, pendiente = [], None
    for linea in md.replace("<br>", " ").splitlines():
        celdas = linea.split("|")
        if linea.startswith("|") and pendiente is not None and len(celdas) == len(pendiente):
            linea = "|".join(" ".join(f"{a} {b}".split()) for a, b in zip(pendiente, celdas))
            celdas, pendiente = linea.split("|"), None
        if linea.startswith("|||") and not linea.startswith("|---"):
            pendiente = celdas
            continue
        if pendiente is not None:  # no hubo fila siguiente compatible: se conserva tal cual
            out.append("|".join(pendiente))
            pendiente = None
        out.append(linea)
    return "\n".join(out)


def pdfplumber(path):
    import pdfplumber
    partes = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tablas = page.find_tables()
            resto = page
            for t in tablas:
                resto = resto.outside_bbox(t.bbox)
            # texto fuera de las tablas y tablas como filas "a | b | c", intercalados por altura en la página
            bloques = [(l["top"], l["text"]) for l in resto.extract_text_lines()]
            for t in tablas:
                filas = [" | ".join(" ".join((c or "").split()) for c in fila) for fila in t.extract()]
                bloques.append((t.bbox[1], "\n".join(filas)))
            partes += [texto for _, texto in sorted(bloques, key=lambda b: b[0])]
    return "\n".join(partes)


def puntaje(texto, sondas=SONDAS):
    # ponytail: una "fila" = una línea; tablas que parten celdas en varias líneas cuentan como falla, que es justo lo que queremos detectar
    lineas = [" ".join(l.split()) for l in texto.splitlines()]
    ok = [s for s in sondas if any(all(tok in l for tok in s) for l in lineas)]
    return ok


if __name__ == "__main__":
    assert puntaje("a | 10004 | 99998\nx", [("a", "10004", "99998"), ("a", "x")]) == [("a", "10004", "99998")]
    assert unir_filas_partidas("|||Cantidad<br>máxima||\n|RegXReq|Int (4)|de registros|S|") == "|RegXReq|Int (4)|Cantidad máxima de registros|S|"
    assert unir_filas_partidas("|||huérfana||\ntexto") == "|||huérfana||\ntexto"
    pdf = sys.argv[1]
    for nombre, fn in [("pdftotext", pdftotext), ("pymupdf4llm", pymupdf4llm), ("pdfplumber", pdfplumber)]:
        t0 = time.perf_counter()
        texto = fn(pdf)
        seg = time.perf_counter() - t0
        ok = puntaje(texto)
        print(f"{nombre:12} {len(ok):2}/{len(SONDAS)} filas intactas | {seg:5.1f} s | {len(texto):7} chars")
        for s in SONDAS:
            if s not in ok:
                print("   falla:", " · ".join(s))
        open(f"data/{nombre}.txt", "w").write(texto)
