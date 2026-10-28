"""Ingesta: descarga las fuentes de ARCA, las parte por sección o artículo, calcula los
embeddings y reconstruye el índice en pgvector desde cero.

uso: uv run python -m app.ingest                reconstrucción completa (deja data/fragmentos.jsonl para inspeccionar)
     uv run python -m app.ingest --actualizar   job semanal: reindexa solo lo que cambió
"""
import difflib
import hashlib
import html
import json
import os
import re
import statistics
import urllib.request
from pathlib import Path

import psycopg

from app.busqueda import DB_URL, embeber, vector

RAW = Path("data/raw")
PARTICION = os.getenv("PARTICION", "seccion")  # "fija": ventanas de MAX_CHARS sin mirar la estructura (experimento)
MAX_CHARS = 2000  # ~500 tokens; 5 fragmentos entran holgados en el contexto de 4096. Se calibra en la etapa 4.

FUENTES = [
    # v4.7 deja de ser vigente: ARCA publicó la v4.8 (revisión del 1/12/2026) en fe/ayuda/documentos/wsfev1-RG-4291.pdf
    {"id": "wsfev1", "tipo": "manual", "norma": "RG 4291", "fecha": "2026-09-01", "vigente": False,
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

# Micrositio de monotributo (etapa 5): páginas con contenido encontradas recorriendo /monotributo/ el 2026-10-28.
# ponytail: lista fija; una página nueva del micrositio hay que agregarla acá (el job semanal solo detecta cambios).
MONOTRIBUTO = [
    "categorias.asp", "exportacion-servicios/",
    *(f"ayuda/{p}.asp" for p in (
        "que-es", "tipos-de-monotributo", "inicio", "CUIT", "clave-fiscal", "domicilio-fiscal-electronico",
        "actividades", "jurisdicciones", "parametros", "desarrollo-de-la-actividad", "facturacion",
        "constancias-y-credenciales", "pagos", "reimputacion-de-pagos", "planes-de-pagos", "recategorizacion",
        "obra-social", "jubilacion", "reintegro-a-cumplidores", "alivio-fiscal", "monotributo-unificado",
        "exclusion", "de-oficio", "baja", "renuncia", "cese-de-actividades", "pasaje-al-regimen-general",
        "procedimiento")),
    *(f"monotributo-promovido/{p}/" for p in ("que-es", "beneficios", "facturacion")),
    *(f"monotributo-social/{p}/" for p in ("que-es-y-quienes-pueden-acceder", "como-me-inscribo-y-como-pido-la-baja",
                                           "como-facturo", "como-pago")),
]
# Web services de ARCA (etapa 7): las entradas del corpus de mcp-arca-afip, validadas por scripts/descubrir_ws.py
FUENTES_WS = json.loads((Path(__file__).parent / "fuentes_ws.json").read_text())
FUENTES += [{"id": "mono-" + re.sub(r"\W+", "-", p.removesuffix(".asp")).strip("-"), "tipo": "web", "norma": None,
             "titulo": "Monotributo", "url": f"https://www.arca.gob.ar/monotributo/{p}"} for p in MONOTRIBUTO]
FUENTES += [{**f, "norma": None} for f in FUENTES_WS]


def archivo(fuente):
    return RAW / f"{fuente['id']}.{'pdf' if fuente['url'].endswith('.pdf') else 'html'}"


def descargar(fuente, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(fuente["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        destino.write_bytes(r.read())


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
    # la ruta; los títulos de método "(FEDummy)", "(getPersona)", "(BFEGetPARAM_Zonas)" van siempre un nivel arriba
    return 4.5 if re.search(r"\((?:FE\w+|\w*[a-z][A-Z]\w*|[A-Za-z]+_\w+)\)$", titulo) else len(marcas)


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
    if PARTICION == "fija":
        return {}, [("", t) for t in partir_fijo(md)]
    return {}, [(s, t) for s, cuerpo in secciones_markdown(md, ignorar) for t in empaquetar(cuerpo)]


def partir_fijo(texto, maximo=MAX_CHARS, solape=200):
    """Línea base del experimento de partición: ventanas de largo fijo con solapamiento, cortando en un espacio."""
    out, i = [], 0
    while i < len(texto):
        corte = texto.rfind(" ", i + maximo // 2, i + maximo)  # -1 si no hay espacio: se corta en seco
        fin = len(texto) if i + maximo >= len(texto) else (corte if corte > 0 else i + maximo)
        out.append(texto[i:fin].strip())
        if fin >= len(texto):
            break
        i = max(fin - solape, i + 1)
    return [x for x in out if x]


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
    if PARTICION == "fija":
        return meta, [("", x) for x in partir_fijo(cuerpo)]

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


# --- páginas web de ARCA (HTML → markdown) ---

def _celdas(fila):
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", fila, re.S)]


def tabla_markdown(tabla):
    filas = [_celdas(f) for f in re.findall(r"<tr.*?</tr>", tabla, re.S)]
    filas = [f for f in filas if any(f)]
    if not filas:
        return ""
    if filas[0] and filas[0][0].startswith("Categ"):  # tabla de categorías de monotributo: una ficha por categoría
        return fichas_categorias(tabla)
    md = ["|" + "|".join(f"**{c}**" for c in filas[0]) + "|", "|" + "---|" * len(filas[0])]  # negrita = encabezado real
    return "\n".join(md + ["|" + "|".join(f) + "|" for f in filas[1:]])


def fichas_categorias(tabla):
    """Encabezados en dos filas: "Impuesto integrado" (colspan 2) se abre en servicios / venta de cosas muebles.
    Los nombres salen de la propia tabla, que ARCA cambia cada semestre; como ficha por categoría, cada una se cita sola."""
    trs = re.findall(r"<tr.*?</tr>", tabla, re.S)
    sub = iter(_celdas(trs[1]))
    cols = []
    for attrs, texto in re.findall(r"<th([^>]*)>(.*?)</th>", trs[0], re.S)[1:]:
        nombre = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", texto)).split())
        n = int(m[1]) if (m := re.search(r'colspan="?(\d+)', attrs)) else 1
        cols += [f"{nombre} ({next(sub)})" for _ in range(n)] if n > 1 else [nombre]
    filas = [_celdas(f) for f in trs[2:]]
    return "\n\n".join(f"**Categoría {f[0]}**: " + "; ".join(f"{c}: {v}" for c, v in zip(cols, f[1:]))
                         for f in filas if len(f) == len(cols) + 1)


def html_a_markdown(raw):
    m = re.search(r"<article.*?</article>", raw, re.S)
    # sin <article> (solo categorías): del último h1 (el primero es el nombre del sitio) al pie oculto "Footer ARCA"
    pie = raw.find('<h2 class="sr-only">Footer')
    t = m[0] if m else raw[max(raw.rfind("<h1"), 0):pie if pie > 0 else None]
    t = re.sub(r"<!--.*?-->|<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<table.*?</table>", lambda x: "\n\n" + tabla_markdown(x[0]) + "\n\n", t, flags=re.S)
    t = re.sub(r"<h([1-4])[^>]*>(.*?)</h\1>",
               lambda x: "\n\n" + "#" * (int(x[1]) + 1) + " " + " ".join(re.sub(r"<[^>]+>", " ", x[2]).split()) + "\n\n",
               t, flags=re.S)
    t = re.sub(r"<li[^>]*>", "\n- ", t)
    t = re.sub(r"</p>|<br\s*/?>|</div>|</ul>|</ol>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lineas = [" ".join(l.split()) for l in t.splitlines()]
    lineas = [l for l in lineas if l != "-"]  # ítems de menú vacíos
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def partir_web(path, prefijo="Monotributo"):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    meta = {}
    if m := re.search(r"<title>\s*(.*?)\s*(?:-|\||</title>)", raw, re.S):
        meta["titulo"] = f"{prefijo}: " + " ".join(html.unescape(m[1]).split())
    if m := re.search(r"desde el (\d{1,2})/(\d{1,2})/(\d{4})", raw):  # "Valores de aplicación desde el 1/08/2026"
        meta["fecha"] = f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    md = html_a_markdown(raw)
    return meta, [(s, t) for s, cuerpo in secciones_markdown("# Página\n" + md) for t in empaquetar(cuerpo)]


# --- WSDL de los web services: operaciones, documentación y campos de entrada/salida ---

def partir_wsdl(path):
    import xml.etree.ElementTree as ET
    raiz = ET.parse(path).getroot()
    local = lambda e: e.tag.rsplit("}", 1)[-1]
    nombre = lambda q: (q or "").split(":")[-1]
    doc = lambda e: " ".join("".join(d.itertext()).split()) if (d := next((h for h in e if local(h) == "documentation"), None)) is not None else ""
    elementos = {e.get("name"): e for e in raiz.iter() if local(e) == "element" and e.get("name")}
    tipos = {e.get("name"): e for e in raiz.iter() if local(e) == "complexType" and e.get("name")}
    mensajes = {m.get("name"): [p.get("element") or p.get("type") for p in m if local(p) == "part"]
                for m in raiz.iter() if local(m) == "message"}

    def campos(ref):  # un nivel: los hijos del complexType del elemento (inline o por nombre de tipo)
        el = elementos.get(nombre(ref))
        ct = next((c for c in el.iter() if local(c) == "complexType"), None) if el is not None else None
        if ct is None:
            ct = tipos.get(nombre(el.get("type") if el is not None else ref))
        if ct is None:
            return []
        return [f"{c.get('name')} ({nombre(c.get('type')) or 'complejo'})" for c in ct.iter()
                if local(c) == "element" and c.get("name") and c is not el]

    servicio = next((e for e in raiz.iter() if local(e) == "service"), None)
    direccion = next((e.get("location") for e in raiz.iter() if local(e) == "address"), "")
    titulo = servicio.get("name") if servicio is not None else raiz.get("name", "")
    secciones = [("", f"Web service {titulo}. {doc(servicio) if servicio is not None else ''} Dirección: {direccion}".strip())]
    vistas = set()
    for op in (o for pt in raiz.iter() if local(pt) == "portType" for o in pt if local(o) == "operation"):
        if op.get("name") in vistas:
            continue
        vistas.add(op.get("name"))
        partes = [doc(op)] if doc(op) else []
        for h in op:
            if local(h) in ("input", "output"):
                refs = mensajes.get(nombre(h.get("message")), [])
                cs = [c for r in refs for c in campos(r)]
                etiqueta = "Entrada" if local(h) == "input" else "Salida"
                partes.append(f"{etiqueta}: {', '.join(nombre(r) for r in refs)}" + (f". Campos: {', '.join(cs)}" if cs else ""))
        secciones += [(f"Operación {op.get('name')}", t) for t in empaquetar("\n\n".join(partes))]
    return {}, secciones  # el título de la fuente ya dice qué web service es


ESQUEMA = """
DROP TABLE IF EXISTS fragmentos, documentos;
CREATE TABLE documentos (
    id text PRIMARY KEY, titulo text NOT NULL, url text NOT NULL, tipo text NOT NULL,
    norma text, fecha date, vigente boolean NOT NULL, sha256 text NOT NULL,
    ingestado timestamptz NOT NULL DEFAULT now()
);
-- ponytail: sin índice HNSW; con ~600 filas el escaneo exacto es instantáneo. Agregarlo pasando las 10.000.
CREATE TABLE fragmentos (
    id serial PRIMARY KEY, documento_id text NOT NULL REFERENCES documentos ON DELETE CASCADE,
    orden int NOT NULL, seccion text NOT NULL, texto text NOT NULL, embedding vector(1024) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', seccion || ' ' || texto)) STORED
);
CREATE INDEX ON fragmentos USING gin (tsv);
"""
# El registro de cambios sobrevive a las reconstrucciones completas.
REGISTRO = """CREATE TABLE IF NOT EXISTS actualizaciones (
    fecha timestamptz NOT NULL DEFAULT now(), documento_id text NOT NULL, accion text NOT NULL, detalle text)"""
LOTE = 32


def insertar(conn, frags):
    # se embebe la ruta de títulos junto al texto: "FEDummy > Mensaje de respuesta" le da contexto a una tabla suelta
    embeddings = []
    for i in range(0, len(frags), LOTE):
        embeddings += embeber([f"{x['seccion']}\n\n{x['texto']}" for x in frags[i:i + LOTE]])
    docs = {x["id"]: x for x in frags}
    conn.cursor().executemany(
        "INSERT INTO documentos (id, titulo, url, tipo, norma, fecha, vigente, sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        [(d["id"], d["titulo"], d["url"], d["tipo"], d["norma"], d["fecha"], d["vigente"], d["sha256"]) for d in docs.values()])
    conn.cursor().executemany(
        "INSERT INTO fragmentos (documento_id, orden, seccion, texto, embedding) VALUES (%s,%s,%s,%s,%s::vector)",
        [(x["id"], x["orden"], x["seccion"], x["texto"], vector(e)) for x, e in zip(frags, embeddings)])


def indexar(frags):
    with psycopg.connect(DB_URL) as conn:  # una transacción: si algo falla, queda el índice anterior
        conn.execute(ESQUEMA)
        conn.execute(REGISTRO)
        insertar(conn, frags)
        conn.execute("INSERT INTO actualizaciones (documento_id, accion, detalle) VALUES ('*', 'reconstruccion', %s)",
                     (f"{len(frags)} fragmentos",))


def fragmentos_de(f, forzar=False):
    """forzar: vuelve a bajar la fuente. La copia nueva reemplaza a la guardada solo si se pudo procesar:
    ARCA responde 200 con una página vacía a una URL que ya no existe."""
    path = archivo(f)
    if forzar or not path.exists():
        nuevo = path.with_name(path.name + ".nuevo")
        try:
            descargar(f, nuevo)
            meta, secciones = partir_fuente(f, nuevo)
            if not secciones:
                raise ValueError("la descarga no tiene contenido")
            nuevo.replace(path)
        finally:
            nuevo.unlink(missing_ok=True)
    else:
        meta, secciones = partir_fuente(f, path)
    doc = {"fecha": None, "vigente": True, **f, **meta}
    # hash del contenido extraído (no del archivo: una página que solo cambia scripts no se reindexa) y de los
    # metadatos, para que marcar un manual como no vigente también se aplique en la actualización semanal
    datos = json.dumps({k: doc[k] for k in ("titulo", "fecha", "vigente")}, sort_keys=True)
    doc["sha256"] = hashlib.sha256((datos + "\n".join(f"{s}\n{t}" for s, t in secciones)).encode()).hexdigest()
    out = []
    for orden, (seccion, texto) in enumerate(secciones):
        seccion = seccion.removeprefix("Página").removeprefix(" > ")
        out.append({**doc, "seccion": f"{doc['titulo']} > {seccion}" if seccion else doc["titulo"], "orden": orden, "texto": texto})
    return out


def partir_fuente(f, path):
    return {"manual": lambda p: partir_manual(p, f.get("ignorar")), "norma": partir_norma, "wsdl": partir_wsdl,
            "web": lambda p: partir_web(p, f["titulo"].split(":")[0])}[f["tipo"]](path)


def fragmentos():
    return [x for f in FUENTES for x in fragmentos_de(f)]


def actualizar():
    """Job semanal: vuelve a bajar las fuentes y reindexa solo los documentos cuyo contenido cambió."""
    with psycopg.connect(DB_URL) as conn:
        conn.execute(REGISTRO)
        anteriores = dict(conn.execute("SELECT id, sha256 FROM documentos").fetchall())
    cambios = []
    for f in FUENTES:
        try:
            frags = fragmentos_de(f, forzar=True)
        except Exception as e:  # una caída de ARCA no puede vaciar el índice: se conserva la versión anterior
            cambios.append((f["id"], "error", f"se mantiene la versión anterior: {e}"))
            continue
        sha = frags[0]["sha256"] if frags else None
        if sha == anteriores.get(f["id"]):
            continue
        with psycopg.connect(DB_URL) as conn:  # una transacción por documento
            conn.execute("DELETE FROM documentos WHERE id = %s", (f["id"],))
            insertar(conn, frags)
            accion = "cambiado" if f["id"] in anteriores else "nuevo"
            conn.execute("INSERT INTO actualizaciones (documento_id, accion, detalle) VALUES (%s, %s, %s)",
                         (f["id"], accion, f"{len(frags)} fragmentos"))
        cambios.append((f["id"], accion, f"{len(frags)} fragmentos"))
    with psycopg.connect(DB_URL) as conn:
        for id_ in set(anteriores) - {f["id"] for f in FUENTES}:
            conn.execute("DELETE FROM documentos WHERE id = %s", (id_,))
            conn.execute("INSERT INTO actualizaciones (documento_id, accion) VALUES (%s, 'eliminado')", (id_,))
            cambios.append((id_, "eliminado", ""))
        for id_, accion, detalle in cambios:
            if accion == "error":
                conn.execute("INSERT INTO actualizaciones (documento_id, accion, detalle) VALUES (%s, %s, %s)", (id_, accion, detalle))
    return cambios


def _check():
    assert nivel_titulo("#####", "Método (getPersona)") == 4.5 and nivel_titulo("#####", "Método (BFEGetPARAM_Zonas)") == 4.5
    assert nivel_titulo("#####", "Mensaje de respuesta") == 5 and nivel_titulo("#####", "Alcance (CUIT)") == 5
    h = '<article><h2>Pagos</h2><p>Se paga <b>hasta</b> el 20.</p><ul><li>uno</li></ul><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></article>'
    assert html_a_markdown(h) == "### Pagos\n\nSe paga hasta el 20.\n\n- uno\n\n|**A**|**B**|\n|---|---|\n|1|2|", html_a_markdown(h)
    t = ('<table><tr><th rowspan="2">Categ.</th><th rowspan="2">Ingresos</th><th colspan="2">Impuesto</th></tr>'
         '<tr><th>Servicios</th><th>Venta</th></tr><tr><td>A</td><td>$1</td><td>$2</td><td>$3</td></tr></table>')
    assert fichas_categorias(t) == "**Categoría A**: Ingresos: $1; Impuesto (Servicios): $2; Impuesto (Venta): $3", fichas_categorias(t)
    partes = partir_fijo("palabra " * 100, maximo=100, solape=20)
    assert all(len(x) <= 100 for x in partes) and partes[0].startswith("palabra") and len(partes) > 8
    assert [len(x) for x in partir_fijo("x" * 250, maximo=100, solape=20)] == [100, 100, 90]  # sin espacios corta en seco
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
    import sys
    _check()
    if "--actualizar" in sys.argv:
        cambios = actualizar()
        for id_, accion, detalle in cambios:
            print(f"{accion:10} {id_:40} {detalle}")
        print(f"{len(cambios)} cambios" if cambios else "sin cambios")
        sys.exit()
    frags = fragmentos()
    Path("data/fragmentos.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in frags))
    indexar(frags)
    for f in FUENTES:
        largos = [len(x["texto"]) for x in frags if x["id"] == f["id"]]
        x0 = next(x for x in frags if x["id"] == f["id"])
        print(f"{f['id']:7} {len(largos):4} fragmentos | mediana {statistics.median(largos):5.0f} | máx {max(largos):5} | "
              f"<150 chars: {sum(l < 150 for l in largos):3} | fecha {x0['fecha']} | vigente {x0['vigente']}")
