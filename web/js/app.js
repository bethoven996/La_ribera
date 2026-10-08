let CATALOGO = [];
const DIRECCION = "3 de Febrero 780, Rosario"; // se carga desde data/catalogo.json (lo genera scripts/armar_catalogo.py)
const WHATSAPP = "5493417206755"; // 341 720-6755, formato wa.me: 54 9 + característica sin 0 + número

const ORDEN_CAT = [
  "Frutos secos",
  "Semillas",
  "Cereales y legumbres",
  "Harinas y derivados",
  "Granolas y barritas",
  "Panificados",
  "Endulzantes",
  "Untables",
  "Almacén",
  "Bebidas y refrigerados",
  "Congelados",
  "Especias y condimentos",
  "Yuyos y té",
  "Yerba",
];
const TONO = {
  "Frutos secos": 32,
  Semillas: 70,
  "Cereales y legumbres": 48,
  "Harinas y derivados": 40,
  "Granolas y barritas": 24,
  Panificados: 28,
  Endulzantes: 12,
  Untables: 18,
  Almacén: 80,
  "Bebidas y refrigerados": 190,
  Congelados: 200,
  "Especias y condimentos": 8,
  "Yuyos y té": 110,
  Yerba: 95,
};

const $ = (s) => document.querySelector(s);
const plata = (n) => "$" + Math.round(n).toLocaleString("es-AR");
const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const esc = (s) =>
  s.replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );

let categoria = null,
  busqueda = "";
let carrito = {};
try {
  carrito = JSON.parse(localStorage.getItem("ribera-carrito") || "{}");
} catch (e) {
  carrito = {};
}
const guardar = () => {
  try {
    localStorage.setItem("ribera-carrito", JSON.stringify(carrito));
  } catch (e) {}
};
const claveItem = (p, v) => p.id + "|" + v.e;
let porId = new Map();

/* ---------- Categorías ---------- */
function pintarEstantes() {
  const cuenta = {};
  CATALOGO.forEach((p) => (cuenta[p.c] = (cuenta[p.c] || 0) + 1));
  const cats = ORDEN_CAT.filter((c) => cuenta[c]);
  $("#estantes").innerHTML =
    `<button class="chip" type="button" data-cat="" aria-pressed="${!categoria}">Todos<small class="num">${CATALOGO.length}</small></button>` +
    cats
      .map(
        (c) =>
          `<button class="chip" type="button" data-cat="${esc(c)}" aria-pressed="${categoria === c}">${esc(c)}<small class="num">${cuenta[c]}</small></button>`,
      )
      .join("");
}
$("#estantes").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (!b) return;
  categoria = b.dataset.cat || null;
  pintarBanner();
  pintarEstantes();
  pintarGrilla();
  const activo = document.querySelector('.chip[aria-pressed="true"]');
  activo?.scrollIntoView({
    block: "nearest",
    inline: "center",
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
  });
  activo?.focus({ preventScroll: true });
  actualizarFlechas();
});
$("#buscar").addEventListener("input", (e) => {
  busqueda = norm(e.target.value.trim());
  pintarGrilla();
});

/* ---------- Productos ---------- */
function xKg(v) {
  return v.g && v.g !== 1000
    ? `<span class="xkg num">${plata((v.p * 1000) / v.g)} el kg</span>`
    : "";
}

