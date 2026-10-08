"""
Página para REVISAR las fotos automáticas y CARGAR A MANO las que faltan.

Uso:
    python scripts/fotos_manual.py
    → se abre http://localhost:8001 en el navegador

En cada producto:
    - "Buscar en Google" abre la búsqueda ya armada en otra pestaña
    - arrastrá la imagen sobre el producto, o copiala (clic derecho > Copiar imagen)
      y pegala con Ctrl+V después de hacer clic en el producto
    - "Está bien" aprueba una foto automática; "Quitar" la borra (y no se vuelve a poner sola)

Solo escucha en tu compu (127.0.0.1): nadie de afuera puede entrar.
Cada cambio actualiza web/data/catalogo.json al toque.
"""
from __future__ import annotations

import io
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import armar_catalogo  # noqa: E402
from buscar_fotos import es_envasado, separar_marca  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
FOTOS = RAIZ / "web" / "img" / "productos"
F_ORIGEN = RAIZ / "data" / "fotos" / "origen.json"
EXTENSIONES = (".webp", ".jpg", ".jpeg", ".png")
PUERTO = 8001
SLUG_OK = re.compile(r"^[a-z0-9-]+$")
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
candado = threading.Lock()


def leer_origen() -> dict:
    return json.loads(F_ORIGEN.read_text("utf-8")) if F_ORIGEN.exists() else {}


def escribir_origen(o: dict):
    F_ORIGEN.parent.mkdir(parents=True, exist_ok=True)
    F_ORIGEN.write_text(json.dumps(o, ensure_ascii=False, indent=1), "utf-8")


def foto_de(slug: str) -> str | None:
    for e in EXTENSIONES:
        if (FOTOS / f"{slug}{e}").exists():
            return f"{slug}{e}"
    return None


def borrar_fotos(slug: str):
    for e in EXTENSIONES:
        (FOTOS / f"{slug}{e}").unlink(missing_ok=True)


def guardar_imagen(slug: str, datos: bytes):
    im = Image.open(io.BytesIO(datos)).convert("RGB")
    if min(im.size) < 120:
        raise ValueError("La imagen es muy chica (menos de 120 px). Buscá una más grande.")
    im.thumbnail((600, 600))
    borrar_fotos(slug)
    FOTOS.mkdir(parents=True, exist_ok=True)
    im.save(FOTOS / f"{slug}.jpg", "JPEG", quality=82, optimize=True)


