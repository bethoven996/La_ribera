"""
Importa el Excel de precios de La Ribera y genera el seed de la base.

Uso:
    python scripts/import_excel.py STOCK_AGOSTO_23_8.xlsx --out data/seed

Fuentes (por hoja):
    PRECIOS      -> presentaciones fraccionadas (100 g, 250 g...) o por unidad
    PRECIO X KG  -> presentación de 1 kg (solo si tiene precio redondeado)
    Hoja 1       -> proveedor de cada producto (solo uso interno, nunca va al front)

Salida:
    categorias.json, productos.json (con presentaciones anidadas), revisar.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path

import openpyxl

# Nombres de categoría prolijos y únicos (las hojas los escriben distinto)
CATEGORIAS = {
    "cereales y legumbres": "Cereales y legumbres",
    "frutos secos": "Frutos secos",
    "semillas": "Semillas",
    "harinas y derivados": "Harinas y derivados",
    "panificados": "Panificados",
    "granolas y barritas": "Granolas y barritas",
    "almacen ( snacks / fideos secos, otros)": "Almacén",
    "bebidas vegetales / yogurt / jugos/ refriregados": "Bebidas y refrigerados",
    "untables": "Untables",
    "congelados": "Congelados",
    "endulzantes": "Endulzantes",
    "especias y condimentos": "Especias y condimentos",
    "especias/ condimentos / sales": "Especias y condimentos",
    "yuyos y te": "Yuyos y té",
    "yerba": "Yerba",
}

# Sufijo "por kilo" que no aporta al nombre: "x 1kg", "1 kg", "x kg", "x1kg"
KILO_RE = re.compile(r"\s*\bx?\s*(1\s*)?kgs?\b\.?\s*$", re.I)
# Cualquier tamaño ("x300gr", "2,5 kg"): solo para cruzar con la hoja de proveedores
TAMANIO_RE = re.compile(r"\s*\bx?\s*\d*[.,]?\d*\s*(kg|kgs|gr|grs|g)\b\.?\s*$", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def nombre_visible(nombre: str) -> str:
    s = re.sub(r"\s+", " ", str(nombre)).strip()
    s = KILO_RE.sub("", s).strip(" -")
    return s[:1].upper() + s[1:]


def clave(nombre: str) -> str:
    """Clave para cruzar el mismo producto entre PRECIOS y PRECIO X KG."""
    return norm(nombre_visible(nombre))


def clave_amplia(nombre: str) -> str:
    """Ignora cualquier tamaño: Hoja 1 lista bultos de proveedor ("x 2,5 kg")."""
    s = norm(nombre)
    for _ in range(2):
        s = TAMANIO_RE.sub("", s).strip(" -")
    return s


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Presentacion:
    etiqueta: str            # "250 g", "1 kg", "unidad"
    gramos: int | None       # None = se vende por unidad
    precio: float | None
    costo: float | None      # costo total (incluye packaging y reposición)
    margen: float | None
    origen: str              # hoja de donde salió


@dataclass
class Producto:
    slug: str
    nombre: str
    nombre_original: str
    categoria: str
    costo_base: float | None          # costo x kg o unidad
    proveedor: str | None = None
    activo: bool = True
    clave: str = ""                   # identifica al producto entre syncs
    presentaciones: list[Presentacion] = field(default_factory=list)


def etiqueta(gramos):
    if gramos is None:
        return "unidad"
    return f"{gramos / 1000:g} kg" if gramos >= 1000 else f"{gramos} g"


def es_categoria(nombre, *valores) -> bool:
    return norm(nombre) in CATEGORIAS and all(v is None for v in valores)


def leer_precios(filas, productos, revisar):
    cat = None
    for i, r in enumerate(filas[1:], start=2):
        nombre = r[1]
        if not nombre or not str(nombre).strip():
            continue
        costo_base, frac = num(r[2]), num(r[3])
        if es_categoria(nombre, costo_base):
            cat = CATEGORIAS[norm(nombre)]
            continue
        if costo_base is None:
            revisar.append(("PRECIOS", i, nombre, "fila sin costo, se ignora"))
            continue

        k = clave(nombre)
        if k in productos:
            revisar.append(("PRECIOS", i, nombre, "producto duplicado, se ignora la segunda fila"))
            continue

        gramos = int(frac) if frac else None
        if gramos is None and KILO_RE.search(str(nombre).strip()):
            gramos = 1000   # envase cerrado de 1 kg: "Granola Granomax Natural x1KG"
        precio, costo = num(r[10]), num(r[7])
        p = Producto(slug(nombre_visible(nombre)), nombre_visible(nombre), str(nombre).strip(),
                     cat or "Sin categoría", costo_base)
        p.presentaciones.append(Presentacion(etiqueta(gramos), gramos, precio, costo, num(r[8]), "PRECIOS"))
        productos[k] = p
        validar(p.presentaciones[-1], "PRECIOS", i, nombre, revisar)


def leer_precio_kg(filas, productos, revisar):
    cat = None
    for i, r in enumerate(filas[1:], start=2):
        nombre = r[1]
        if not nombre or not str(nombre).strip():
            continue
        costo_base = num(r[2])
        if es_categoria(nombre, costo_base):
            cat = CATEGORIAS[norm(nombre)]
            continue
        precio = num(r[8])
        if not precio:          # en esta hoja la mayoría no tiene precio: no se vende por kg
            continue

        pres = Presentacion("1 kg", 1000, precio, num(r[5]), num(r[6]), "PRECIO X KG")
        k = clave(nombre)
        p = productos.get(k)
        if p is None:
            p = Producto(slug(nombre_visible(nombre)), nombre_visible(nombre), str(nombre).strip(),
                         cat or "Sin categoría", costo_base)
            productos[k] = p
        existente = next((x for x in p.presentaciones if x.gramos == 1000), None)
        if existente and existente.precio:
            continue
        if existente:   # la de PRECIOS no tenía precio: la reemplaza la de PRECIO X KG
            p.presentaciones.remove(existente)
            revisar[:] = [r for r in revisar if not (r[2] == p.nombre_original and "sin precio" in r[3])]
        p.presentaciones.append(pres)
        validar(pres, "PRECIO X KG", i, nombre, revisar)


def leer_proveedores(filas, productos):
    indice = {}
    for p in productos.values():
        indice.setdefault(clave_amplia(p.nombre_original), []).append(p)
    for r in filas[1:]:
        nombre, prov = r[2], r[3]
        if not (nombre and prov):
            continue
        for p in productos.get(clave(nombre)) and [productos[clave(nombre)]] or indice.get(clave_amplia(nombre), []):
            p.proveedor = p.proveedor or str(prov).strip()


def validar(pres, hoja, fila, nombre, revisar):
    if not pres.precio:
        revisar.append((hoja, fila, nombre, f"{pres.etiqueta}: sin precio de venta"))
    elif pres.costo and pres.precio < pres.costo:
        revisar.append((hoja, fila, nombre,
                        f"{pres.etiqueta}: precio ${pres.precio:,.0f} menor al costo ${pres.costo:,.0f}"))


HOJAS = {"precios": "PRECIOS", "kg": "PRECIO X KG", "proveedores": "Hoja 1"}
# Encabezados mínimos que tiene que tener cada hoja (columna -> texto esperado)
ENCABEZADOS = {
    "precios": {1: "producto", 2: "costo x kg", 3: "fraccionado", 7: "costo total", 10: "precio redondeado"},
    "kg": {1: "producto", 2: "costo x kg", 5: "costo total", 8: "precio redondeado"},
    "proveedores": {2: "producto", 3: "proveedor"},
}


class EstructuraCambiada(Exception):
    """La planilla cambió de forma: la sync se frena y la web sigue con los últimos precios válidos."""


def buscar_hoja(hojas: dict, nombre: str):
    if nombre in hojas:
        return hojas[nombre]
    for k, v in hojas.items():          # tolera "2 PRECIOS", espacios, mayúsculas
        if norm(k).endswith(norm(nombre)):
            return v
    raise EstructuraCambiada(f"No encuentro la hoja '{nombre}'. Hojas: {list(hojas)}")


def chequear_encabezados(filas, clave_hoja):
    enc = [norm(c) if c else "" for c in (filas[0] if filas else [])]
    for col, esperado in ENCABEZADOS[clave_hoja].items():
        if col >= len(enc) or not enc[col].startswith(esperado):
            raise EstructuraCambiada(
                f"Hoja {HOJAS[clave_hoja]}: en la columna {chr(65 + col)} esperaba '{esperado}' "
                f"y encontré '{enc[col] if col < len(enc) else ''}'")


def procesar(hojas: dict[str, list[tuple]]):
    """hojas: {nombre_hoja: [fila1, fila2, ...]} con la fila 1 = encabezados.
    Funciona igual con el .xlsx o con Google Sheets."""
    tablas = {}
    for k, nombre in HOJAS.items():
        filas = buscar_hoja(hojas, nombre)
        chequear_encabezados(filas, k)
        ancho = max((len(f) for f in filas), default=0)
        tablas[k] = [tuple(f) + (None,) * (ancho - len(f)) for f in filas]   # Sheets corta celdas vacías

    productos: dict[str, Producto] = {}
    revisar: list[tuple] = []
    leer_precios(tablas["precios"], productos, revisar)
    leer_precio_kg(tablas["kg"], productos, revisar)
    leer_proveedores(tablas["proveedores"], productos)

    # Slugs únicos + desactivar productos sin ningún precio válido
    vistos = {}
    for p in productos.values():
        n = vistos.get(p.slug, 0)
        vistos[p.slug] = n + 1
        if n:
            p.slug = f"{p.slug}-{n + 1}"
        p.presentaciones.sort(key=lambda x: (x.gramos is None, x.gramos or 0))
        if not any(x.precio for x in p.presentaciones):
            p.activo = False
    for k, p in productos.items():
        p.clave = k
    return productos, revisar


def hojas_desde_xlsx(path) -> dict[str, list[tuple]]:
    # data_only=True: valores calculados, no fórmulas. El archivo solo se LEE.
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    return {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb}


def guardar(productos, revisar, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cats = sorted({p.categoria for p in productos.values()})
    (out / "categorias.json").write_text(
        json.dumps([{"slug": slug(c), "nombre": c} for c in cats], ensure_ascii=False, indent=2), "utf-8")
    (out / "productos.json").write_text(
        json.dumps([asdict(p) for p in productos.values()], ensure_ascii=False, indent=2), "utf-8")
    with open(out / "revisar.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["hoja", "fila", "producto", "problema"])
        w.writerows(revisar)

    activos = sum(p.activo for p in productos.values())
    n_pres = sum(len(p.presentaciones) for p in productos.values())
    print(f"Productos: {len(productos)} ({activos} activos) | Presentaciones: {n_pres} | "
          f"Categorías: {len(cats)} | Para revisar: {len(revisar)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("excel")
    ap.add_argument("--out", default="data/seed")
    a = ap.parse_args()
    productos, revisar = procesar(hojas_desde_xlsx(a.excel))
    guardar(productos, revisar, a.out)


if __name__ == "__main__":
    main()