function tarjeta(p) {
  const v = p.v[p.sel],
    k = claveItem(p, v),
    cant = carrito[k] || 0;
  const pres =
    p.v.length > 1
      ? `<div class="presentaciones" role="group" aria-label="Presentación">${p.v
          .map(
            (x, i) =>
              `<button class="pres" type="button" data-pres="${i}" aria-pressed="${i === p.sel}">${esc(x.e === "unidad" ? "Unidad" : x.e)}</button>`,
          )
          .join("")}</div>`
      : `<div class="pres-unica">${v.e === "unidad" ? "Por unidad" : "Bolsa de " + esc(v.e)}</div>`;
  const accion = cant
    ? `<div class="contador" aria-label="Cantidad"><button type="button" data-menos aria-label="Quitar uno">−</button><span class="num">${cant}</span><button type="button" data-mas aria-label="Agregar uno">+</button></div>`
    : `<button class="agregar" type="button" data-mas>Agregar</button>`;
  return `<article class="producto" data-id="${p.id}">
    ${
      p.f
        ? `<div class="frasco con-foto"><img src="img/productos/${esc(p.f)}" alt="${esc(p.n)}" loading="lazy" width="400" height="320"><span class="peso-foto num">${v.e === "unidad" ? "x 1" : esc(v.e)}</span></div>`
        : `<div class="frasco" style="--h:${TONO[p.c] ?? 60}"><div class="etiqueta"><span class="peso num">${v.e === "unidad" ? "x 1" : esc(v.e)}</span><span class="cat">${esc(p.c)}</span></div></div>`
    }
    <div class="datos">
      <h3>${esc(p.n)}</h3>
      ${pres}
      <div class="precio-fila"><div class="precio num">${plata(v.p)}${xKg(v)}</div>${accion}</div>
    </div>
  </article>`;
}

function filtrados() {
  const palabras = busqueda.split(/\s+/).filter(Boolean);
  return CATALOGO.filter(
    (p) =>
      (!categoria || p.c === categoria) &&
      palabras.every((w) => p.k.includes(w)),
  );
}

function pintarGrilla() {
  const lista = filtrados();
  $("#titulo-lista").textContent = busqueda
    ? `Resultados para “${$("#buscar").value.trim()}”`
    : categoria || "Todos los productos";
  $("#conteo").textContent =
    lista.length === 1 ? "1 producto" : `${lista.length} productos`;
  $("#grilla").innerHTML = lista.length
    ? lista.map(tarjeta).join("")
    : `<div class="vacio"><strong>No encontramos ese producto</strong>Probá con otra palabra o mirá todas las categorías.</div>`;
}

function repintarTarjeta(id) {
  const el = document.querySelector(`.producto[data-id="${id}"]`);
  if (el) el.outerHTML = tarjeta(porId.get(id));
}

$("#grilla").addEventListener("click", (e) => {
  const card = e.target.closest(".producto");
  if (!card) return;
  const p = porId.get(card.dataset.id),
    v = p.v[p.sel],
    k = claveItem(p, v);
  if (e.target.closest("[data-pres]")) {
    p.sel = +e.target.closest("[data-pres]").dataset.pres;
  } else if (e.target.closest("[data-mas]")) {
    const antes = carrito[k] || 0;
    carrito[k] = Math.min(99, antes + 1);
    if (!antes) avisarAgregado(p, v);
  } else if (e.target.closest("[data-menos]")) {
    carrito[k] = (carrito[k] || 0) - 1;
    if (carrito[k] <= 0) delete carrito[k];
  } else return;
  guardar();
  repintarTarjeta(p.id);
  pintarCuenta();
});

/* ---------- Aviso "agregado" ---------- */
let timerAviso;
function avisarAgregado(p, v) {
  let el = $("#aviso-agregado");
  if (!el) {
    el = document.createElement("div");
    el.id = "aviso-agregado";
    el.className = "aviso-agregado";
    el.setAttribute("role", "status");
    document.body.append(el);
  }
  el.innerHTML = `<span>Agregaste ${esc(p.n)} (${v.e === "unidad" ? "unidad" : esc(v.e)})</span><button type="button" id="aviso-ver">Ver pedido</button>`;
  el.hidden = false;
  clearTimeout(timerAviso);
  timerAviso = setTimeout(() => (el.hidden = true), 3500);
}
document.addEventListener("click", (e) => {
  if (e.target.id === "aviso-ver") {
    $("#aviso-agregado").hidden = true;
    pintarPanel();
    abrir($("#panel"));
  }
});

