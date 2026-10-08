# La Ribera — Almacén saludable

Tienda online de La Ribera: catálogo con precios sincronizados desde Google Sheets, pedido por WhatsApp
y (próximamente) panel del dueño con estadísticas.

## Estructura

```
web/                    ← LA TIENDA (lo que ve el cliente)
  index.html            estructura de la página
  css/estilos.css       estilos (colores y tipografías arriba de todo, en :root)
  js/app.js             lógica: catálogo, buscador, pedido, WhatsApp, formas de pago
  data/catalogo.json    productos y precios (lo genera scripts/armar_catalogo.py)
  data/slugs.csv        lista de slugs: el nombre que tiene que tener cada foto
  img/productos/        fotos de productos: <slug>.jpg
scripts/
  sync_drive.py         lee la planilla del Drive → data/seed/ (y --push a Supabase)
  import_excel.py       lo mismo pero desde un .xlsx
  armar_catalogo.py     data/seed/ → web/data/catalogo.json (solo datos públicos)
  buscar_fotos.py       busca fotos en Open Food Facts → data/fotos/reporte.html
  descargar_fotos.py    baja las fotos aprobadas a web/img/productos/
  cargar_supabase.py    carga productos e historial de precios en Supabase
supabase/migrations/    tablas, seguridad y reglas de pago (correr en orden)
tests/                  pruebas de seguridad de la base
```

## Ver la tienda en tu compu

```powershell
python -m http.server 8000 -d web
```
Abrí http://localhost:8000 (hace falta el servidor: abriendo index.html con doble clic no carga el catálogo).

## Actualizar precios desde el Drive

```powershell
python scripts\sync_drive.py
python scripts\armar_catalogo.py
```

## Fotos de productos

**1. Automático** (solo pone la foto si coinciden nombre Y marca):
```powershell
python scripts\buscar_fotos.py          # Open Food Facts (~35 min, se puede cortar y retomar)
python scripts\descargar_fotos.py       # baja las de confianza alta
python scripts\fotos_brave.py           # Brave para el resto (necesita BRAVE_API_KEY en .env)
```

**2. Revisar y completar a mano:**
```powershell
python scripts\fotos_manual.py          # abre http://localhost:8001
```
- *Para revisar*: fotos puestas solas → "Está bien" o "Quitar" (si la quitás no se vuelve a poner sola).
- *Sin foto*: "Buscar en Google", y arrastrá la imagen sobre el producto o copiala y pegá con Ctrl+V.

Cada cambio actualiza la tienda al toque. Una foto cargada a mano nunca la pisa un script.

## Datos que NO van al repo

`data/`, `.env`, `secrets/` y los `.xlsx` están en `.gitignore`: tienen costos, proveedores y claves.
