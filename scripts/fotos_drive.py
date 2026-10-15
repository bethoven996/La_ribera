"""
Trae las fotos de una carpeta de Google Drive (SOLO LECTURA) y las pone en la web.

Cómo lo usan los dueños:
    En la carpeta "Fotos La Ribera" del Drive suben la foto con el MISMO NOMBRE que el
    producto en el Excel (ej. "Almendra sin cascara guara 6.jpg"). Listo: en menos de una
    hora aparece en la página. Si cambian la foto (mismo nombre), se actualiza sola.

Uso:
    python scripts/fotos_drive.py            # baja las nuevas o cambiadas
    python scripts/fotos_drive.py --probar   # solo muestra qué haría

Necesita (en el .env o en los secretos de GitHub):
    GOOGLE_SERVICE_ACCOUNT_FILE   la misma clave que usa sync_drive.py
    GOOGLE_FOTOS_FOLDER_ID        id de la carpeta (lo que va después de /folders/ en la URL)
La carpeta tiene que estar compartida con el mail de la cuenta de servicio, como Lector.

Las fotos quedan en web/img/productos/<slug>.jpg. Si los dueños subieron una foto desde
el panel, esa tiene prioridad (la decide armar_catalogo.py).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
from importar_fotos_carpeta import asociar, indice_productos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
FOTOS = RAIZ / "web" / "img" / "productos"
ESTADO = FOTOS / "drive_estado.json"          # qué archivo del Drive ya se bajó (para no repetir)
REPORTE = RAIZ / "web" / "data" / "fotos_drive.json"   # lo muestra el panel: archivos sin asociar
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
CARPETA = "application/vnd.google-apps.folder"


def listar(api, carpeta_id: str, ruta: str = "") -> list[dict]:
    """Imágenes de la carpeta y sus subcarpetas."""
    salida, token = [], None
    while True:
        r = api.files().list(q=f"'{carpeta_id}' in parents and trashed = false",
                             fields="nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime)",
                             pageSize=1000, pageToken=token,
                             supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        for f in r.get("files", []):
            if f["mimeType"] == CARPETA:
                salida += listar(api, f["id"], f"{ruta}{f['name']}/")
            elif f["mimeType"].startswith("image/"):
                f["ruta"] = ruta + f["name"]
                salida.append(f)
        token = r.get("nextPageToken")
        if not token:
            return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probar", action="store_true", help="no baja nada, solo muestra")
    a = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
    except ImportError:
        pass
    carpeta = os.environ.get("GOOGLE_FOTOS_FOLDER_ID")
    if not carpeta:
        print("Sin GOOGLE_FOTOS_FOLDER_ID: no se buscan fotos en el Drive.")
        return
    cred = Path(os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"])
    if not cred.is_absolute():
        cred = RAIZ / cred
    try:
        from pillow_heif import register_heif_opener   # fotos de iPhone (opcional)
        register_heif_opener()
    except ImportError:
        pass

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    api = build("drive", "v3", credentials=Credentials.from_service_account_file(str(cred), scopes=SCOPES),
                cache_discovery=False)

    archivos = listar(api, carpeta)
    por_clave, por_huella = indice_productos()
    estado = json.loads(ESTADO.read_text("utf-8")) if ESTADO.exists() else {}
    FOTOS.mkdir(parents=True, exist_ok=True)

    nuevas, sin_asociar, errores, usados = [], [], [], {}
    # si hay dos archivos para el mismo producto, gana el más reciente
    for f in sorted(archivos, key=lambda x: x.get("modifiedTime", "")):
        p, como = asociar(Path(f["name"]).stem, por_clave, por_huella)
        if not p:
            sin_asociar.append(f["ruta"])
            continue
        usados[p["slug"]] = (f, p, como)

    for slug, (f, p, como) in usados.items():
        firma = f.get("md5Checksum") or f.get("modifiedTime")
        if estado.get(slug, {}).get("firma") == firma and (FOTOS / f"{slug}.jpg").exists():
            continue                                   # ya estaba bajada y no cambió
        nuevas.append(f"{f['ruta']}  →  {p['nombre']}" + (f"   ({como})" if como.startswith("aprox") else ""))
        if a.probar:
            continue
        try:
            buf, req = io.BytesIO(), api.files().get_media(fileId=f["id"])
            dl = MediaIoBaseDownload(buf, req)
            while not dl.next_chunk()[1]:
                pass
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(buf.getvalue()))).convert("RGB")
            im.thumbnail((700, 700))
            for e in (".webp", ".jpeg", ".png"):
                (FOTOS / f"{slug}{e}").unlink(missing_ok=True)
            im.save(FOTOS / f"{slug}.jpg", "JPEG", quality=84, optimize=True)
            estado[slug] = {"firma": firma, "archivo": f["ruta"]}
        except Exception as e:                          # una foto rota no frena las demás
            errores.append(f"{f['ruta']}: {e.__class__.__name__}")

    print(f"Fotos en el Drive: {len(archivos)} | nuevas o cambiadas: {len(nuevas)} | sin asociar: {len(sin_asociar)}")
    for x in nuevas:
        print("  +", x)
    for x in sin_asociar:
        print("  ? sin producto con ese nombre:", x)
    for x in errores:
        print("  ERROR", x)
    if a.probar:
        print("(Prueba: no se bajó nada.)")
        return
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    REPORTE.parent.mkdir(parents=True, exist_ok=True)
    reporte = {"sin_asociar": sorted(sin_asociar), "errores": errores}
    viejo = json.loads(REPORTE.read_text("utf-8")) if REPORTE.exists() else {}
    if {k: viejo.get(k) for k in reporte} != reporte or nuevas:   # no generar cambios (ni deploys) de más
        reporte["revisado"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
        REPORTE.write_text(json.dumps(reporte, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