/* ---------- Carrito ---------- */
function items() {
  return Object.entries(carrito)
    .map(([k, cant]) => {
      const [id, e] = k.split("|");
      const p = porId.get(id);
      const v = p && p.v.find((x) => x.e === e);
      return p && v ? { k, p, v, cant } : null;
    })
    .filter(Boolean);
}
const totalCarrito = () => items().reduce((s, i) => s + i.v.p * i.cant, 0);
function pintarCuenta() {
  $("#cuenta").textContent = items().reduce((s, i) => s + i.cant, 0);
}

let datos = {
  nombre: "",
  apellido: "",
  pago: "",
  entrega: "retiro",
  direccion: "",
  notas: "",
};
const PAGOS = {
  efectivo: "Efectivo",
  transferencia: "Transferencia",
  credito: "Tarjeta de crédito",
};
const ALIAS = "La.ribera780";
const MINIMO_DESC_EFECTIVO = 20000; // "superando los $20.000": estrictamente mayor
function calcularPago(subtotal, pago) {
  if (pago === "efectivo" && subtotal > MINIMO_DESC_EFECTIVO)
    return {
      ajuste: -Math.round(subtotal * 0.1),
      texto: "Descuento efectivo (10%)",
    };
  if (pago === "credito")
    return {
      ajuste: Math.round(subtotal * 0.1),
      texto: "Recargo tarjeta de crédito (10%)",
    };
  return { ajuste: 0, texto: "" };
}
function htmlInfoPago() {
  const sub = totalCarrito();
  if (datos.pago === "efectivo")
    return sub > MINIMO_DESC_EFECTIVO
      ? `<div class="info-pago bien">Pagando en efectivo tenés <strong>10% de descuento</strong>.</div>`
      : `<div class="info-pago">Si tu pedido supera los ${plata(MINIMO_DESC_EFECTIVO)}, en efectivo tenés 10% de descuento. Te faltan <strong class="num">${plata(MINIMO_DESC_EFECTIVO - sub)}</strong> para superar ese monto.</div>`;
  if (datos.pago === "transferencia")
    return `<div class="info-pago alias"><span>Alias para transferir<strong>${ALIAS}</strong></span>
      <button type="button" class="btn-copiar-alias" id="btn-alias">Copiar alias</button></div>`;
  if (datos.pago === "credito")
    return `<div class="info-pago">Con tarjeta de crédito hay un <strong>10% de recargo</strong>.</div>`;
  return "";
}
function htmlTotales() {
  const sub = totalCarrito(),
    { ajuste, texto } = calcularPago(sub, datos.pago);
  return (
    (ajuste
      ? `<div class="fila-total"><span>Subtotal</span><span class="num">${plata(sub)}</span></div>
      <div class="fila-total ${ajuste < 0 ? "desc" : ""}"><span>${texto}</span><span class="num">${ajuste < 0 ? "−" : "+"}${plata(Math.abs(ajuste))}</span></div>`
      : "") +
    `<div class="total"><span>Total estimado</span><strong class="num">${plata(sub + ajuste)}</strong></div>
     <p class="aviso">Sin cargo de envío incluido. Te confirmamos el total final por WhatsApp.</p>`
  );
}
function refrescarPago() {
  const a = $("#info-pago"),
    b = $("#bloque-total");
  if (a) a.innerHTML = htmlInfoPago();
  if (b) b.innerHTML = htmlTotales();
}
let paso = "carrito";

