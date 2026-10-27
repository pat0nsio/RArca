"""Ingesta: descarga las fuentes de ARCA, las parte por sección o artículo, calcula los
embeddings y reconstruye el índice en pgvector desde cero.

uso: uv run python -m app.ingest   (también deja data/fragmentos.jsonl para inspeccionar)
"""
import difflib
import hashlib
import html
import json
import re
import statistics
import urllib.request
from pathlib import Path

import psycopg

from app.busqueda import DB_URL, embeber, vector

RAW = Path("data/raw")
MAX_CHARS = 2000  # ~500 tokens; 5 fragmentos entran holgados en el contexto de 4096. Se calibra en la etapa 4.

FUENTES = [
    {"id": "wsfev1", "tipo": "manual", "norma": "RG 4291", "fecha": "2026-09-01",
     "titulo": "Manual del desarrollador WSFEv1 v4.7",
     "url": "https://www.arca.gob.ar/ws/documentacion/manuales/manual-desarrollador-ARCA-COMPG.pdf"},
    {"id": "wsfex", "tipo": "manual", "norma": "RG 2758", "fecha": "2025-08-18",
     "titulo": "Manual del desarrollador WSFEX v3.1.1",
     "ignorar": r"Especificaciones técnicas de Servicios Web -WSFEXV1",  # encabezado de cada página
     "url": "https://www.arca.gob.ar/ws/documentacion/manuales/WSFEX-Manualparaeldesarrollador_V3.1.1_ARCA.pdf"},
    {"id": "rg4291", "tipo": "norma", "norma": "RG 4291", "titulo": "RG 4291/2018 (texto actualizado)",
     "url": "https://biblioteca.afip.gob.ar/dcp/REAG01004291_2018_08_02"},
    {"id": "rg5616", "tipo": "norma", "norma": "RG 5616", "titulo": "RG 5616/2024",
     "url": "https://biblioteca.afip.gob.ar/dcp/REAG09005616_2024_12_17"},
    {"id": "rg5700", "tipo": "norma", "norma": "RG 5700", "titulo": "RG 5700/2025",
     "url": "https://biblioteca.afip.gob.ar/dcp/REAG09005700_2025_05_26"},
]


