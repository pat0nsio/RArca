"""Genera app/fuentes_ws.json: las fuentes de los web services de ARCA, tomando como base las 84 entradas del
corpus de mcp-arca-afip (eval/mcp/sources.original.json, MIT) para que la comparación sea sobre lo mismo.

Para cada entrada: la descarga (siguiendo redirecciones); si está caída prueba la misma ruta en arca.gob.ar; de las
páginas HTML sigue hasta 10 PDF enlazados del mismo dominio (la misma regla que su crawler). Descarta lo que no es
lo que dice ser (un .pdf que devuelve HTML) y las versiones viejas de documentos que RArca ya tiene.

uso: uv run python -m scripts.descubrir_ws
"""
import json
import re
import time
import urllib.parse
from pathlib import Path

import httpx

from app.ingest import FUENTES, FUENTES_WS

ORIGEN = Path("eval/mcp/sources.original.json")
SALIDA = Path("app/fuentes_ws.json")
# solo las fuentes propias de RArca: FUENTES ya incluye las que este script generó la vez anterior
YA_EN_RARCA = {f["url"] for f in FUENTES} - {f["url"] for f in FUENTES_WS}
ruta = lambda u: re.sub(r"^https?://[^/]+", "", u)  # afip.gob.ar y arca.gob.ar sirven los mismos archivos sin redirigir
# versiones anteriores de manuales que RArca ya tiene actualizados (WSFEv1 v4.7 y WSFEX v3.1.1 en arca.gob.ar)
VIEJOS = re.compile(r"manual-desarrollador-ARCA-COMPG-v\d|WSFEX-Manualparaeldesarrollador_V3\.1\.1_ARCA\.pdf$")
# entradas de su lista (abril de 2026) que hoy dan 404 → la versión vigente según el catálogo de ARCA
# (www.afip.gob.ar/ws/documentacion/catalogo.asp, consultado el 2026-10-28)
REEMPLAZOS = {
    "https://www.afip.gob.ar/ws/ws-padron-a13/manual-ws-sr-padron-a13-v1.3.pdf":
        "https://www.afip.gob.ar/ws/ws-padron-a13/manual-ws-sr-padron-a13-v1.4.pdf",
    "https://www.afip.gob.ar/ws/WSLiquiGranos/manual_wslpg_1.24.pdf": "https://www.afip.gob.ar/ws/WSLiquiGranos/manual-wslpg.pdf",
}
# El mismo manual aparece en ws/documentacion/manuales/ y en fe/ayuda/documentos/ con revisiones distintas: quedan las
# dos en el índice, pero solo la más nueva es vigente (la búsqueda filtra por vigente). Verificado el 2026-10-28.
F = "https://www.afip.gob.ar/fe/ayuda/documentos/"
M = "https://www.afip.gob.ar/ws/documentacion/manuales/"
VIGENTES = {  # versión vieja → (la que la reemplaza, motivo)
    M + "WSSEG-ManualParaElDesarrollador_ARCA.pdf": (F + "wsseg-RG-2668.pdf", "v0.9 (21/5/2025) → v1.0 (9/6/2025)"),
    M + "WSBFEV1-ManualParaElDesarrollador_ARCA_V3_0.pdf": (F + "wsbfev1-RG-5427-y-2861.pdf", "v3.0 (17/3/2025) → v3.2 (9/6/2025)"),
    M + "Web-Service-MTXCA-v25.pdf": (F + "wsmtxca-RG-2904.pdf", "v0.25.6 → v0.25.8"),
}
FECHAS = {F + "wsfev1-RG-4291.pdf": "2026-12-01", F + "wsseg-RG-2668.pdf": "2025-06-09", F + "wsbfev1-RG-5427-y-2861.pdf": "2025-06-09"}
cliente = httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"})


def tipo_de(url):
    u = url.lower()
    return "wsdl" if "wsdl" in u else "manual" if u.endswith(".pdf") else "web"


def bajar(url):
    """(url final, contenido) si responde 200 con el tipo esperado; None si no."""
    time.sleep(1)  # misma cortesía que su crawler (1,2 s)
    try:
        r = cliente.get(url)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    es_pdf = r.content[:5] == b"%PDF-"
    if (tipo_de(url) == "manual") != es_pdf:  # un ".pdf" que devuelve HTML, o al revés
        return None
    return str(r.url), r.content