let confirmandoVaciar = false;
function pintarVaciar(hay) {
  $("#zona-vaciar").innerHTML =
    !hay || paso === "mensaje"
      ? ""
      : confirmandoVaciar
        ? `<div class="confirmar-vaciar" role="group" aria-label="Confirmar"><span>¿Vaciar pedido?</span><button type="button" class="si" id="vaciar-si">Sí</button><button type="button" id="vaciar-no">No</button></div>`
        : `<button type="button" class="btn-vaciar" id="btn-vaciar" aria-label="Vaciar pedido"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg> Vaciar</button>`;
}
function pintarPanel() {
  const lista = items(),
    cuerpo = $("#panel-cuerpo"),
    pie = $("#panel-pie");
  pintarVaciar(lista.length > 0);
  if (!lista.length) {
    paso = "carrito";
    cuerpo.innerHTML = `<div class="vacio-carrito"><strong>Tu pedido está vacío</strong>Agregá productos desde el catálogo y van a aparecer acá.</div>`;
    pie.innerHTML = `<button class="btn-sec" type="button" data-cerrar>Ver productos</button>`;
    return;
  }
  if (paso === "mensaje") return pintarMensaje();
  cuerpo.innerHTML =
    lista
      .map(
        (i) => `<div class="linea" data-k="${esc(i.k)}">
      <div><div class="nombre">${esc(i.p.n)}</div><div class="detalle num">${i.v.e === "unidad" ? "Unidad" : esc(i.v.e)} · ${plata(i.v.p)} c/u</div></div>
      <div class="subtotal num">${plata(i.v.p * i.cant)}</div>
      <button class="quitar" type="button" data-quitar aria-label="Quitar ${esc(i.p.n)} del pedido">Quitar</button>
      <div class="contador"><button type="button" data-menos aria-label="Quitar uno">−</button><span class="num">${i.cant}</span><button type="button" data-mas aria-label="Agregar uno">+</button></div>
    </div>`,
      )
      .join("") +
    `<div class="fila-total sub-items"><span>Subtotal</span><strong class="num">${plata(totalCarrito())}</strong></div>
     <form class="form" id="form-pedido" novalidate>
       <div class="dos-campos">
         <div class="campo"><label for="f-nombre">Nombre</label><input id="f-nombre" autocomplete="given-name" value="${esc(datos.nombre)}" maxlength="60"></div>
         <div class="campo"><label for="f-apellido">Apellido</label><input id="f-apellido" autocomplete="family-name" value="${esc(datos.apellido)}" maxlength="60"></div>
       </div>
       <fieldset class="campo"><legend>Entrega</legend><div class="opciones">
         <label class="opcion"><input type="radio" name="entrega" value="retiro" ${datos.entrega === "retiro" ? "checked" : ""}><span>Retiro en el local</span></label>
         <label class="opcion"><input type="radio" name="entrega" value="envio" ${datos.entrega === "envio" ? "checked" : ""}><span>Envío a domicilio</span></label>
       </div></fieldset>
              <div class="info-pago info-retiro" id="campo-retiro" ${datos.entrega === "retiro" ? "" : "hidden"}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-6.1-7-11.5A7 7 0 0 1 19 9.5C19 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg><span>Retirás en <strong>${DIRECCION}</strong>. Coordinamos el horario por WhatsApp.</span></div>
       <div class="campo" id="campo-dir" ${datos.entrega === "envio" ? "" : "hidden"}><label for="f-dir">Dirección</label><input id="f-dir" autocomplete="street-address" value="${esc(datos.direccion)}" maxlength="200"></div>
       <fieldset class="campo"><legend>¿Cómo vas a pagar?</legend><div class="opciones tres">
         ${Object.entries(PAGOS)
           .map(
             ([v, t]) =>
               `<label class="opcion"><input type="radio" name="pago" value="${v}" ${datos.pago === v ? "checked" : ""}><span>${t}</span></label>`,
           )
           .join("")}
       </div></fieldset>
       <div id="info-pago" aria-live="polite">${htmlInfoPago()}</div>
       <div class="campo"><label for="f-notas">Aclaraciones (opcional)</label><textarea id="f-notas" maxlength="500">${esc(datos.notas)}</textarea></div>
       <p class="error" id="f-error" hidden></p>
     </form>
     <div id="bloque-total" class="bloque-total">${htmlTotales()}</div>`;
  pie.innerHTML = `<button class="btn-grande" type="button" id="btn-encargar">${iconoWa} Encargar por WhatsApp</button>`;
}

