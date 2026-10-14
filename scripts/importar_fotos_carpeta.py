"""
Carga fotos desde una carpeta donde cada archivo se llama como el producto en el Excel
(por ejemplo la carpeta del Drive que armaron Guille y Juli, descargada a la compu).

Uso:
    python scripts/importar_fotos_carpeta.py "C:/Users/Beto/Downloads/Fotos La Ribera"
    python scripts/importar_fotos_carpeta.py "carpeta" --probar      # muestra qué haría, sin copiar

- Busca en subcarpetas también (las secciones del Drive).
- Estas fotos son de los dueños: REEMPLAZAN a las que haya (de Google, Open Food Facts, etc.).
- Si el archivo se llama como un tamaño de un producto agrupado (ej. "Estevia kony liquida 500ml"),
  la foto va al producto agrupado ("Stevia Kony líquida").
- Al final lista los archivos que no pudo asociar, para renombrarlos o cargarlos con fotos_manual.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from difflib import get_close_matches
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
from import_excel import clave  # noqa: E402
from reglas_web import huella  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
FOTOS = RAIZ / "web" / "img" / "productos"
F_ORIGEN = RAIZ / "data" / "fotos" / "origen.json"
EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".jfif"}


def indice_productos():
    productos = json.loads((RAIZ / "data" / "seed" / "productos.json").read_text("utf-8"))
    por_clave = {p["clave"]: p for p in productos}
    por_huella: dict[frozenset, list[str]] = {}
    for p in productos:
        for nombre in {p["nombre_original"], p["nombre"]}:
            por_huella.setdefault(huella(nombre), []).append(p["clave"])
    # tamaños de productos agrupados -> producto agrupado
    archivo = RAIZ / "config" / "agrupar.json"
    if archivo.exists():
        for g in json.loads(archivo.read_text("utf-8")):
            kg = clave(g["nombre"])
            if kg in por_clave:
                for miembro in g["productos"]:
                    por_huella.setdefault(huella(miembro), []).insert(0, kg)
                    por_clave.setdefault(clave(miembro), por_clave[kg])
    return por_clave, por_huella


def asociar(nombre: str, por_clave, por_huella) -> tuple[dict | None, str]:
    k = clave(nombre)
    if k in por_clave:
        return por_clave[k], "exacto"
    candidatos = list(dict.fromkeys(por_huella.get(huella(nombre), [])))
    if len(candidatos) == 1:
        return por_clave[candidatos[0]], "exacto"
    parecido = get_close_matches(k, list(por_clave), n=1, cutoff=0.88)
    if parecido:
        return por_clave[parecido[0]], f"aproximado → {por_clave[parecido[0]]['nombre']}"
    return None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta")
    ap.add_argument("--probar", action="store_true", help="no copia nada, solo muestra")
    a = ap.parse_args()

    carpeta = Path(a.carpeta)
    if not carpeta.is_dir():
        sys.exit(f"No encuentro la carpeta {carpeta}")
    try:
        from pillow_heif import register_heif_opener  # fotos de iPhone (opcional)
        register_heif_opener()
    except ImportError:
        pass

    por_clave, por_huella = indice_productos()
    origen = json.loads(F_ORIGEN.read_text("utf-8")) if F_ORIGEN.exists() else {}
    FOTOS.mkdir(parents=True, exist_ok=True)

    ok, aprox, sin, errores = [], [], [], []
    for archivo in sorted(carpeta.rglob("*")):
        if archivo.suffix.lower() not in EXT_IMAGEN:
            continue
        p, como = asociar(archivo.stem, por_clave, por_huella)
        if not p:
            sin.append(archivo.relative_to(carpeta))
            continue
        (aprox if como.startswith("aprox") else ok).append(f"{archivo.name}  →  {p['nombre']}"
                                                           + (f"   ({como})" if como.startswith("aprox") else ""))
        if a.probar:
            continue
        try:
            im = ImageOps.exif_transpose(Image.open(archivo)).convert("RGB")
            im.thumbnail((700, 700))
            for e in (".webp", ".jpg", ".jpeg", ".png"):
                (FOTOS / f"{p['slug']}{e}").unlink(missing_ok=True)
            im.save(FOTOS / f"{p['slug']}.jpg", "JPEG", quality=84, optimize=True)
            origen[p["slug"]] = {"fuente": "dueños", "archivo": archivo.name, "revisada": True}
        except Exception as e:
            errores.append(f"{archivo.name}: {e}")

    if not a.probar:
        F_ORIGEN.parent.mkdir(parents=True, exist_ok=True)
        F_ORIGEN.write_text(json.dumps(origen, ensure_ascii=False, indent=1), "utf-8")

    print(f"\nAsociadas: {len(ok)}")
    if aprox:
        print(f"\nAsociadas por parecido ({len(aprox)}) — revisá que estén bien:")
        for x in aprox:
            print("  ", x)
    if sin:
        print(f"\nSin asociar ({len(sin)}) — el nombre del archivo no coincide con ningún producto:")
        for x in sin:
            print("  ", x)
    for x in errores:
        print("ERROR", x)
    if a.probar:
        print("\n(Prueba: no se copió nada. Sacá --probar para copiar.)")
    else:
        import armar_catalogo
        armar_catalogo.main()


if __name__ == "__main__":
    main()
