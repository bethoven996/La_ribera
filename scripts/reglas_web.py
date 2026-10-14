"""
Reglas que deciden QUÉ se muestra en la web, además de los precios del Excel.

1) Ocultar productos (sin stock, no se venden más):
   En la hoja PRECIOS, agregá una columna al final con el título "Web".
   Si en esa columna ponés NO, el producto no aparece en la web.
   Para que vuelva a aparecer, borrás el NO.

2) Venta por kilo (presentación "1 kg" que sale de la hoja PRECIO X KG):
   - Si la hoja PRECIO X KG tiene una columna "Web": solo se ofrece 1 kg en las filas con SI.
   - Si no la tiene: se usa la lista de config/venta_por_kilo.txt.
   Los envases cerrados de 1 kg de la hoja PRECIOS (ej. "Granola Granomax x1KG") no se tocan.

3) Agrupar tamaños de un mismo producto en una sola tarjeta (config/agrupar.json):
   ej. "Stevia Kony líquida" con opciones 100 ml / 200 ml / 500 ml.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from import_excel import Presentacion, Producto, clave, nombre_visible, norm, slug

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config"

# Palabras que no distinguen productos al comparar nombres
_RUIDO = {"x", "de", "del", "la", "el", "con", "c", "s", "sin", "kg", "xkg", "x1kg", "1kg", "kgs"}
_TAMANIO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|cc|grs?|g|kg|lts?|l)\b", re.I)


def huella(nombre: str) -> frozenset[str]:
    """Conjunto de palabras significativas: 'Granola tradicional xkg - Mandala raiz'
    y 'Granola tradicional mandala raiz xkg' dan lo mismo."""
    palabras = re.sub(r"[^a-z0-9 ]+", " ", norm(nombre)).split()
    return frozenset(p for p in palabras if p not in _RUIDO and not re.fullmatch(r"x?\d+(kg|gr?|ml)?", p))


def buscar(productos: dict[str, Producto], nombre: str) -> str | None:
    """Clave del producto que corresponde a un nombre escrito a mano."""
    k = clave(nombre)
    if k in productos:
        return k
    h = huella(nombre)
    candidatos = [c for c, p in productos.items() if huella(p.nombre_original) == h]
    return candidatos[0] if len(candidatos) == 1 else None


def _columna_web(filas) -> int | None:
    if not filas:
        return None
    for i, titulo in enumerate(filas[0]):
        if titulo and norm(str(titulo)).strip().startswith("web"):
            return i
    return None


def _valor(v) -> str:
    return norm(str(v or "")).strip()


def ocultar(tabla_precios, productos, revisar):
    col = _columna_web(tabla_precios)
    if col is None:
        return 0
    n = 0
    for i, r in enumerate(tabla_precios[1:], start=2):
        nombre = r[1]
        if not nombre or _valor(r[col]) not in ("no", "n", "sin stock", "0"):
            continue
        k = clave(nombre)
        if k in productos:
            productos[k].activo = False
            productos[k].oculto = True
            n += 1
    return n


def limitar_kilo(tabla_kg, productos, revisar) -> tuple[int, list[str]]:
    """Saca la presentación de 1 kg (hoja PRECIO X KG) a los que no se venden por kilo."""
    col = _columna_web(tabla_kg)
    permitidos: set[str] = set()
    sin_match: list[str] = []
    if col is not None:
        for r in tabla_kg[1:]:
            if r[1] and _valor(r[col]) in ("si", "s", "x"):
                k = buscar(productos, r[1])
                if k:
                    permitidos.add(k)
    else:
        archivo = CONFIG / "venta_por_kilo.txt"
        if not archivo.exists():
            return 0, []                       # sin regla: se deja todo como viene
        for linea in archivo.read_text("utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            k = buscar(productos, linea)
            if k:
                permitidos.add(k)
            else:
                sin_match.append(linea)
    quitados = 0
    for k, p in productos.items():
        if k in permitidos:
            continue
        antes = len(p.presentaciones)
        p.presentaciones = [x for x in p.presentaciones if x.origen != "PRECIO X KG"]
        quitados += antes - len(p.presentaciones)
    for linea in sin_match:
        revisar.append(("config/venta_por_kilo.txt", "", linea, "no encontré este producto en el Excel"))
    return quitados, sin_match


def _etiqueta_tamanio(nombre: str) -> tuple[str, int | None, float]:
    """'Estevia kony liquida 200ml' -> ('200 ml', None, 200)"""
    m = list(_TAMANIO.finditer(nombre))
    if not m:
        return "unidad", None, 0
    valor, unidad = m[-1].group(1).replace(",", "."), m[-1].group(2).lower()
    n = float(valor)
    if unidad in ("ml", "cc"):
        return f"{n:g} ml", None, n
    if unidad.startswith("l"):
        return f"{n:g} l", None, n * 1000
    if unidad == "kg":
        return f"{n:g} kg", int(n * 1000), n * 1000
    return f"{n:g} g", int(n), n


def agrupar(productos, revisar) -> int:
    archivo = CONFIG / "agrupar.json"
    if not archivo.exists():
        return 0
    grupos = json.loads(archivo.read_text("utf-8"))
    hechos = 0
    for g in grupos:
        miembros = []
        for nombre in g["productos"]:
            k = buscar(productos, nombre)
            if k:
                miembros.append(k)
            else:
                revisar.append(("config/agrupar.json", "", nombre, f"no encontré este producto para '{g['nombre']}'"))
        if len(miembros) < 2:
            continue
        base = productos[miembros[0]]
        nuevo = Producto(slug(g["nombre"]), g["nombre"], g["nombre"], g.get("categoria") or base.categoria,
                         base.costo_base, proveedor=base.proveedor)
        filas = []
        for k in miembros:
            p = productos.pop(k)
            if not p.activo and getattr(p, "oculto", False):
                continue                       # un tamaño marcado NO en la columna Web
            etiqueta, gramos, orden = _etiqueta_tamanio(p.nombre_original)
            for x in p.presentaciones:
                filas.append((orden, Presentacion(etiqueta, gramos, x.precio, x.costo, x.margen, x.origen)))
        nuevo.presentaciones = [x for _, x in sorted(filas, key=lambda t: t[0])]
        nuevo.orden_fijo = True
        productos[clave(g["nombre"])] = nuevo
        hechos += 1
    return hechos


def aplicar(tablas, productos, revisar) -> dict:
    return {
        "ocultos": ocultar(tablas["precios"], productos, revisar),
        "kilo_quitados": limitar_kilo(tablas["kg"], productos, revisar)[0],
        "agrupados": agrupar(productos, revisar),
    }
