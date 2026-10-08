"""
Carga los productos de la planilla en Supabase (Postgres).

Uso:
    python scripts/cargar_supabase.py --dry-run   # muestra qué cambiaría, no toca nada
    python scripts/cargar_supabase.py             # aplica los cambios

Lee data/seed/productos.json y data/seed/revisar.csv (los genera sync_drive.py).

Reglas:
  * La sync solo escribe lo que viene del Drive: nombre, categoría, precios, costos,
    proveedor. Nunca pisa fotos, descripciones ni tags que cargó el admin.
  * Nada se borra: si un producto desaparece de la planilla, queda inactivo
    (así no se pierde su historial de ventas).
  * Cada precio o costo que cambia queda en historial_precios.
  * Todo corre en UNA transacción: o se aplica completo, o no se aplica nada.

Variable de entorno:
    DATABASE_URL   connection string de Supabase (Session pooler). Es secreta.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
from import_excel import slug  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def dec(v):
    return None if v is None else Decimal(str(round(v, 2)))


def cargar(productos: list[dict], revisar: list[list], dsn: str, dry_run: bool = False) -> dict:
    res = {"nuevos": [], "precios_cambiados": [], "desactivados": [], "reactivados": []}

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # --- categorías ---
        cats = sorted({p["categoria"] for p in productos})
        for orden, nombre in enumerate(cats):
            cur.execute("""insert into public.categorias (slug, nombre, orden) values (%s, %s, %s)
                           on conflict (slug) do update set nombre = excluded.nombre""",
                        (slug(nombre), nombre, orden))
        cur.execute("select nombre, id from public.categorias")
        cat_id = dict(cur.fetchall())

        cur.execute("select clave, id, activo, slug from public.productos")
        existentes = {c: (i, a, s) for c, i, a, s in cur.fetchall()}
        slugs_usados = {s for _, _, s in existentes.values()}

        for p in productos:
            previo = existentes.get(p["clave"])
            if previo is None:
                s, n = p["slug"], 2
                while s in slugs_usados:
                    s, n = f'{p["slug"]}-{n}', n + 1
                slugs_usados.add(s)
                cur.execute("""insert into public.productos (clave, slug, nombre, categoria_id, activo)
                               values (%s, %s, %s, %s, %s) returning id""",
                            (p["clave"], s, p["nombre"], cat_id[p["categoria"]], p["activo"]))
                pid = cur.fetchone()[0]
                res["nuevos"].append(p["nombre"])
            else:
                pid, estaba_activo, _ = previo
                # slug NO se actualiza: cambiaría la URL del producto
                cur.execute("""update public.productos
                                  set nombre = %s, categoria_id = %s, activo = %s, en_planilla = true,
                                      actualizado_en = now()
                                where id = %s""",
                            (p["nombre"], cat_id[p["categoria"]], p["activo"], pid))
                if p["activo"] and not estaba_activo:
                    res["reactivados"].append(p["nombre"])
                elif estaba_activo and not p["activo"]:
                    res["desactivados"].append(p["nombre"])

            cur.execute("""insert into public.productos_privado (producto_id, proveedor, costo_base, nombre_original)
                           values (%s, %s, %s, %s)
                           on conflict (producto_id) do update
                           set proveedor = excluded.proveedor, costo_base = excluded.costo_base,
                               nombre_original = excluded.nombre_original""",
                        (pid, p["proveedor"], dec(p["costo_base"]), p["nombre_original"]))

            # --- presentaciones ---
            cur.execute("""select pr.etiqueta, pr.id, pr.precio, c.costo
                             from public.presentaciones pr
                             left join public.presentaciones_costos c on c.presentacion_id = pr.id
                            where pr.producto_id = %s""", (pid,))
            prev_pres = {e: (i, pr, co) for e, i, pr, co in cur.fetchall()}

            for pres in p["presentaciones"]:
                precio, costo = dec(pres["precio"]), dec(pres["costo"])
                cur.execute("""insert into public.presentaciones (producto_id, etiqueta, gramos, precio, activo)
                               values (%s, %s, %s, %s, true)
                               on conflict (producto_id, etiqueta) do update
                               set gramos = excluded.gramos, precio = excluded.precio, activo = true
                               returning id""",
                            (pid, pres["etiqueta"], pres["gramos"], precio))
                pres_id = cur.fetchone()[0]
                cur.execute("""insert into public.presentaciones_costos (presentacion_id, costo, margen)
                               values (%s, %s, %s)
                               on conflict (presentacion_id) do update
                               set costo = excluded.costo, margen = excluded.margen""",
                            (pres_id, costo, pres["margen"]))

                antes = prev_pres.pop(pres["etiqueta"], None)
                if antes is None or antes[1] != precio or antes[2] != costo:
                    cur.execute("""insert into public.historial_precios (presentacion_id, precio, costo)
                                   values (%s, %s, %s)""", (pres_id, precio, costo))
                    if antes is not None and antes[1] != precio:
                        res["precios_cambiados"].append(
                            f'{p["nombre"]} {pres["etiqueta"]}: {antes[1]} → {precio}')

            # presentaciones que ya no están en la planilla
            for _, (pres_id, _, _) in prev_pres.items():
                cur.execute("update public.presentaciones set activo = false where id = %s", (pres_id,))

        # --- productos que desaparecieron de la planilla ---
        claves = [p["clave"] for p in productos]
        cur.execute("""update public.productos set activo = false, en_planilla = false, actualizado_en = now()
                        where en_planilla and not (clave = any(%s)) returning nombre""", (claves,))
        res["desactivados"] += [r[0] for r in cur.fetchall()]

        resumen = {k: len(v) for k, v in res.items()} | {"total_planilla": len(productos)}
        cur.execute("insert into public.sync_log (ok, resumen, revisar) values (true, %s, %s)",
                    (json.dumps(resumen | {"detalle": res}, ensure_ascii=False),
                     json.dumps(revisar, ensure_ascii=False)))

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    return res


def imprimir(res: dict, dry_run: bool):
    print("SIMULACIÓN (no se guardó nada)" if dry_run else "Cambios aplicados")
    for k, v in res.items():
        print(f"  {k.replace('_', ' ')}: {len(v)}")
        for x in v[:10]:
            print(f"     - {x}")
        if len(v) > 10:
            print(f"     ... y {len(v) - 10} más")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(RAIZ / "data" / "seed"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Falta DATABASE_URL en el .env")

    seed = Path(a.seed)
    productos = json.loads((seed / "productos.json").read_text("utf-8"))
    with open(seed / "revisar.csv", encoding="utf-8-sig") as f:
        revisar = list(csv.reader(f))[1:]

    imprimir(cargar(productos, revisar, dsn, a.dry_run), a.dry_run)


if __name__ == "__main__":
    main()