const iconoWa = `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.3-.4.7-1.4.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.8 11.8 0 0 0 4.5 4c1.7.7 2.3.8 3.2.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.3-.2-.5-.3z"/></svg>`;

function armarMensaje() {
  const lineas = items().map(
    (i) =>
      `• ${i.cant} x ${i.p.n} (${i.v.e === "unidad" ? "unidad" : i.v.e}) — ${plata(i.v.p * i.cant)}`,
  );
  const sub = totalCarrito(),
    { ajuste, texto } = calcularPago(sub, datos.pago);
  const totales = ajuste
    ? [
        `Subtotal: ${plata(sub)}`,
        `${texto}: ${ajuste < 0 ? "−" : "+"}${plata(Math.abs(ajuste))}`,
      ]
    : [];
  return [
    `¡Hola La Ribera! Quiero hacer este pedido:`,
    ``,
    ...lineas,
    ``,
    ...totales,
    `Total estimado: ${plata(sub + ajuste)}`,
    ``,
    `Nombre: ${datos.nombre} ${datos.apellido}`,
    datos.entrega === "envio"
      ? `Envío a: ${datos.direccion}`
      : `Retiro en el local`,
    `Pago: ${PAGOS[datos.pago]}` +
      (datos.pago === "transferencia" ? ` (alias ${ALIAS})` : ""),
    ...(datos.notas ? [`Aclaraciones: ${datos.notas}`] : []),
  ].join("\n");
}

function pintarMensaje() {
  const msj = armarMensaje();
  $("#panel-cuerpo").innerHTML =
    `<p class="aviso" style="margin-top:12px">Este es el mensaje que se va a enviar al WhatsApp de La Ribera:</p>
    <pre class="mensaje" id="texto-mensaje">${esc(msj)}</pre>
    ${WHATSAPP ? "" : `<div class="nota-preview">Vista previa: falta cargar el número de WhatsApp del local. En la versión final, este botón abre WhatsApp con el mensaje listo y el pedido queda registrado en el panel del dueño.</div>`}`;
  const href = WHATSAPP
    ? `https://wa.me/${WHATSAPP}?text=${encodeURIComponent(msj)}`
    : null;
  $("#panel-pie").innerHTML = `<div style="display:grid;gap:10px">
      ${href ? `<a class="btn-grande" href="${href}" target="_blank" rel="noopener">${iconoWa} Abrir WhatsApp</a>` : `<button class="btn-grande" type="button" disabled>${iconoWa} Abrir WhatsApp</button>`}
      <button class="btn-sec" type="button" id="btn-copiar">Copiar mensaje</button>
      <button class="btn-sec" type="button" id="btn-volver">Volver al pedido</button></div>`;
}

