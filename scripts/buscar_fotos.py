"""
Busca fotos de los productos ENVASADOS en Open Food Facts (base abierta, imágenes CC BY-SA).

Uso:
    python scripts/buscar_fotos.py              # busca todo (retoma donde quedó)
    python scripts/buscar_fotos.py --limite 20  # prueba con 20 productos

Necesita en el .env:
    OFF_CONTACTO=tu-email@ejemplo.com   (Open Food Facts pide identificarse)

Salida (en data/fotos/):
    sugerencias.json   una fila por producto: estado, foto sugerida, origen y licencia
    reporte.html       para revisar a ojo: nuestro nombre vs. lo que encontró, con la foto
    off_cache.json     respuestas guardadas: si cortás el script, retoma sin repetir búsquedas

Reglas de Open Food Facts que respetamos:
    - máximo 10 búsquedas por minuto (esperamos 6,5 s entre búsquedas)
    - User-Agent propio con contacto
    - las imágenes son CC BY-SA: hay que citar la fuente (guardamos el link de cada una)

Nada de esto se publica solo: son SUGERENCIAS para aprobar desde el panel.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
# Dos buscadores de Open Food Facts. Se prueba el primero; si falla, el segundo.
#   searchalicious: buscador nuevo (Elasticsearch), mejor para texto libre
#   legacy:         buscador viejo search.pl, se satura seguido
BUSCADORES = [
    ("searchalicious", "https://search.openfoodfacts.org/search"),
    ("legacy", "https://world.openfoodfacts.org/cgi/search.pl"),
]
CAMPOS = "code,product_name,product_name_es,brands,quantity,image_front_url,image_url"
ESPERA = 6.5

# Palabras que no ayudan a identificar el producto
VACIAS = {"de", "del", "la", "el", "los", "las", "con", "sin", "y", "x", "en", "a", "por", "para",
          "gr", "grs", "g", "kg", "ml", "cc", "u", "un", "unidad", "unidades", "s", "c"}


def texto(v) -> str:
    """El buscador nuevo devuelve algunos campos como lista (brands: ['Quimya'])."""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x)
    return str(v or "")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("s/", "sin ").replace("c/", "con ")
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def tokens(s: str) -> set[str]:
    return {t for t in norm(s).split() if t not in VACIAS and not t.isdigit() and len(t) > 1
            and not re.fullmatch(r"\d+(gr|g|kg|ml|cc|grs)?", t)}


def separar_marca(nombre: str) -> tuple[str, str | None]:
    """'Galletitas choco rellenas - Smams' -> ('Galletitas choco rellenas', 'Smams')"""
    partes = [p.strip() for p in re.split(r"\s+-\s+", nombre)]
    if len(partes) >= 2 and len(partes[-1].split()) <= 3:
        return " - ".join(partes[:-1]), partes[-1]
    return nombre, None


def consulta(nombre: str) -> str:
    base, marca = separar_marca(nombre)
    base = re.sub(r"\bx?\s*\d+[.,]?\d*\s*(gr|grs|g|kg|ml|cc|u)\b\.?", " ", base, flags=re.I)
    return re.sub(r"\s+", " ", f"{base} {marca or ''}").strip()


def parecida(t: str, conjunto: set[str]) -> bool:
    """yogurt ~ yogur, galletitas ~ galletita, almendras ~ almendra"""
    from difflib import SequenceMatcher
    return t in conjunto or any(SequenceMatcher(None, t, o).ratio() >= 0.85 for o in conjunto)


def puntuar(nuestro: str, cand: dict) -> float:
    """Qué parte de nuestras palabras aparece en el producto encontrado (0 a 1), exigiendo la marca."""
    base, marca = separar_marca(nuestro)
    nuestros = tokens(base)
    suyo = tokens(" ".join(texto(cand.get(k)) for k in ("product_name", "product_name_es", "brands")))
    if not nuestros or not suyo:
        return 0.0
    cobertura = sum(parecida(t, suyo) for t in nuestros) / len(nuestros)
    if marca:
        if not any(parecida(t, tokens(texto(cand.get("brands")))) for t in tokens(marca)):
            cobertura *= 0.3          # la marca no coincide: casi seguro es otro producto
    return round(cobertura, 2)


def params_de(motor: str, q: str) -> dict:
    if motor == "searchalicious":
        return {"q": q, "page_size": 8, "fields": CAMPOS, "langs": "es"}
    return {"search_terms": q, "search_simple": 1, "action": "process", "json": 1, "page_size": 8, "fields": CAMPOS}


def productos_de(datos) -> list[dict]:
    if not isinstance(datos, dict):
        return []
    return datos.get("hits") or datos.get("products") or []


caidos: set[str] = set()   # buscadores que fallaron varias veces en esta corrida


def buscar(sesion, q: str, cache: dict) -> list[dict]:
    if q in cache:
        return cache[q]
    errores = []
    for motor, url in BUSCADORES:
        if motor in caidos:
            continue
        for intento in range(3):
            try:
                r = sesion.get(url, params=params_de(motor, q), timeout=30)
            except requests.RequestException as e:
                errores.append(f"{motor}: {type(e).__name__}")
                break
            if r.status_code in (429, 503):
                espera = 20 * (intento + 1)
                print(f"   {motor} respondió {r.status_code} (saturado). Espero {espera} s…")
                time.sleep(espera)
                continue
            if not r.ok:
                errores.append(f"{motor}: HTTP {r.status_code} {r.text[:120]!r}")
                break
            try:
                prods = productos_de(r.json())
            except ValueError:
                errores.append(f"{motor}: no devolvió JSON ({r.text[:80]!r})")
                break
            cache[q] = prods
            time.sleep(ESPERA)
            return prods
        else:
            errores.append(f"{motor}: saturado 3 veces seguidas")
        caidos.add(motor)
        print(f"   Dejo de usar {motor} en esta corrida. Detalle: {errores[-1]}")
    raise RuntimeError("Ningún buscador de Open Food Facts respondió:\n  " + "\n  ".join(errores) +
                       "\nEl progreso quedó guardado. Probá más tarde o corré scripts/probar_off.py")


def elegir(nombre: str, prods: list[dict]) -> dict:
    con_foto = [p for p in prods if p.get("image_front_url") or p.get("image_url")]
    if not con_foto:
        return {"estado": "sin_resultado"}
    mejor = max(con_foto, key=lambda p: puntuar(nombre, p))
    s = puntuar(nombre, mejor)
    estado = "alta" if s >= 0.75 else "revisar" if s >= 0.4 else "sin_resultado"
    if estado == "alta" and separar_marca(nombre)[1] is None:
        estado = "revisar"   # sin marca no podemos asegurar que sea el mismo producto
    if estado == "sin_resultado":
        return {"estado": estado}
    code = mejor.get("code")
    return {
        "estado": estado, "puntaje": s,
        "off_codigo": code,
        "off_nombre": texto(mejor.get("product_name_es") or mejor.get("product_name")),
        "off_marca": texto(mejor.get("brands")), "off_cantidad": texto(mejor.get("quantity")),
        "imagen": mejor.get("image_front_url") or mejor.get("image_url"),
        "fuente": f"https://world.openfoodfacts.org/product/{code}",
        "licencia": "CC BY-SA 3.0 — Open Food Facts",
    }


def es_envasado(p: dict) -> bool:
    """Se vende cerrado: todo por unidad, o un único envase de 1 kg de marca ('Granola Granomax x1KG')."""
    pres = p["presentaciones"]
    if all(x["etiqueta"] == "unidad" for x in pres):
        return True
    return len(pres) == 1 and separar_marca(p["nombre_original"])[1] is not None


def reporte(filas: list[dict], destino: Path):
    orden = {"alta": 0, "revisar": 1, "sin_resultado": 2}
    filas = sorted(filas, key=lambda f: (orden[f["estado"]], f["nombre"]))
    cuenta = {k: sum(f["estado"] == k for f in filas) for k in orden}
    def fila(f):
        if f["estado"] == "sin_resultado":
            return f'<tr class="sin"><td>{html.escape(f["nombre"])}</td><td colspan="3">Sin resultado</td></tr>'
        return (f'<tr class="{f["estado"]}"><td>{html.escape(f["nombre"])}</td>'
                f'<td><img src="{html.escape(f["imagen"])}" loading="lazy" alt=""></td>'
                f'<td>{html.escape(str(f.get("off_nombre") or ""))}<br><small>{html.escape(str(f.get("off_marca") or ""))} '
                f'{html.escape(str(f.get("off_cantidad") or ""))}</small></td>'
                f'<td>{f["estado"]} ({f["puntaje"]})<br><a href="{html.escape(f["fuente"])}" target="_blank">ver en OFF</a></td></tr>')
    destino.write_text(f"""<!doctype html><meta charset="utf-8"><title>Fotos sugeridas — La Ribera</title>
