"""
Descarga a web/img/productos/ las fotos que encontró buscar_fotos.py.

Uso:
    python scripts/descargar_fotos.py              # solo las de confianza ALTA
    python scripts/descargar_fotos.py --revisar    # también las de "revisar" (miralas antes en reporte.html)
    python scripts/descargar_fotos.py --pisar      # reemplaza fotos que ya tengas

Nunca pisa una foto existente salvo con --pisar (así no se pierden las que saquen ellos).
Las achica a 600 px y escribe web/img/productos/CREDITOS.md (licencia CC BY-SA de Open Food Facts).
Después corré: python scripts/armar_catalogo.py
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
FOTOS = RAIZ / "web" / "img" / "productos"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--revisar", action="store_true")
    ap.add_argument("--pisar", action="store_true")
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    contacto = os.environ.get("OFF_CONTACTO") or sys.exit("Falta OFF_CONTACTO en el .env")

    sug = json.loads((RAIZ / "data" / "fotos" / "sugerencias.json").read_text("utf-8"))
    slug_de = {p["clave"]: p["slug"] for p in json.loads((RAIZ / "data" / "seed" / "productos.json").read_text("utf-8"))}
    estados = {"alta", "revisar"} if a.revisar else {"alta"}
    elegidas = [s for s in sug if s["estado"] in estados and s.get("imagen") and s["clave"] in slug_de]

    f_origen = RAIZ / "data" / "fotos" / "origen.json"
    origen = json.loads(f_origen.read_text("utf-8")) if f_origen.exists() else {}
    elegidas = [s for s in elegidas if not origen.get(slug_de[s["clave"]], {}).get("rechazada")]

    FOTOS.mkdir(parents=True, exist_ok=True)
    sesion = requests.Session()
    sesion.headers["User-Agent"] = f"LaRiberaCatalogo/0.1 ({contacto})"
    creditos, nuevas = [], 0
    for s in elegidas:
        slug = slug_de[s["clave"]]
        destino = FOTOS / f"{slug}.jpg"
        creditos.append(f"- {s['nombre']}: [{s.get('off_nombre') or 'Open Food Facts'}]({s['fuente']}) — {s['licencia']}")
        if destino.exists() and not a.pisar:
            continue
        try:
            r = sesion.get(s["imagen"], timeout=30)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            im.thumbnail((600, 600))
            im.save(destino, "JPEG", quality=82, optimize=True)
            origen[slug] = {"fuente": "off", "pagina": s["fuente"], "titulo": s.get("off_nombre"),
                            "puntaje": s.get("puntaje"), "revisada": False}
            nuevas += 1
            print(f"OK  {slug}")
        except Exception as e:
            print(f"ERR {slug}: {e}")
        time.sleep(1)   # imágenes: sin límite estricto, pero vamos tranquilos

    f_origen.write_text(json.dumps(origen, ensure_ascii=False, indent=1), "utf-8")
    (FOTOS / "CREDITOS.md").write_text(
        "# Créditos de imágenes\n\nFotos de Open Food Facts (https://openfoodfacts.org), "
        "licencia Creative Commons Attribution-ShareAlike (CC BY-SA).\n\n" + "\n".join(sorted(creditos)) + "\n", "utf-8")
    print(f"\n{nuevas} fotos nuevas.")
    sys.path.insert(0, str(Path(__file__).parent))
    import armar_catalogo
    armar_catalogo.main()
    print("Revisalas con: python scripts\\fotos_manual.py")


if __name__ == "__main__":
    main()
