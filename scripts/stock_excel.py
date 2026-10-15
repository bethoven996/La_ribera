"""
Lee la hoja STOCK del Excel del Drive (opcional: si no existe, no pasa nada).

Columnas (la fila 1 son los títulos, en este orden):
    A Fecha      14/10/2026
    B Producto   igual que en la hoja PRECIOS (o PRECIO X KG)
    C Tipo       Conteo | Ingreso | Ajuste | Mínimo
    D Cantidad   4,5   (en kg para lo suelto, en unidades para lo envasado)
    E Unidad     kg | u
    F Nota       opcional

  Conteo   lo que hay en el local ese día (antes de abrir). Pisa todo lo anterior.
  Ingreso  mercadería que entró (suma).
  Ajuste   corrección: negativo si se venció o rompió (-0,5), positivo si sobraba.
  Mínimo   cantidad desde la que avisa que se está terminando.

Las ventas cargadas en el panel (y los pedidos web confirmados) se descuentan solas.
El código solo LEE esta hoja: nunca escribe en el Excel.
"""
from __future__ import annotations

import datetime as dt
import re

from import_excel import norm

TIPOS = {"conteo": "conteo", "inventario": "conteo", "ingreso": "ingreso", "entrada": "ingreso", "compra": "ingreso",
         "ajuste": "ajuste", "minimo": "minimo", "min": "minimo", "alerta": "minimo"}
UNIDADES = {"kg": "kg", "kilo": "kg", "kilos": "kg", "kgs": "kg", "g": "g", "gr": "g", "grs": "g", "gramos": "g",
            "u": "u", "un": "u", "unidad": "u", "unidades": "u", "uni": "u"}


def buscar_hoja_stock(hojas: dict):
    for nombre, filas in hojas.items():
        if norm(nombre).strip() == "stock":
            return filas
    return None


def fecha(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)):                       # Google Sheets: días desde 30/12/1899
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    m = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$", str(v))
    if m:
        d, mes, a = map(int, m.groups())
        try:
            return dt.date(a + 2000 if a < 100 else a, mes, d)
        except ValueError:
            return None
    return None


def numero(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return None
    t = str(v).strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):    # 1.250,5
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def leer_stock(hojas: dict, productos: dict, revisar: list) -> list[dict]:
    from reglas_web import buscar
    filas = buscar_hoja_stock(hojas)
    if not filas:
        return []
    movs = []
    for i, r in enumerate(filas[1:], start=2):
        r = tuple(r) + (None,) * 6
        if not any(r[:5]):
            continue
        nombre = str(r[1] or "").strip()
        f, tipo = fecha(r[0]), TIPOS.get(norm(str(r[2] or "")).strip())
        cant, unidad = numero(r[3]), UNIDADES.get(norm(str(r[4] or "")).strip().rstrip("."))
        problema = (not f and "fecha inválida (usá 14/10/2026)") or (not nombre and "falta el producto") \
            or (not tipo and "tipo inválido (Conteo, Ingreso, Ajuste o Mínimo)") \
            or (cant is None and "cantidad inválida") or (not unidad and "unidad inválida (kg o u)")
        k = None if problema else buscar(productos, nombre)
        if not problema and not k:
            problema = "no encuentro este producto en PRECIOS / PRECIO X KG (copiá el nombre igual)"
        if not problema and tipo in ("conteo", "ingreso", "minimo") and cant < 0:
            problema = "la cantidad no puede ser negativa (solo en Ajuste)"
        if problema:
            revisar.append(("STOCK", i, nombre, problema))
            continue
        if unidad == "g":                                  # 500 g -> 0,5 kg
            cant, unidad = cant / 1000, "kg"
        movs.append({"clave": k, "fecha": f.isoformat(), "tipo": tipo, "cantidad": round(cant, 3),
                     "unidad": unidad, "nota": (str(r[5]).strip()[:200] if r[5] else None), "fila": i})
    return movs