def descargar(fuente):
    destino = RAW / f"{fuente['id']}.{'pdf' if fuente['url'].endswith('.pdf') else 'html'}"
    if not destino.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(fuente["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            destino.write_bytes(r.read())
    return destino


# --- manuales (PDF → markdown) ---

def _fila(l):
    return l.startswith("|") and not l.startswith("|---")


def _unir(a, b):
    return "|".join(" ".join(f"{x} {y}".split()) for x, y in zip(a.split("|"), b.split("|")))


def normalizar_tablas(md):
    """Arregla dos defectos de pymupdf4llm en tablas:
    1. Una tabla que sigue en otra página sale como tabla nueva cuyo "encabezado" es una fila
       de datos. Los encabezados reales salen en negrita: si no lo está, se une a la de arriba.
    2. Un pedazo de celda sale como fila sin primer campo (`|||texto||`): en celdas centradas
       verticalmente es de la fila de abajo (que sigue en minúscula); al cortar página, de la de arriba."""
    lineas = md.replace("<br>", " ").splitlines()
    out = []
    for l in lineas:
        if l.startswith("|---") and out and _fila(out[-1]) and "**" not in out[-1]:
            k = len(out) - 2
            while k >= 0 and not out[k].strip():
                k -= 1
            if k >= 0 and out[k].startswith("|") and out[k].count("|") == l.count("|"):
                fila = out.pop()
                del out[k + 1:]
                out.append(fila)
                continue
        out.append(l)

    res, i = [], 0
    while i < len(out):
        l = out[i]
        if _fila(l) and l.startswith("||"):
            sig = out[i + 1] if i + 1 < len(out) else ""
            arriba = bool(res) and _fila(res[-1]) and res[-1].count("|") == l.count("|")
            abajo = _fila(sig) and sig.count("|") == l.count("|")
            j = next((n for n, c in enumerate(l.split("|")) if c.strip()), 0)
            sigue_minuscula = abajo and sig.split("|")[j].strip()[:1].islower()
            if abajo and (not arriba or sigue_minuscula):
                out[i + 1] = _unir(l, sig)
                i += 1
                continue
            if arriba:
                res[-1] = _unir(res[-1], l)
                i += 1
                continue
        res.append(l)
        i += 1
    return "\n".join(res)


def limpiar_titulo(t):
    return " ".join(re.sub(r"\*\*|</?u>|`", "", t).split())


def nivel_titulo(marcas, titulo):
    if m := re.match(r"(\d+(?:\.\d+)*)\s", titulo):  # "2.1.10 Ejemplo": la numeración manda
        return 2 + m[1].count(".")  # "1" queda a la altura de "Contenido" y lo cierra
    # pymupdf4llm a veces da a "Mensaje de respuesta" el mismo nivel que el método y lo pisa en
    # la ruta; los títulos de método "(FEDummy)", "(FEXAuthorize)" van siempre un nivel arriba
    return 4.5 if re.search(r"\(FE\w+\)$", titulo) else len(marcas)


def secciones_markdown(md, ignorar=None):
    """[(ruta de títulos, cuerpo)] siguiendo los niveles de los títulos del markdown."""
    pila, cuerpo, out = [], [], []
    for linea in md.splitlines() + ["# FIN"]:
        if ignorar and re.search(ignorar, linea):
            continue
        m = re.match(r"^(#+)\s+(.*)", linea)
        titulo = limpiar_titulo(m[2]) if m else ""
        if not m or titulo.endswith(":"):  # "Dónde:" presenta lo que sigue, no es una sección
            cuerpo.append(titulo or linea)
            continue
        if "\n".join(cuerpo).strip():
            out.append((" > ".join(t for _, t in pila), "\n".join(cuerpo)))
        cuerpo = []
        nivel = nivel_titulo(m[1], titulo)
        pila = [(n, t) for n, t in pila if n < nivel] + [(nivel, titulo)]
    return [(s, c) for s, c in out if "Contenido" not in s.split(" > ")]  # el índice solo mete ruido


def bloques(texto):
    """Párrafos, tablas y bloques de código, sin partir ninguno."""
    out, actual, tipo = [], [], None
    for linea in texto.splitlines():
        if tipo == "codigo":
            actual.append(linea)
            if linea.startswith("```"):
                out.append(("codigo", actual)); actual, tipo = [], None
            continue
        nuevo = "codigo" if linea.startswith("```") else "tabla" if linea.startswith("|") else "parrafo" if linea.strip() else None
        if nuevo != tipo or nuevo == "codigo":
            if actual:
                out.append((tipo, actual))
            actual, tipo = [], nuevo
        if nuevo:
            actual.append(linea)
    if actual:
        out.append((tipo, actual))
    return out


def trozos(tipo, lineas, maximo=MAX_CHARS):
    """Parte un bloque largo por líneas; las tablas repiten su encabezado en cada trozo."""
    # solo se repite un encabezado real (pymupdf4llm los saca en negrita); repetir una fila de datos la duplicaría
    cabecera = lineas[:2] if tipo == "tabla" and "**" in lineas[0] else []
    resto = lineas[len(cabecera):]
    largo_max = maximo - len("\n".join(cabecera)) - 1
    out, actual = [], list(cabecera)
    for linea in resto:
        if actual != cabecera and len("\n".join(actual + [linea])) > maximo:
            out.append("\n".join(actual)); actual = list(cabecera)
        actual.append(linea[:largo_max])  # ponytail: una sola línea > MAX se trunca; casi no aparece en estas fuentes
    out.append("\n".join(actual))
    return out


def empaquetar(texto, maximo=MAX_CHARS):
    piezas = [p for tipo, lineas in bloques(texto) for p in trozos(tipo, lineas, maximo)]
    out, actual = [], ""
    for p in piezas:
        if actual and len(actual) + 2 + len(p) > maximo:
            out.append(actual); actual = ""
        actual = f"{actual}\n\n{p}" if actual else p
    return out + [actual] if actual else out


URL = re.compile(r"https?://[^\s<>|`)\]]+")


def reparar_urls(md, texto_crudo):
    """El modo layout de pymupdf4llm corrompe algunas URL subrayadas ("afp.gov.ar/...asmxi"),
    aunque el texto plano del PDF las tiene bien: se reemplaza cada una por la más parecida de ese texto."""
    buenas = set(URL.findall(texto_crudo))
    def arreglar(m):
        u = m[0]
        return u if u in buenas else (difflib.get_close_matches(u, buenas, n=1, cutoff=0.9) or [u])[0]
    return URL.sub(arreglar, md)


def partir_manual(path, ignorar=None):
    import pymupdf
    from pymupdf import pymupdf4llm
    crudo = " ".join(p.get_text() for p in pymupdf.open(path))
    md = normalizar_tablas(reparar_urls(pymupdf4llm.to_markdown(str(path), show_progress=False), crudo))
    return {}, [(s, t) for s, cuerpo in secciones_markdown(md, ignorar) for t in empaquetar(cuerpo)]


# --- normas (HTML de la biblioteca electrónica) ---

def texto_html(raw):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(" ".join(l.split()) for l in t.splitlines() if l.strip())


def partir_norma(path):
    t = texto_html(path.read_text(encoding="utf-8", errors="ignore"))
    meta = {}
    if m := re.search(r"Fecha de emisión: (\d\d)/(\d\d)/(\d{4})", t):
        meta["fecha"] = f"{m[3]}-{m[2]}-{m[1]}"
    if m := re.search(r"Estado de la Norma: (\w+)", t):
        meta["vigente"] = m[1] == "Vigente"
    inicio = min(i for i in (t.find("VISTO"), t.find("ARTÍCULO 1")) if i >= 0)
    fin = t.find("FIRMANTES", inicio)
    cuerpo = t[inicio:fin if fin > 0 else None]

    # Solo corta en artículos que siguen la secuencia: un "ARTÍCULO 6°" citado dentro del
    # artículo 1 (texto que modifica otra norma) no es el artículo 6 de esta norma.
    cortes, siguiente = [(0, "Considerandos")], 1
    for m in re.finditer(r"ARTÍCULO (\d+)°?\s*\.?-", cuerpo):
        if int(m[1]) == siguiente:
            cortes.append((m.start(), f"Artículo {siguiente}")); siguiente += 1
    for m in re.finditer(r"\bANEXO ([IVX]+)\b", cuerpo):
        if m.start() > cortes[-1][0]:
            cortes.append((m.start(), f"Anexo {m[1]}"))
    secciones = []
    for (a, nombre), (b, _) in zip(cortes, cortes[1:] + [(len(cuerpo), None)]):
        if cuerpo[a:b].strip():
            secciones += [(nombre, t) for t in empaquetar(cuerpo[a:b])]
    return meta, secciones


ESQUEMA = """
DROP TABLE IF EXISTS fragmentos, documentos;
CREATE TABLE documentos (
    id text PRIMARY KEY, titulo text NOT NULL, url text NOT NULL, tipo text NOT NULL,
    norma text, fecha date, vigente boolean NOT NULL, sha256 text NOT NULL,
    ingestado timestamptz NOT NULL DEFAULT now()
);
-- ponytail: sin índice HNSW; con ~500 filas el escaneo exacto es instantáneo. Agregarlo pasando las 10.000.
CREATE TABLE fragmentos (
    id serial PRIMARY KEY, documento_id text NOT NULL REFERENCES documentos ON DELETE CASCADE,
    orden int NOT NULL, seccion text NOT NULL, texto text NOT NULL, embedding vector(1024) NOT NULL
);
"""
LOTE = 32


def indexar(frags):
    # se embebe la ruta de títulos junto al texto: "FEDummy > Mensaje de respuesta" le da contexto a una tabla suelta
    embeddings = []
    for i in range(0, len(frags), LOTE):
        embeddings += embeber([f"{x['seccion']}\n\n{x['texto']}" for x in frags[i:i + LOTE]])
    with psycopg.connect(DB_URL) as conn:  # una transacción: si algo falla, queda el índice anterior
        conn.execute(ESQUEMA)
        docs = {x["id"]: x for x in frags}
        conn.cursor().executemany(
            "INSERT INTO documentos (id, titulo, url, tipo, norma, fecha, vigente, sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(d["id"], d["titulo"], d["url"], d["tipo"], d["norma"], d["fecha"], d["vigente"], d["sha256"]) for d in docs.values()])
        conn.cursor().executemany(
            "INSERT INTO fragmentos (documento_id, orden, seccion, texto, embedding) VALUES (%s,%s,%s,%s,%s::vector)",
            [(x["id"], x["orden"], x["seccion"], x["texto"], vector(e)) for x, e in zip(frags, embeddings)])


def fragmentos():
    for f in FUENTES:
        path = descargar(f)
        meta, secciones = partir_manual(path, f.get("ignorar")) if f["tipo"] == "manual" else partir_norma(path)
        doc = {**f, "vigente": True, **meta, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for orden, (seccion, texto) in enumerate(secciones):
            yield {**doc, "seccion": f"{f['titulo']} > {seccion}" if seccion else f["titulo"], "orden": orden, "texto": texto}


def _check():
    crudo = "https://wswhomo.afip.gov.ar/wsfev1/service.asmx y https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
    assert reparar_urls("<u>https://wswhomo.afp.gov.ar/wsfev1/service.asmxi</u> https://otra.gob.ar/x", crudo) == \
        "<u>https://wswhomo.afip.gov.ar/wsfev1/service.asmx</u> https://otra.gob.ar/x"
    assert reparar_urls("https://wswhomo.afp.gov.ar/wsfev1/service.asmx?WSDLi", crudo) == "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
    centrada = "|**C**|**T**|**D**|**O**|\n|---|---|---|---|\n|||Cantidad máxima||\n|RegXReq|Int (4)|incluir en un request|S|"
    assert normalizar_tablas(centrada).splitlines()[2] == "|RegXReq|Int (4)|Cantidad máxima incluir en un request|S|"
    pagina = "|**V**|**D**|\n|---|---|\n|2.5|Se adaptan|\n||Se agregan 10096|\n\n\n|2.6|Se adaptan otros|\n|---|---|"
    assert normalizar_tablas(pagina) == "|**V**|**D**|\n|---|---|\n|2.5|Se adaptan Se agregan 10096|\n|2.6|Se adaptan otros|"
    assert normalizar_tablas("|**A**|\n|---|\n|x|\n\ntexto\n\n|**B**|\n|---|") == "|**A**|\n|---|\n|x|\n\ntexto\n\n|**B**|\n|---|"
    assert secciones_markdown("# A\nx\n## B\ny\n# Contenido\nz\n# C\nw") == [("A", "x"), ("A > B", "y"), ("C", "w")]
    assert secciones_markdown("##### Método (FEDummy)\n##### Mensaje\nx")[0][0] == "Método (FEDummy) > Mensaje"
    assert secciones_markdown("### Contenido\nx\n## 2.1 Autorizador\n# 2.1.10 Ejemplo\nx\n##### Dónde:\ny")[0] == ("2.1 Autorizador > 2.1.10 Ejemplo", "x\nDónde:\ny")
    assert secciones_markdown("# Contenido\n## Sub\nx\n# A\nPIE\ny", ignorar="PIE") == [("A", "y")]
    tabla = "|**C**|**D**|\n|---|---|\n" + "\n".join(f"|f{i}|{'x' * 30}|" for i in range(20))
    partes = empaquetar(tabla, maximo=200)
    assert len(partes) > 1 and all(p.startswith("|**C**|**D**|\n|---|---|") and len(p) <= 200 for p in partes)
    assert sum(p.count("|f") for p in partes) == 20  # ninguna fila perdida ni duplicada
    sin_cabecera = "|4.1|a|\n|---|---|\n" + "\n".join(f"|f{i}|{'x' * 30}|" for i in range(20))
    assert sum(p.count("|4.1|") for p in empaquetar(sin_cabecera, maximo=200)) == 1  # fila de datos no se repite


if __name__ == "__main__":
    _check()
    frags = list(fragmentos())
    Path("data/fragmentos.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in frags))
    indexar(frags)
    for f in FUENTES:
        largos = [len(x["texto"]) for x in frags if x["id"] == f["id"]]
        x0 = next(x for x in frags if x["id"] == f["id"])
        print(f"{f['id']:7} {len(largos):4} fragmentos | mediana {statistics.median(largos):5.0f} | máx {max(largos):5} | "
              f"<150 chars: {sum(l < 150 for l in largos):3} | fecha {x0['fecha']} | vigente {x0['vigente']}")
