"""
Lee la planilla de La Ribera desde Google Sheets (SOLO LECTURA) y genera los datos para la web.

Uso:
    python scripts/sync_drive.py --out data/seed

Variables de entorno (.env, nunca al repo):
    GOOGLE_SHEET_ID              id de la planilla (lo que va entre /d/ y /edit en la URL)
    GOOGLE_SERVICE_ACCOUNT_FILE  ruta al JSON de la cuenta de servicio

La cuenta de servicio solo tiene permiso de Lector sobre ESA planilla y el scope es
spreadsheets.readonly: aunque el código quisiera, Google no le deja modificar nada.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from import_excel import HOJAS, EstructuraCambiada, guardar, procesar  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def hojas_desde_google(sheet_id: str, credenciales: str) -> dict[str, list[tuple]]:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(credenciales, scopes=SCOPES)
    api = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()

    titulos = [s["properties"]["title"] for s in api.get(spreadsheetId=sheet_id).execute()["sheets"]]
    # Solo las 3 hojas que usamos, en una sola llamada
    from import_excel import norm
    pedidas = [t for t in titulos if any(norm(t).endswith(norm(h)) for h in HOJAS.values())]
    res = api.values().batchGet(
        spreadsheetId=sheet_id,
        ranges=[f"'{t}'" for t in pedidas],
        valueRenderOption="UNFORMATTED_VALUE",   # números reales (2100, 0.35), no "$ 2.100" ni "35%"
    ).execute()
    return {t: [tuple(c if c != "" else None for c in fila) for fila in vr.get("values", [])]
            for t, vr in zip(pedidas, res["valueRanges"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/seed")
    ap.add_argument("--push", action="store_true", help="además carga los cambios en Supabase")
    ap.add_argument("--dry-run", action="store_true", help="muestra qué cambiaría en Supabase, sin guardar")
    a = ap.parse_args()

    from dotenv import load_dotenv
    raiz = Path(__file__).resolve().parent.parent
    load_dotenv(raiz / ".env")
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    cred = Path(os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"])
    if not cred.is_absolute():
        cred = raiz / cred
    if not cred.exists():
        sys.exit(f"No encuentro la clave en {cred}. Guardala ahí con ese nombre.")
    try:
        productos, revisar = procesar(hojas_desde_google(sheet_id, cred))
    except EstructuraCambiada as e:
        print(f"SYNC FRENADA: {e}\nLa web sigue con los últimos precios válidos.", file=sys.stderr)
        sys.exit(2)
    guardar(productos, revisar, a.out)

    if a.push or a.dry_run:
        from dataclasses import asdict
        from cargar_supabase import cargar, imprimir
        dsn = os.environ.get("DATABASE_URL") or sys.exit("Falta DATABASE_URL en el .env")
        res = cargar([asdict(p) for p in productos.values()], [list(r) for r in revisar], dsn, a.dry_run)
        imprimir(res, a.dry_run)


if __name__ == "__main__":
    main()
