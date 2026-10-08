"""
Pone fotos AUTOMÁTICAMENTE a los productos envasados que todavía no tienen, usando la
búsqueda de imágenes de Brave. Solo pone la foto si el título del resultado coincide
con el NOMBRE y la MARCA del producto. Lo dudoso queda para cargar a mano con fotos_manual.py.

Uso:
    python scripts/fotos_brave.py --limite 10   # prueba
    python scripts/fotos_brave.py               # todos los que no tienen foto

Necesita en el .env:
    BRAVE_API_KEY=...   (https://brave.com/search/api — plan gratis: 2.000 búsquedas/mes)

Nunca pisa una foto existente. Guarda de dónde salió cada foto en data/fotos/origen.json.
Al final corre armar_catalogo.py solo.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from buscar_fotos import consulta, es_envasado, puntuar, separar_marca, tokens  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
FOTOS = RAIZ / "web" / "img" / "productos"
URL = "https://api.search.brave.com/res/v1/images/search"
EXTENSIONES = (".webp", ".jpg", ".jpeg", ".png")
UMBRAL = 0.75          # mismo criterio que con Open Food Facts
ESPERA = 1.1           # plan gratis: 1 búsqueda por segundo
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def tiene_foto(slug: str) -> bool:
    return any((FOTOS / f"{slug}{e}").exists() for e in EXTENSIONES)


def candidatos(sesion, q: str) -> list[dict]:
    r = sesion.get(URL, params={"q": q, "count": 10, "country": "AR", "search_lang": "es", "safesearch": "strict"},
                   timeout=30)
    if r.status_code == 429:
        time.sleep(5)
        r = sesion.get(URL, params={"q": q, "count": 10, "country": "AR", "search_lang": "es"}, timeout=30)
    if r.status_code in (401, 403):
        sys.exit(f"Brave rechazó la API key (HTTP {r.status_code}). Revisá BRAVE_API_KEY en el .env.")
    r.raise_for_status()
    return r.json().get("results") or []


def puntaje(nombre: str, res: dict) -> float:
    """Usa el título y el sitio del resultado como si fueran 'nombre' y 'marca'."""
    titulo = res.get("title") or ""
    sitio = urlparse(res.get("url") or "").netloc
    return puntuar(nombre, {"product_name": titulo, "brands": f"{titulo} {sitio} {res.get('source') or ''}"})


def bajar(res: dict) -> Image.Image | None:
    for url in ((res.get("properties") or {}).get("url"), (res.get("thumbnail") or {}).get("src")):
        if not url:
            continue
        try:
            # sin la API key: la imagen se pide directo al sitio, no a Brave
            r = requests.get(url, timeout=20, headers={"User-Agent": NAVEGADOR})
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            if min(im.size) >= 150:           # descarta miniaturas inservibles
                return im
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    key = os.environ.get("BRAVE_API_KEY") or sys.exit("Falta BRAVE_API_KEY en el .env")

    productos = json.loads((RAIZ / "data" / "seed" / "productos.json").read_text("utf-8"))
    f_origen = RAIZ / "data" / "fotos" / "origen.json"
    f_origen.parent.mkdir(parents=True, exist_ok=True)
    origen = json.loads(f_origen.read_text("utf-8")) if f_origen.exists() else {}

    pendientes = [p for p in productos if p["activo"] and es_envasado(p) and not tiene_foto(p["slug"])
                  and separar_marca(p["nombre"])[1]                     # sin marca: no se puede asegurar, va a mano
                  and not origen.get(p["slug"], {}).get("rechazada")]   # la quitaste a mano: no insistir
    if a.limite:
        pendientes = pendientes[: a.limite]
    FOTOS.mkdir(parents=True, exist_ok=True)

    sesion = requests.Session()
    sesion.headers.update({"X-Subscription-Token": key, "Accept": "application/json"})
    print(f"{len(pendientes)} envasados con marca y sin foto. Búsquedas: {len(pendientes)} "
          f"(~{len(pendientes) * ESPERA / 60:.0f} min).")

    puestas = dudosas = 0
    try:
        for i, p in enumerate(pendientes, 1):
            res = candidatos(sesion, consulta(p["nombre"]))
            time.sleep(ESPERA)
            ordenados = sorted(res, key=lambda r: puntaje(p["nombre"], r), reverse=True)
            mejor = ordenados[0] if ordenados else None
            s = puntaje(p["nombre"], mejor) if mejor else 0
            if not mejor or s < UMBRAL:
                dudosas += 1
                print(f"[{i}/{len(pendientes)}] a mano   {p['nombre']}")
                continue
            im = bajar(mejor)
            if im is None:
                dudosas += 1
                print(f"[{i}/{len(pendientes)}] a mano   {p['nombre']} (no se pudo bajar la imagen)")
                continue
            im.thumbnail((600, 600))
            im.save(FOTOS / f"{p['slug']}.jpg", "JPEG", quality=82, optimize=True)
            origen[p["slug"]] = {"fuente": "brave", "pagina": mejor.get("url"), "titulo": mejor.get("title"),
                                 "puntaje": s, "revisada": False}
            f_origen.write_text(json.dumps(origen, ensure_ascii=False, indent=1), "utf-8")
            puestas += 1
            print(f"[{i}/{len(pendientes)}] PUESTA   {p['nombre']}  ←  {mejor.get('title')}")
    except KeyboardInterrupt:
        print("\nCortado. Lo hecho quedó guardado; volvé a correrlo para seguir.")

    print(f"\nFotos puestas: {puestas} | Para cargar a mano: {dudosas}")
    import armar_catalogo
    armar_catalogo.main()
    print("Revisalas y completá las que faltan con: python scripts\\fotos_manual.py")


if __name__ == "__main__":
    main()