$("#panel").addEventListener("click", (e) => {
  if (e.target.closest("#btn-vaciar")) {
    confirmandoVaciar = true;
    pintarVaciar(true);
    $("#vaciar-no").focus();
    return;
  }
  if (e.target.closest("#vaciar-no")) {
    confirmandoVaciar = false;
    pintarVaciar(true);
    $("#btn-vaciar").focus();
    return;
  }
  if (e.target.closest("#vaciar-si")) {
    const ids = items().map((i) => i.p.id);
    carrito = {};
    confirmandoVaciar = false;
    guardar();
    pintarPanel();
    pintarCuenta();
    new Set(ids).forEach(repintarTarjeta);
    return;
  }
  const linea = e.target.closest(".linea");
  if (linea && e.target.closest("[data-quitar]")) {
    const k = linea.dataset.k;
    leerForm();
    delete carrito[k];
    guardar();
    pintarPanel();
    pintarCuenta();
    repintarTarjeta(k.split("|")[0]);
    return;
  }
  if (
    linea &&
    (e.target.closest("[data-mas]") || e.target.closest("[data-menos]"))
  ) {
    const k = linea.dataset.k;
    leerForm();
    carrito[k] = (carrito[k] || 0) + (e.target.closest("[data-mas]") ? 1 : -1);
    carrito[k] = Math.min(99, carrito[k]);
    if (carrito[k] <= 0) delete carrito[k];
    guardar();
    pintarPanel();
    pintarCuenta();
    repintarTarjeta(k.split("|")[0]);
    return;
  }
  if (e.target.closest("#btn-encargar")) {
    leerForm();
    const faltas = [
      [!datos.nombre, "Escribí tu nombre.", "#f-nombre"],
      [!datos.apellido, "Escribí tu apellido.", "#f-apellido"],
      [
        datos.entrega === "envio" && !datos.direccion,
        "Escribí la dirección de envío.",
        "#f-dir",
      ],
      [!datos.pago, "Elegí cómo vas a pagar.", 'input[name="pago"]'],
    ].find((f) => f[0]);
    if (faltas) {
      const p = $("#f-error");
      p.textContent = faltas[1];
      p.hidden = false;
      $(faltas[2]).focus();
      return;
    }
    paso = "mensaje";
    pintarPanel();
    return;
  }
  if (e.target.closest("#btn-alias")) {
    const b = e.target.closest("#btn-alias");
    const listo = (t) => {
      b.textContent = t;
      setTimeout(() => (b.textContent = "Copiar alias"), 2000);
    };
    try {
      navigator.clipboard.writeText(ALIAS).then(
        () => listo("Alias copiado"),
        () => listo("Copialo a mano"),
      );
    } catch (er) {
      listo("Copialo a mano");
    }
    return;
  }
  if (e.target.closest("#btn-volver")) {
    paso = "carrito";
    pintarPanel();
    return;
  }
  if (e.target.closest("#btn-copiar")) {
    const b = e.target.closest("#btn-copiar"),
      txt = armarMensaje();
    const ok = () => {
      b.textContent = "Mensaje copiado";
      setTimeout(() => (b.textContent = "Copiar mensaje"), 2000);
    };
    const fallback = () => {
      const r = document.createRange();
      r.selectNodeContents($("#texto-mensaje"));
      const s = getSelection();
      s.removeAllRanges();
      s.addRange(r);
      b.textContent = "Seleccionado: copialo con Ctrl+C";
    };
    try {
      navigator.clipboard.writeText(txt).then(ok, fallback);
    } catch (er) {
      fallback();
    }
  }
});
$("#panel").addEventListener("change", (e) => {
  if (e.target.name === "entrega") {
    leerForm();
    $("#campo-dir").hidden = datos.entrega !== "envio";
    $("#campo-retiro").hidden = datos.entrega !== "retiro";
  }
  {
    leerForm();
    $("#campo-dir").hidden = datos.entrega !== "envio";
  }
  if (e.target.name === "pago") {
    leerForm();
    refrescarPago();
  }
});
function leerForm() {
  if (!$("#form-pedido")) return;
  datos.nombre = $("#f-nombre").value.trim();
  datos.apellido = $("#f-apellido").value.trim();
  datos.pago =
    document.querySelector('input[name="pago"]:checked')?.value || "";
  datos.entrega =
    document.querySelector('input[name="entrega"]:checked')?.value || "retiro";
  datos.direccion = $("#f-dir").value.trim();
  datos.notas = $("#f-notas").value.trim();
}

/* ---------- Abrir y cerrar ---------- */
let ultimoFoco = null;
function abrir(el) {
  ultimoFoco = document.activeElement;
  $("#velo").hidden = false;
  el.hidden = false;
  el.querySelector("[data-cerrar]")?.focus();
}
function cerrarTodo() {
  leerForm();
  confirmandoVaciar = false;
  $("#velo").hidden = true;
  $("#panel").hidden = true;
  $("#modal-login").hidden = true;
  ultimoFoco?.focus();
}
$("#abrir-carrito").addEventListener("click", () => {
  pintarPanel();
  abrir($("#panel"));
});
$("#abrir-login").addEventListener("click", () => {
  $("#login-nota").hidden = true;
  abrir($("#modal-login"));
});
$("#velo").addEventListener("click", cerrarTodo);
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-cerrar]")) cerrarTodo();
});
$("#modal-login").addEventListener("click", (e) => {
  if (e.target.id === "modal-login") cerrarTodo();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") cerrarTodo();
});
$("#form-login").addEventListener("submit", (e) => {
  e.preventDefault();
  $("#login-nota").hidden = false;
});