def con_respaldo(url):
    if res := bajar(url):
        return res, "ok"
    alt = url.replace("www.afip.gob.ar", "www.arca.gob.ar")
    if alt != url and (res := bajar(alt)):
        return res, "mudada a arca.gob.ar"
    if url in REEMPLAZOS and (res := bajar(REEMPLAZOS[url])):
        return res, "caída: se usa la versión vigente"
    return None, "caída"


def servicio_de(archivo, origen, por_defecto="wsfev1"):
    """El web service al que pertenece un archivo según su nombre: 'Web-Service-MTXCA-v25.pdf' → wsmtxca."""
    a = archivo.lower().replace("-", "").replace("_", "")
    claves = [(k, c) for k in origen for c in {k.replace("_", ""), k.removeprefix("ws").replace("_", "")} if len(c) >= 4]
    return max((k for k, c in claves if c in a), key=len, default=por_defecto)


def enlazados(url, html):
    out = []
    for h in re.findall(r'href="([^"#]+)"', html.decode("utf-8", "ignore")):
        h = urllib.parse.urljoin(url, h.strip())
        if (h.lower().endswith(".pdf") or "wsdl" in h.lower()) and re.search(r"(afip|arca)\.gob\.ar", h):
            out.append(h)
    return list(dict.fromkeys(out))[:10]


if __name__ == "__main__":
    o = {k: {} for k in ("wsfev1", "wsmtxca", "wsseg", "wsct", "wsbfev1")}
    assert [servicio_de(a, o) for a in ("Web-Service-MTXCA-v25.pdf", "WSSEG-Manual.pdf", "Manual_Desarrollador_WSCT_v1.6.4.pdf",
                                         "wsbfev1-RG-5427-y-2861.pdf", "otro.pdf")] == ["wsmtxca", "wsseg", "wsct", "wsbfev1", "wsfev1"]
    assert tipo_de("https://x/y.asmx?WSDL") == "wsdl" and tipo_de("https://x/a.PDF") == "manual" and tipo_de("https://x/a.asp") == "web"
    origen = json.loads(ORIGEN.read_text())
    fuentes, informe, vistas = [], [], set()
    for ws, datos in origen.items():
        pendientes = [(u, None) for u in datos["entrypoints"]]
        while pendientes:
            url, desde = pendientes.pop(0)
            if url in vistas:
                continue
            vistas.add(url)
            res, estado = con_respaldo(url)
            informe.append({"ws": ws, "url": url, "estado": estado, "enlazado_desde": desde})
            if not res:
                continue
            final, contenido = res
            if ruta(final) in {ruta(u) for u in YA_EN_RARCA | {f["url"] for f in fuentes}} or VIEJOS.search(final):
                informe[-1]["estado"] += " (ya en RArca o versión vieja: no se agrega)"
                continue
            nombre = urllib.parse.unquote(final.rstrip("/").split("/")[-1].split("?")[0]) or ws
            # un PDF enlazado desde la página de un servicio puede ser de otro (la de factura electrónica enlaza los
            # manuales de WSSEG, WSCT, MTXCA y WSBFE): el título nombra el servicio del archivo, no el de la página
            servicio = servicio_de(nombre, origen) if desde else ws
            fuentes.append({"id": f"ws-{ws}-{len([f for f in fuentes if f['ws'] == ws]) + 1}", "ws": ws, "tipo": tipo_de(final),
                            "titulo": f"{origen[servicio]['name']}: {nombre}", "url": final, "fecha": FECHAS.get(final),
                            **({"vigente": False, "reemplazada_por": VIGENTES[final][0], "motivo": VIGENTES[final][1]}
                               if final in VIGENTES else {})})
            if tipo_de(final) == "web" and desde is None:  # como su crawler: solo desde las entradas, un nivel
                pendientes += [(u, url) for u in enlazados(final, contenido)]
    SALIDA.write_text(json.dumps(fuentes, ensure_ascii=False, indent=1))
    Path("data/descubrimiento_ws.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1))
    estados = {}
    for i in informe:
        estados[i["estado"]] = estados.get(i["estado"], 0) + 1
    print(f"{len(fuentes)} fuentes nuevas → {SALIDA} | {len(informe)} URLs revisadas:", estados)
