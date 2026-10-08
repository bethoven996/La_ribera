"""
Arma web/data/catalogo.json: lo que ve el cliente (nombre, categoría, presentaciones y precios).
NUNCA incluye costos, márgenes ni proveedores.

También detecta las fotos: si existe web/img/productos/<slug>.jpg (o .jpeg/.png/.webp),
el producto la muestra. Para saber el slug de cada producto, mirá web/data/slugs.csv.

Uso:
    python scripts/armar_catalogo.py
Correrlo después de sync_drive.py y cada vez que agregues fotos.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SEED = RAIZ / "data" / "seed" / "productos.json"
WEB = RAIZ / "web"
FOTOS = WEB / "img" / "productos"
EXTENSIONES = (".webp", ".jpg", ".jpeg", ".png")


def foto_de(slug: str) -> str | None:
    for ext in EXTENSIONES:
        if (FOTOS / f"{slug}{ext}").exists():
            return f"{slug}{ext}"
    return None


def main():
    productos = json.loads(SEED.read_text("utf-8"))
    FOTOS.mkdir(parents=True, exist_ok=True)
    catalogo, con_foto = [], 0
    for p in productos:
        if not p["activo"]:
            continue
        pres = [{"e": x["etiqueta"], "g": x["gramos"], "p": round(x["precio"])}
                for x in p["presentaciones"] if x["precio"]]
        if not pres:
            continue
        item = {"s": p["slug"], "n": p["nombre"], "c": p["categoria"], "v": pres}
        if f := foto_de(p["slug"]):
            item["f"] = f
            con_foto += 1
        catalogo.append(item)

    (WEB / "data").mkdir(parents=True, exist_ok=True)
    (WEB / "data" / "catalogo.json").write_text(
        json.dumps(catalogo, ensure_ascii=False, separators=(",", ":")), "utf-8")
    with open(WEB / "data" / "slugs.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["slug (nombre del archivo de foto)", "producto", "categoria", "tiene_foto"])
        for it in sorted(catalogo, key=lambda x: (x["c"], x["n"])):
            w.writerow([it["s"], it["n"], it["c"], "si" if "f" in it else ""])

    huerfanas = [f.name for f in FOTOS.iterdir()
                 if f.suffix.lower() in EXTENSIONES and f.stem not in {c["s"] for c in catalogo}]
    print(f"Catálogo: {len(catalogo)} productos, {con_foto} con foto.")
    if huerfanas:
        print(f"Ojo: {len(huerfanas)} fotos no coinciden con ningún slug (revisá el nombre): {huerfanas[:5]}")


if __name__ == "__main__":
    main()