/* ---------- Ilustración del banner (dibujada por código, estilo del logo) ---------- */
function ilustrar() {
  let semilla = 7;
  const r = () => {
    semilla = (semilla * 16807) % 2147483647;
    return (semilla - 1) / 2147483646;
  };
  const W = 1200,
    H = 340,
    out = [];
  const g = (x, y, a, sc, cuerpo) =>
    `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${a.toFixed(1)}) scale(${sc.toFixed(2)})">${cuerpo}</g>`;
  const hoja = (L, A) =>
    `<path d="M0 0Q${L * 0.45} ${-A} ${L} 0Q${L * 0.45} ${A} 0 0Z"/><path d="M${L * 0.08} 0L${L * 0.86} 0"/>` +
    [0.3, 0.52, 0.72]
      .map(
        (t, i) =>
          `<path d="M${L * t} 0l${L * 0.13} ${(i % 2 ? 1 : -1) * A * 0.5}"/>`,
      )
      .join("");
  const ramita = (largo) => {
    let c = `<path d="M0 0Q${largo * 0.5} ${-largo * 0.08} ${largo} 0"/>`;
    for (let t = 0.22; t < 0.95; t += 0.16) {
      const s = 1 - t * 0.45,
        lado = Math.round(t * 10) % 2 ? 1 : -1;
      c += g(
        largo * t,
        -largo * 0.04 * Math.sin(t * Math.PI),
        lado * 42,
        s,
        hoja(46, 16),
      );
    }
    return c + g(largo, 0, -6, 0.8, hoja(46, 16));
  };
  const espiga = (largo) => {
    let c = `<path d="M0 0L${largo} 0"/>`;
    for (let t = 0.5; t <= 1.001; t += 0.1)
      for (const lado of [-1, 1]) {
        c += g(
          largo * t,
          0,
          lado * 28,
          0.55,
          `<path d="M0 0Q8 -7 20 0Q8 7 0 0Z"/><path d="M20 0l14 0"/>`,
        );
      }
    return c;
  };
  const almendra = () =>
    `<path d="M-22 0C-14 -16 10 -14 24 0C10 14 -14 16 -22 0Z"/><path d="M-14 -2C-2 -8 10 -6 18 0"/><path d="M-6 5l2 -1M3 6l2 -1M-10 -6l2 1"/>`;
  const semillaG = () =>
    `<path d="M0 -14C9 -6 9 8 0 14C-9 8 -9 -6 0 -14Z"/><path d="M0 -10L0 10M-4 -4l0 8M4 -4l0 8"/>`;
  const baya = () =>
    `<circle r="8"/><path d="M-3 -6l3 -4l3 4"/><circle cx="-2" cy="1" r="1.2" fill="currentColor"/>`;

  // ondas de agua de fondo
  for (let y = 18; y < H; y += 26) {
    let d = `M0 ${y}`;
    for (let x = 0; x <= W; x += 60) d += `q15 ${r() * 3 + 1.5} 30 0t30 0`;
    out.push(
      `<path d="${d}" stroke="var(--onda-agua)" stroke-width="1" opacity=".35" fill="none"/>`,
    );
  }
  // elementos en los costados, centro libre para el título
  const piezas = [];
  for (const lado of [0, 1]) {
    for (let i = 0; i < 12; i++) {
      // nacen cerca del centro-lateral y crecen hacia el borde: el título queda libre
      const x = lado ? W - 70 - r() * 250 : 70 + r() * 250,
        y = 20 + r() * (H - 40);
      const tipo = r();
      const ang = (lado ? 0 : 180) + (r() - 0.5) * 100;
      if (tipo < 0.34)
        piezas.push(g(x, y, ang, 1.1 + r() * 0.5, ramita(110 + r() * 50)));
      else if (tipo < 0.52)
        piezas.push(g(x, y, ang - 60, 1.2 + r() * 0.4, espiga(110)));
      else if (tipo < 0.72)
        piezas.push(g(x, y, r() * 360, 1.3 + r() * 0.5, almendra()));
      else if (tipo < 0.88)
        piezas.push(g(x, y, r() * 360, 1.2 + r() * 0.4, semillaG()));
      else
        piezas.push(
          g(
            x,
            y,
            r() * 40,
            1.4,
            baya() + g(14, 6, 0, 0.8, baya()) + g(5, -12, 0, 0.7, baya()),
          ),
        );
    }
  }
  for (let i = 0; i < 6; i++) {
    // detalles chicos arriba y abajo del centro
    const x = 360 + r() * 480,
      y = r() < 0.5 ? 10 + r() * 20 : H - 10 - r() * 20;
    piezas.push(g(x, y, r() * 360, 0.6, r() < 0.5 ? almendra() : semillaG()));
  }
  out.push(
    `<g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${piezas.join("")}</g>`,
  );
  $("#ilustracion").innerHTML = out.join("");
}