def lista_productos() -> list[dict]:
    productos = json.loads((RAIZ / "data" / "seed" / "productos.json").read_text("utf-8"))
    origen = leer_origen()
    salida = []
    for p in productos:
        if not p["activo"]:
            continue
        o = origen.get(p["slug"], {})
        f = foto_de(p["slug"])
        if f and o.get("fuente") in ("brave", "off") and not o.get("revisada"):
            estado = "revisar"
        elif f:
            estado = "con_foto"
        else:
            estado = "sin_foto"
        salida.append({"slug": p["slug"], "nombre": p["nombre"], "categoria": p["categoria"],
                       "envasado": es_envasado(p), "marca": separar_marca(p["nombre"])[1],
                       "foto": f, "estado": estado, "fuente": o.get("fuente"), "titulo": o.get("titulo")})
    return salida


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio en la consola
        pass

    def responder(self, codigo=200, cuerpo=b"", tipo="application/json"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def json(self, obj, codigo=200):
        self.responder(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def slug(self) -> str | None:
        s = (parse_qs(urlparse(self.path).query).get("slug") or [""])[0]
        return s if SLUG_OK.match(s) else None

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta == "/":
            return self.responder(200, PAGINA.encode("utf-8"), "text/html; charset=utf-8")
        if ruta == "/api/productos":
            return self.json(lista_productos())
        if ruta.startswith("/fotos/"):
            nombre = ruta.removeprefix("/fotos/")
            archivo = FOTOS / nombre
            if re.match(r"^[a-z0-9-]+\.(jpg|jpeg|png|webp)$", nombre) and archivo.exists():
                return self.responder(200, archivo.read_bytes(), "image/jpeg")
        self.responder(404, b"no encontrado", "text/plain")

    def do_POST(self):
        ruta, slug = urlparse(self.path).path, self.slug()
        if not slug:
            return self.json({"error": "Producto inválido"}, 400)
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else b""
        try:
            with candado:
                origen = leer_origen()
                if ruta == "/api/subir":
                    guardar_imagen(slug, cuerpo)
                    origen[slug] = {"fuente": "manual", "revisada": True}
                elif ruta == "/api/subir_url":
                    url = json.loads(cuerpo or b"{}").get("url", "")
                    if not url.startswith(("http://", "https://")):
                        raise ValueError("No es un link de imagen válido.")
                    r = requests.get(url, timeout=20, headers={"User-Agent": NAVEGADOR})
                    r.raise_for_status()
                    guardar_imagen(slug, r.content)
                    origen[slug] = {"fuente": "manual", "pagina": url, "revisada": True}
                elif ruta == "/api/aprobar":
                    origen.setdefault(slug, {})["revisada"] = True
                elif ruta == "/api/quitar":
                    borrar_fotos(slug)
                    origen[slug] = {"rechazada": True}   # fotos_brave.py no la vuelve a poner
                else:
                    return self.json({"error": "Acción desconocida"}, 404)
                escribir_origen(origen)
                armar_catalogo.main()
        except Exception as e:
            return self.json({"error": str(e) or type(e).__name__}, 400)
        self.json({"ok": True, "foto": foto_de(slug)})


PAGINA = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Fotos — La Ribera</title>
<style>
:root{--papel:#F6F5EE;--sup:#fff;--tinta:#2D3223;--suave:#626852;--linea:#E2E1D3;--salvia:#989F75;--boton:#5B6343;--ok:#4D7A3A;--mal:#A4472F;--rio:#7E9998}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:var(--papel);color:var(--tinta)}
header{position:sticky;top:0;z-index:5;background:var(--salvia);color:#FBF3E0;padding:12px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
header h1{font-size:18px;margin:0 12px 0 0}
.tab{border:1.5px solid #FBF3E0;background:none;color:#FBF3E0;border-radius:999px;padding:6px 14px;cursor:pointer;font:inherit}
.tab[aria-pressed=true]{background:#FBF3E0;color:var(--tinta)}
header input{margin-left:auto;border:0;border-radius:999px;padding:8px 14px;min-width:220px;font:inherit}
main{padding:20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.p{background:var(--sup);border:2px solid transparent;border-radius:14px;padding:12px;display:grid;grid-template-columns:110px 1fr;gap:12px;cursor:pointer}
.p.activa{border-color:var(--rio)}.p.arrastrando{border-color:var(--ok);background:#eef5ea}
.img{width:110px;height:110px;border-radius:10px;background:#efece2;display:grid;place-items:center;overflow:hidden;font-size:12px;color:var(--suave);text-align:center;padding:6px}
.img img{width:100%;height:100%;object-fit:contain;background:#fff}
.n{font-weight:600;line-height:1.25;margin-bottom:2px}.c{font-size:12px;color:var(--suave)}
.t{font-size:11px;color:var(--suave);margin-top:4px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.acc{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.acc a,.acc button,.acc label{font:inherit;font-size:13px;border-radius:999px;padding:5px 10px;border:1.5px solid var(--boton);background:none;color:var(--tinta);cursor:pointer;text-decoration:none}
.acc .si{background:var(--ok);border-color:var(--ok);color:#fff}.acc .no{border-color:var(--mal);color:var(--mal)}
.acc input{display:none}
.msg{font-size:12px;margin-top:6px;min-height:1em}.msg.err{color:var(--mal)}.msg.ok{color:var(--ok)}
.ayuda{grid-column:1/-1;background:var(--sup);border-radius:12px;padding:12px 16px;font-size:14px;color:var(--suave);line-height:1.5}
.vacio{grid-column:1/-1;padding:40px;text-align:center;color:var(--suave)}
</style></head><body>
<header><h1>Fotos de productos</h1>
<button class="tab" data-f="revisar">Para revisar <span id="n-revisar"></span></button>
<button class="tab" data-f="sin_foto">Sin foto <span id="n-sin_foto"></span></button>
<button class="tab" data-f="con_foto">Con foto <span id="n-con_foto"></span></button>
<input id="q" type="search" placeholder="Filtrar por nombre…"></header>
<main id="lista"></main>
<script>
let todos=[], filtro="revisar", activa=null;
const $=s=>document.querySelector(s), esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const norm=s=>s.normalize("NFD").replace(/[̀-ͯ]/g,"").toLowerCase();
async function cargar(){ todos=await (await fetch("/api/productos")).json();
  for(const k of ["revisar","sin_foto","con_foto"]) $("#n-"+k).textContent="("+todos.filter(p=>p.estado===k).length+")";
  if(filtro==="revisar" && !todos.some(p=>p.estado==="revisar")) filtro="sin_foto";
  pintar(); }
function pintar(){
  document.querySelectorAll(".tab").forEach(b=>b.setAttribute("aria-pressed", b.dataset.f===filtro));
  const q=norm($("#q").value.trim());
  // sin foto: primero envasados con marca (más fáciles de encontrar)
  const lista=todos.filter(p=>p.estado===filtro && (!q||norm(p.nombre).includes(q)))
    .sort((a,b)=>(b.envasado&&!!b.marca)-(a.envasado&&!!a.marca)||a.categoria.localeCompare(b.categoria)||a.nombre.localeCompare(b.nombre));
  const ayuda={revisar:"Estas fotos se pusieron solas. Si la foto es del producto correcto tocá <b>Está bien</b>; si no, <b>Quitar</b> (no se vuelve a poner sola).",
    sin_foto:"Tocá <b>Buscar en Google</b>, elegí la imagen y <b>arrastrala</b> sobre el producto. O clic derecho en la imagen → <b>Copiar imagen</b>, hacé clic en el producto acá y pegá con <b>Ctrl+V</b>.",
    con_foto:"Fotos ya aprobadas o cargadas a mano. Para cambiar una, arrastrá o pegá otra encima."}[filtro];
  $("#lista").innerHTML=`<div class="ayuda">${ayuda}</div>`+(lista.length?lista.slice(0,200).map(p=>`
   <div class="p" data-s="${p.slug}" tabindex="0">
    <div class="img">${p.foto?`<img src="/fotos/${p.foto}?v=${Date.now()}" alt="">`:"Arrastrá o pegá la foto acá"}</div>
    <div><div class="n">${esc(p.nombre)}</div><div class="c">${esc(p.categoria)}${p.fuente?" · "+esc(p.fuente):""}</div>
     ${p.titulo?`<div class="t" title="${esc(p.titulo)}">Encontrada como: ${esc(p.titulo)}</div>`:""}
     <div class="acc">
      <a href="https://www.google.com/search?tbm=isch&q=${encodeURIComponent(p.nombre.replace(/\s+-\s+/," "))}" target="_blank" rel="noopener">Buscar en Google</a>
      <label>Archivo<input type="file" accept="image/*"></label>
      ${p.estado==="revisar"?`<button class="si" data-a="aprobar">Está bien</button>`:""}
      ${p.foto?`<button class="no" data-a="quitar">Quitar</button>`:""}
     </div><div class="msg"></div></div></div>`).join("")+(lista.length>200?`<div class="vacio">Mostrando 200 de ${lista.length}. Usá el filtro para ver el resto.</div>`:"")
   :`<div class="vacio">No hay productos acá.</div>`);
}
function aviso(card,t,ok){const m=card.querySelector(".msg"); m.textContent=t; m.className="msg "+(ok?"ok":"err");}
async function accion(card,ruta,body,headers){
  aviso(card,"Guardando…",true);
  try{ const r=await fetch(ruta+"?slug="+card.dataset.s,{method:"POST",body,headers}); const d=await r.json();
    if(!r.ok) throw new Error(d.error); await cargar();
    const nueva=document.querySelector(`.p[data-s="${card.dataset.s}"]`); if(nueva) aviso(nueva,"Listo",true);
  }catch(e){ aviso(card,e.message||"No se pudo guardar",false); } }
async function subirDesde(card,dt){
  const archivo=[...(dt.files||[])].find(f=>f.type.startsWith("image/")) || [...(dt.items||[])].map(i=>i.kind==="file"?i.getAsFile():null).find(f=>f&&f.type.startsWith("image/"));
  if(archivo) return accion(card,"/api/subir",archivo);
  let url=dt.getData&&dt.getData("text/uri-list"); const html=dt.getData&&dt.getData("text/html");
  if(html){ const m=html.match(/<img[^>]+src="([^"]+)"/i); if(m) url=m[1].replace(/&amp;/g,"&"); }
  if(url&&url.startsWith("data:image")) return accion(card,"/api/subir",await (await fetch(url)).blob());
  if(url&&/^https?:/.test(url)) return accion(card,"/api/subir_url",JSON.stringify({url}),{"Content-Type":"application/json"});
  aviso(card,"Eso no es una imagen. Probá con clic derecho → Copiar imagen.",false);
}
$("#lista").addEventListener("click",e=>{const card=e.target.closest(".p"); if(!card) return;
  document.querySelectorAll(".p.activa").forEach(x=>x.classList.remove("activa")); card.classList.add("activa"); activa=card;
  const b=e.target.closest("button[data-a]"); if(b) accion(card,"/api/"+b.dataset.a);});
$("#lista").addEventListener("change",e=>{if(e.target.type==="file"&&e.target.files[0]) accion(e.target.closest(".p"),"/api/subir",e.target.files[0]);});
$("#lista").addEventListener("dragover",e=>{const c=e.target.closest(".p"); if(c){e.preventDefault(); c.classList.add("arrastrando");}});
$("#lista").addEventListener("dragleave",e=>{const c=e.target.closest(".p"); if(c) c.classList.remove("arrastrando");});
$("#lista").addEventListener("drop",e=>{const c=e.target.closest(".p"); if(!c) return; e.preventDefault(); c.classList.remove("arrastrando"); subirDesde(c,e.dataTransfer);});
document.addEventListener("paste",e=>{ if(!activa||(e.target instanceof Element && e.target.matches("input"))) return; e.preventDefault(); subirDesde(activa,e.clipboardData);});
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{filtro=b.dataset.f; pintar();});
$("#q").oninput=pintar;
cargar();
</script></body></html>"""


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    url = f"http://localhost:{PUERTO}"
    print(f"Abierto en {url}  (Ctrl+C para cerrar)")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")


if __name__ == "__main__":
    main()
