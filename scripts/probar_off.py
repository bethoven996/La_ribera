"""
Diagnóstico: prueba los buscadores de Open Food Facts con UNA búsqueda y muestra qué responden.
Uso:  python scripts/probar_off.py
      python scripts/probar_off.py "granola granix"
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from buscar_fotos import BUSCADORES, params_de, productos_de  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
contacto = os.environ.get("OFF_CONTACTO") or sys.exit("Falta OFF_CONTACTO en el .env")
q = sys.argv[1] if len(sys.argv) > 1 else "yogur quimya"

s = requests.Session()
s.headers["User-Agent"] = f"LaRiberaCatalogo/0.1 ({contacto})"
for motor, url in BUSCADORES:
    print(f"\n=== {motor}  ({url})")
    try:
        r = s.get(url, params=params_de(motor, q), timeout=30)
        print("HTTP", r.status_code, "| tipo:", r.headers.get("content-type"))
        try:
            prods = productos_de(r.json())
            print("resultados:", len(prods))
            for p in prods[:3]:
                print("  -", p.get("product_name") or p.get("product_name_es"), "|", p.get("brands"),
                      "| foto:", "sí" if (p.get("image_front_url") or p.get("image_url")) else "no")
        except ValueError:
            print("No es JSON. Primeros caracteres:", r.text[:300])
    except requests.RequestException as e:
        print("Error de conexión:", e)