function pintarBanner() {
  const n = CATALOGO.filter((p) => p.c === categoria).length;
  $("#banner-sub").hidden = !categoria;
  $("#banner-sub").textContent = categoria || "";
  $("#banner-bajada").textContent = categoria
    ? n === 1
      ? "1 producto"
      : `${n} productos`
    : "Frutos secos, semillas, harinas y yuyos. Armá tu pedido y lo coordinamos por WhatsApp.";
}

/* ---------- Flechas de categorías ---------- */
function actualizarFlechas() {
  const el = $("#estantes"),
    marco = $("#estantes-marco");
  const izq = el.scrollLeft > 4,
    der = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;
  $("#flecha-izq").hidden = !izq;
  $("#flecha-der").hidden = !der;
  marco.classList.toggle("hay-izq", izq);
  marco.classList.toggle("hay-der", der);
}
$("#flecha-izq").addEventListener("click", () =>
  $("#estantes").scrollBy({ left: -$("#estantes").clientWidth * 0.7 }),
);
$("#flecha-der").addEventListener("click", () =>
  $("#estantes").scrollBy({ left: $("#estantes").clientWidth * 0.7 }),
);
$("#estantes").addEventListener("scroll", actualizarFlechas, { passive: true });
addEventListener("resize", actualizarFlechas);

/* ---------- Arranque ---------- */
async function iniciar() {
  ilustrar();
  pintarBanner();
  try {
    const r = await fetch("data/catalogo.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    CATALOGO = await r.json();
  } catch (e) {
    $("#grilla").innerHTML =
      `<div class="vacio"><strong>No pudimos cargar los productos</strong>Recargá la página en unos segundos.</div>`;
    return;
  }
  CATALOGO.forEach((p) => {
    p.id = p.s;
    p.k = norm(p.n + " " + p.c);
    p.sel = 0;
  });
  CATALOGO.sort(
    (a, b) =>
      ORDEN_CAT.indexOf(a.c) - ORDEN_CAT.indexOf(b.c) ||
      a.n.localeCompare(b.n, "es"),
  );
  porId = new Map(CATALOGO.map((p) => [p.id, p]));
  // descarta del pedido guardado productos que ya no existen
  for (const k of Object.keys(carrito))
    if (!porId.has(k.split("|")[0])) delete carrito[k];
  guardar();
  pintarEstantes();
  pintarGrilla();
  pintarCuenta();
  actualizarFlechas();
}
iniciar();