<style>body{{font-family:system-ui;margin:24px;color:#2D3223;background:#F6F5EE}}table{{border-collapse:collapse;width:100%}}
td{{border-bottom:1px solid #ddd;padding:8px;vertical-align:middle}}img{{width:90px;height:90px;object-fit:contain;background:#fff}}
tr.alta td:last-child{{color:#3d6b2f}}tr.revisar td:last-child{{color:#9a6a12}}tr.sin{{color:#999}}</style>
<h1>Fotos sugeridas</h1><p>Confianza alta: {cuenta['alta']} · Para revisar: {cuenta['revisar']} · Sin resultado: {cuenta['sin_resultado']}</p>
<p>Imágenes de Open Food Facts, licencia CC BY-SA. Nada se publica sin aprobación.</p>
<table><tr><th>Nuestro producto</th><th>Foto</th><th>Encontrado</th><th>Confianza</th></tr>
{''.join(fila(f) for f in filas)}</table>""", "utf-8")
    return cuenta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    contacto = os.environ.get("OFF_CONTACTO")
    if not contacto:
        sys.exit("Agregá OFF_CONTACTO=tu-email al .env (Open Food Facts pide un contacto).")

    productos = json.loads((RAIZ / "data" / "seed" / "productos.json").read_text("utf-8"))
    envasados = [p for p in productos if p["activo"] and es_envasado(p)]
    if a.limite:
        envasados = envasados[: a.limite]

    carpeta = RAIZ / "data" / "fotos"
    carpeta.mkdir(parents=True, exist_ok=True)
    f_cache = carpeta / "off_cache.json"
    cache = json.loads(f_cache.read_text("utf-8")) if f_cache.exists() else {}

    sesion = requests.Session()
    sesion.headers["User-Agent"] = f"LaRiberaCatalogo/0.1 ({contacto})"

    pendientes = sum(consulta(p["nombre"]) not in cache for p in envasados)
    print(f"{len(envasados)} productos envasados. Búsquedas nuevas: {pendientes} "
          f"(~{pendientes * ESPERA / 60:.0f} min). Podés cortar con Ctrl+C y retomar.")

    filas = []
    try:
        for i, p in enumerate(envasados, 1):
            q = consulta(p["nombre"])
            nuevo = q not in cache
            res = elegir(p["nombre"], buscar(sesion, q, cache))
            filas.append({"clave": p["clave"], "nombre": p["nombre"], "consulta": q, **res})
            if nuevo:
                f_cache.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
                print(f"[{i}/{len(envasados)}] {res['estado']:13} {p['nombre']}")
    except KeyboardInterrupt:
        print("\nCortado. El progreso quedó guardado; volvé a correrlo para seguir.")

    (carpeta / "sugerencias.json").write_text(json.dumps(filas, ensure_ascii=False, indent=2), "utf-8")
    cuenta = reporte(filas, carpeta / "reporte.html")
    print(f"\nListo. Alta: {cuenta['alta']} | Revisar: {cuenta['revisar']} | Sin resultado: {cuenta['sin_resultado']}")
    print(f"Abrí {carpeta / 'reporte.html'} en el navegador para verlas.")


if __name__ == "__main__":
    main()
