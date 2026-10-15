/* Panel del dueño. Toda la seguridad está en la base (RLS + funciones que chequean es_admin):
   este archivo solo muestra lo que la base le deja ver al usuario logueado. */
const { SUPABASE_URL, SUPABASE_ANON_KEY } = window.RIBERA;
const sb = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const plata = n => { const v = Math.round(Number(n) || 0); return (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString("es-AR"); };
const entero = n => Math.round(Number(n) || 0).toLocaleString("es-AR");
const isoLocal = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fechaCorta = iso => { const [, m, d] = iso.split("-"); return `${+d}/${+m}`; };

const MEDIOS = { efectivo: "Efectivo", transferencia: "Transferencia", debito: "Débito", credito: "Crédito", mercadopago: "Mercado Pago" };
const normalizar = t => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

/* ---------- Ingreso ---------- */
async function arrancar() {
  const { data: { session } } = await sb.auth.getSession();
  $("#cargando").hidden = true;
  if (!session) return mostrarLogin();
  // ¿es dueño? La tabla admins solo deja ver la propia fila
  const { data } = await sb.from("admins").select("user_id").eq("user_id", session.user.id).maybeSingle();
  if (!data) { await sb.auth.signOut(); return mostrarLogin("Este usuario no tiene acceso al panel."); }
  $("#vista-login").hidden = true; $("#vista-panel").hidden = false;
  cargarCatalogo(); cargarPedidos(); cargarStock();
}
function mostrarLogin(error) {
  $("#vista-panel").hidden = true; $("#vista-login").hidden = false;
  const p = $("#l-error"); p.hidden = !error; p.textContent = error || "";
  $("#l-email").focus();
}
$("#form-login").addEventListener("submit", async e => {
  e.preventDefault();
  const email = $("#l-email").value.trim(), password = $("#l-clave").value;
  if (!email || !password) return mostrarLogin("Completá email y contraseña.");
  const b = $("#l-boton"); b.disabled = true; b.textContent = "Entrando…";
  const { error } = await sb.auth.signInWithPassword({ email, password });
  b.disabled = false; b.textContent = "Entrar";
  if (error) return mostrarLogin(/invalid/i.test(error.message) ? "Email o contraseña incorrectos." : "No se pudo entrar. Probá de nuevo en un rato.");
  $("#l-clave").value = "";
  arrancar();
});
$("#salir").addEventListener("click", async () => { await sb.auth.signOut(); location.reload(); });

/* ---------- Pestañas ---------- */
const TABS = ["vender", "ventas", "pedidos", "stock", "productos", "resumen"];
document.querySelector(".pestanias").addEventListener("click", e => {
  const b = e.target.closest("[data-tab]"); if (b) irA(b.dataset.tab);
});
function irA(tab) {
  document.querySelectorAll("[data-tab]").forEach(x => x.setAttribute("aria-selected", x.dataset.tab === tab));
  TABS.forEach(t => $("#tab-" + t).hidden = t !== tab);
  if (tab === "ventas") cargarDia();
  if (tab === "resumen") cargarResumen();
  if (tab === "pedidos") cargarPedidos();
  if (tab === "stock") cargarStock();
  if (tab === "productos") pintarFotos();
  scrollTo(0, 0);
}

/* ---------- Dashboard ---------- */
let periodo = "mes", agrupar = null, ordenTop = "ventas", ultimo = null;
const graficos = {};
const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const fechaLarga = iso => { const [a, m, d] = iso.split("-"); return `${+d} ${MESES[+m - 1]}${a !== String(new Date().getFullYear()) ? " " + a : ""}`; };
const desdeIso = iso => new Date(iso + "T12:00");

function rango(p) {
  const hoy = new Date(), d = new Date(hoy);
  if (p === "7" || p === "30") { d.setDate(d.getDate() - (+p - 1)); return [d, hoy]; }
  if (p === "mes") return [new Date(hoy.getFullYear(), hoy.getMonth(), 1), hoy];
  if (p === "mes-ant") return [new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1), new Date(hoy.getFullYear(), hoy.getMonth(), 0)];
  if (p === "anio") return [new Date(hoy.getFullYear(), 0, 1), hoy];
  const a = $("#f-desde").value, b = $("#f-hasta").value;
  return a && b && a <= b ? [desdeIso(a), desdeIso(b)] : [new Date(hoy.getFullYear(), hoy.getMonth(), 1), hoy];
}
// contra qué se compara: "este mes" con los mismos días del mes pasado, "este año" con el año pasado
function rangoAnterior(p, desde, hasta) {
  const mismoDia = (a, m, d) => new Date(a, m, Math.min(d, new Date(a, m + 1, 0).getDate()));
  if (p === "mes") return [new Date(desde.getFullYear(), desde.getMonth() - 1, 1), mismoDia(hasta.getFullYear(), hasta.getMonth() - 1, hasta.getDate())];
  if (p === "mes-ant") return [new Date(desde.getFullYear(), desde.getMonth() - 1, 1), new Date(desde.getFullYear(), desde.getMonth(), 0)];
  if (p === "anio") return [new Date(desde.getFullYear() - 1, 0, 1), mismoDia(hasta.getFullYear() - 1, hasta.getMonth(), hasta.getDate())];
  const dias = Math.round((desdeIso(isoLocal(hasta)) - desdeIso(isoLocal(desde))) / 864e5) + 1;
  const a = new Date(desde); a.setDate(a.getDate() - dias); const b = new Date(desde); b.setDate(b.getDate() - 1);
  return [a, b];
}
$("#f-periodo").addEventListener("click", e => {
  const b = e.target.closest("[data-p]"); if (!b) return;
  periodo = b.dataset.p; agrupar = null;
  b.parentElement.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b));
  $("#f-rango").hidden = periodo !== "rango";
  if (periodo === "rango" && !$("#f-desde").value) { const [a, z] = rango("mes"); $("#f-desde").value = isoLocal(a); $("#f-hasta").value = isoLocal(z); }
  cargarResumen();
});
["#f-desde", "#f-hasta", "#f-categoria"].forEach(s => $(s).addEventListener("change", cargarResumen));
$("#g-agrupar").addEventListener("click", e => { const b = e.target.closest("[data-a]"); if (b) { agrupar = b.dataset.a; pintarTiempo(); } });
$("#g-top").addEventListener("click", e => {
  const b = e.target.closest("[data-t]"); if (!b) return;
  ordenTop = b.dataset.t; b.parentElement.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); pintarTop();
});
document.addEventListener("click", e => { if (e.target.id === "ver-pend") { irA("pedidos"); filtroEstado("pendiente"); } });

function llenarCategorias() {
  const sel = $("#f-categoria"), actual = sel.value;
  const cats = [...new Set(CATALOGO.map(p => p.cat).filter(Boolean))].sort((a, b) => a.localeCompare(b, "es"));
  sel.innerHTML = `<option value="">Todas las categorías</option>` + cats.map(c => `<option${c === actual ? " selected" : ""}>${esc(c)}</option>`).join("");
}

async function cargarResumen() {
  const [desde, hasta] = rango(periodo), cat = $("#f-categoria").value || null;
  const [dAnt, hAnt] = rangoAnterior(periodo, desde, hasta);
  const { data, error } = await sb.rpc("panel_dashboard", { p_desde: isoLocal(desde), p_hasta: isoLocal(hasta), p_categoria: cat,
    p_ant_desde: isoLocal(dAnt), p_ant_hasta: isoLocal(hAnt) });
  if (error) { $("#kpis").innerHTML = `<p class="vacio">No se pudieron cargar los datos (${esc(error.message)}).</p>`; return; }
  ultimo = { ...data, desde, hasta, cat };
  $("#f-texto").textContent = `${fechaLarga(isoLocal(desde))} al ${fechaLarga(isoLocal(hasta))} · comparado con ${fechaLarga(isoLocal(dAnt))} al ${fechaLarga(isoLocal(hAnt))}` + (cat ? ` · solo ${cat}` : "");
  const av = $("#aviso-pend"); av.hidden = !data.pendientes_web;
  av.innerHTML = data.pendientes_web ? `Hay <b>${data.pendientes_web}</b> ${data.pendientes_web === 1 ? "pedido web pendiente" : "pedidos web pendientes"} sin confirmar: no suman hasta que los confirmen. <button type="button" id="ver-pend">Ver pedidos</button>` : "";
  pintarKpis(); pintarTiempo(); pintarSemana(); pintarTop(); pintarBarras(); cargarGastos();
}

// en plata (para la ganancia neta, que puede ser negativa) o en puntos (margen)
function diferencia(act, ant, txt) {
  const d = act - ant; if (!ant && !act) return "";
  if (Math.abs(d) < 0.05) return `<small class="var">= igual que el período anterior</small>`;
  return `<small class="var ${d > 0 ? "sube" : "baja"}">${d > 0 ? "▲" : "▼"} ${txt(Math.abs(d))} ${d > 0 ? "más" : "menos"} que antes</small>`;
}
function variacion(act, ant, alReves = false) {
  if (!ant) return act ? `<small class="var">sin datos del período anterior</small>` : "";
  const pct = Math.round((act - ant) / Math.abs(ant) * 100);
  if (pct === 0) return `<small class="var">= igual que el período anterior</small>`;
  const bueno = alReves ? pct < 0 : pct > 0;
  return `<small class="var ${bueno ? "sube" : "baja"}">${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}% vs período anterior</small>`;
}
function pintarKpis() {
  const a = ultimo.actual, b = ultimo.anterior, conCat = !!ultimo.cat;
  const tiles = [
    ["Ventas", plata(a.ventas), variacion(a.ventas, b.ventas)],
    ["Ganancia bruta", plata(a.ganancia), variacion(a.ganancia, b.ganancia)],
    ...(conCat ? [] : [
      ["Gastos", plata(a.gastos), variacion(a.gastos, b.gastos, true)],
      ["Ganancia neta", plata(a.neta), diferencia(a.neta, b.neta, plata), a.neta < 0 ? "negativo" : "destacado"],
    ]),
    ["Margen", a.margen.toLocaleString("es-AR") + "%", diferencia(+a.margen, +b.margen, v => v.toLocaleString("es-AR", { maximumFractionDigits: 1 }) + " pts")],
    ["Ticket promedio", plata(a.ticket), variacion(a.ticket, b.ticket)],
    ["Cantidad de ventas", entero(a.ventas_n), variacion(a.ventas_n, b.ventas_n)],
  ];
  $("#kpis").innerHTML = tiles.map(([t, v, d, c]) => `<div class="tile ${c || ""}"><span>${t}</span><strong class="num">${v}</strong>${d}</div>`).join("")
    + (conCat ? `<p class="nota kpi-nota">Con una categoría elegida no se muestran gastos ni ganancia neta: los gastos son de todo el negocio.</p>` : "");
}

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function opcionesBase(formato) {
  const tinta = css("--tinta-suave"), linea = css("--linea");
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: false },
      tooltip: { backgroundColor: css("--tinta"), titleColor: css("--papel"), bodyColor: css("--papel"), padding: 10, displayColors: false, callbacks: { label: formato } } },
    scales: {
      x: { grid: { display: false }, ticks: { color: tinta, maxRotation: 0, autoSkipPadding: 12 }, border: { color: linea } },
      y: { grid: { color: linea }, border: { display: false }, ticks: { color: tinta, maxTicksLimit: 5, callback: v => v >= 1e6 ? "$" + (v / 1e6).toLocaleString("es-AR") + " M" : v >= 1e3 ? "$" + Math.round(v / 1e3) + " mil" : "$" + v } },
    },
  };
}
function dibujar(id, config) {
  graficos[id]?.destroy();
  if (typeof Chart === "undefined") { $("#" + id).parentElement.innerHTML = `<p class="vacio">No se pudo cargar el gráfico.</p>`; return; }
  graficos[id] = new Chart($("#" + id), config);
}

// sin ventas en el período: en vez de un gráfico vacío, un mensaje
function sinDatos(id, hay) {
  const lienzo = $("#" + id).parentElement;
  let msg = lienzo.querySelector(".vacio");
  if (!msg) { msg = document.createElement("p"); msg.className = "vacio sin-datos"; msg.textContent = "Todavía no hay ventas en este período."; lienzo.append(msg); }
  msg.hidden = hay; $("#" + id).hidden = !hay;
  if (!hay) { graficos[id]?.destroy(); delete graficos[id]; }
  return hay;
}
function pintarTiempo() {
  const { por_dia, desde, hasta, dias } = ultimo;
  const modo = agrupar || (dias > 180 ? "mes" : dias > 62 ? "semana" : "dia");
  document.querySelectorAll("#g-agrupar button").forEach(b => b.setAttribute("aria-pressed", b.dataset.a === modo));
  const mapa = new Map(por_dia.map(d => [d.dia, d])), grupos = new Map();
  for (const d = new Date(desde); isoLocal(d) <= isoLocal(hasta); d.setDate(d.getDate() + 1)) {
    const iso = isoLocal(d), v = mapa.get(iso);
    let k, et;
    if (modo === "dia") { k = iso; et = fechaCorta(iso); }
    else if (modo === "mes") { k = iso.slice(0, 7); et = MESES[d.getMonth()] + (d.getFullYear() !== new Date().getFullYear() ? " " + d.getFullYear() : ""); }
    else { const l = new Date(d); l.setDate(l.getDate() - ((l.getDay() + 6) % 7)); k = isoLocal(l); et = "Sem. " + fechaCorta(k); }
    const g = grupos.get(k) || { et, ventas: 0, n: 0 };
    g.ventas += v ? +v.ventas : 0; g.n += v ? v.n : 0; grupos.set(k, g);
  }
  const filas = [...grupos.values()], color = css("--barra");
  if (!sinDatos("c-tiempo", filas.some(f => f.ventas))) return;
  const op = opcionesBase(ctx => ` ${plata(ctx.raw)} · ${filas[ctx.dataIndex].n} ${filas[ctx.dataIndex].n === 1 ? "venta" : "ventas"}`);
  dibujar("c-tiempo", { type: "line", data: { labels: filas.map(f => f.et), datasets: [{ data: filas.map(f => f.ventas), borderColor: color, borderWidth: 2,
    backgroundColor: color + "33", fill: true, tension: .3, pointRadius: filas.length > 40 ? 0 : 3, pointHoverRadius: 5, pointBackgroundColor: color }] }, options: op });
}

function pintarSemana() {
  const { por_dia, desde, hasta } = ultimo, mapa = new Map(por_dia.map(d => [d.dia, +d.ventas]));
  const tot = Array(7).fill(0), veces = Array(7).fill(0);
  for (const d = new Date(desde); isoLocal(d) <= isoLocal(hasta); d.setDate(d.getDate() + 1)) {
    const i = (d.getDay() + 6) % 7; tot[i] += mapa.get(isoLocal(d)) || 0; veces[i]++;
  }
  const prom = tot.map((t, i) => veces[i] ? Math.round(t / veces[i]) : 0), max = Math.max(...prom);
  if (!sinDatos("c-semana", max > 0)) return;
  const color = css("--barra"), suave = color + "66";
  dibujar("c-semana", { type: "bar", data: { labels: DIAS, datasets: [{ data: prom, backgroundColor: prom.map(v => v === max && max ? color : suave),
    borderRadius: 4, maxBarThickness: 36 }] }, options: { ...opcionesBase(ctx => ` ${plata(ctx.raw)} por día en promedio`), interaction: { mode: "nearest", intersect: true } } });
}

function barrasH(filas, etiqueta, valor, detalle) {
  if (!filas.length) return `<p class="vacio">Todavía no hay ventas en este período.</p>`;
  const max = Math.max(...filas.map(valor)) || 1;
  return filas.map(f => `<div class="bh" title="${esc(etiqueta(f))}: ${plata(valor(f))}">
      <div class="bh-txt"><span>${esc(etiqueta(f))}</span><b class="num">${plata(valor(f))}</b></div>
      <div class="bh-barra"><i style="width:${Math.max(1, valor(f) / max * 100)}%"></i></div>
      ${detalle ? `<small class="num">${detalle(f)}</small>` : ""}</div>`).join("");
}
const cantidadTxt = f => [f.unidades ? entero(f.unidades) + " u" : "", f.kilos ? (+f.kilos).toLocaleString("es-AR") + " kg" : ""].filter(Boolean).join(" · ");
function pintarTop() {
  const lista = ordenTop === "ventas" ? ultimo.top_ventas : ultimo.top_ganancia;
  $("#b-top").innerHTML = barrasH(lista, f => f.producto, f => +f[ordenTop],
    f => cantidadTxt(f) + (ordenTop === "ventas" ? ` · ganancia ${plata(f.ganancia)}` : ` · vendido ${plata(f.ventas)}`));
}
function pintarBarras() {
  const u = ultimo, total = +u.actual.ventas || 1, pct = v => Math.round(v / total * 100) + "%";
  $("#b-cat").innerHTML = barrasH(u.por_categoria, f => f.categoria, f => +f.ventas, f => `${pct(f.ventas)} · ganancia ${plata(f.ganancia)}`);
  $("#b-canal").innerHTML = barrasH(u.por_canal, f => f.canal, f => +f.ventas, f => `${pct(f.ventas)} · ${entero(f.n)} ${f.n === 1 ? "venta" : "ventas"}`);
  $("#b-pago").innerHTML = barrasH(u.por_pago, f => f.medio, f => +f.ventas, f => `${pct(f.ventas)} · ${entero(f.n)} ${f.n === 1 ? "venta" : "ventas"}`);
  $("#sin-ventas").textContent = u.sin_ventas ? `${entero(u.sin_ventas)} productos de la página no vendieron nada en este período.` : "";
  $("#t-menos").innerHTML = u.menos_vendidos.length ? `<table><thead><tr><th>Producto</th><th class="n">Vendido</th></tr></thead><tbody>${u.menos_vendidos.map(f => `<tr><td class="prod">${esc(f.producto)}</td><td class="n num">${plata(f.ventas)}</td></tr>`).join("")}</tbody></table>` : "";
}

/* ---------- Gastos ---------- */
$("#gs-fecha").value = isoLocal(new Date());
async function cargarGastos() {
  const [desde, hasta] = rango(periodo);
  const { data, error } = await sb.from("gastos").select("id, fecha, categoria, descripcion, monto")
    .gte("fecha", isoLocal(desde)).lte("fecha", isoLocal(hasta)).order("fecha", { ascending: false });
  if (error) { $("#g-lista").innerHTML = `<p class="vacio">No se pudieron cargar los gastos (${esc(error.message)}).</p>`; return; }
  $("#g-total").textContent = data.length ? plata(data.reduce((s, g) => s + +g.monto, 0)) : "";
  $("#g-lista").innerHTML = data.length ? `<table><tbody>${data.map(g => `<tr><td class="num">${fechaCorta(g.fecha)}</td><td class="prod">${esc(g.categoria)}${g.descripcion ? ` <small>· ${esc(g.descripcion)}</small>` : ""}</td>
      <td class="n num">${plata(g.monto)}</td><td class="n"><button type="button" class="link-borrar" data-gasto="${g.id}" aria-label="Borrar gasto">Borrar</button></td></tr>`).join("")}</tbody></table>`
    : `<p class="vacio">No hay gastos cargados en este período.</p>`;
}
$("#form-gasto").addEventListener("submit", async e => {
  e.preventDefault();
  const err = $("#gs-error"), monto = +$("#gs-monto").value, fecha = $("#gs-fecha").value;
  if (!fecha || !(monto > 0)) { err.textContent = "Poné la fecha y el monto."; err.hidden = false; return; }
  err.hidden = true;
  const { error } = await sb.from("gastos").insert({ fecha, categoria: $("#gs-cat").value, descripcion: $("#gs-desc").value.trim() || null, monto });
  if (error) { err.textContent = "No se pudo guardar: " + error.message; err.hidden = false; return; }
  $("#gs-monto").value = ""; $("#gs-desc").value = "";
  avisar("Gasto guardado"); cargarResumen();
});
$("#g-lista").addEventListener("click", async e => {
  const b = e.target.closest("[data-gasto]"); if (!b || !confirm("¿Borrar este gasto?")) return;
  const { error } = await sb.from("gastos").delete().eq("id", +b.dataset.gasto);
  if (error) { alert("No se pudo borrar: " + error.message); return; }
  cargarResumen();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => ultimo && (pintarTiempo(), pintarSemana()));

/* ---------- Pedidos ---------- */
let estadoFiltro = "pendiente";
const ESTADOS = { pendiente: "Pendiente", confirmado: "Confirmado", entregado: "Entregado", cancelado: "Cancelado" };
$("#filtro-estado").addEventListener("click", e => {
  const b = e.target.closest("[data-e]"); if (b) filtroEstado(b.dataset.e);
});
function filtroEstado(e) {
  estadoFiltro = e;
  document.querySelectorAll("#filtro-estado button").forEach(x => x.setAttribute("aria-pressed", x.dataset.e === e));
  cargarPedidos();
}

async function cargarPedidos() {
  let q = sb.from("pedidos").select("numero, cliente_nombre, cliente_apellido, cliente_tel, entrega, direccion, medio_pago, notas, estado, subtotal, ajuste_pago, total, creado_en, pedido_items(producto_nombre, etiqueta, cantidad, precio_unit)")
    .eq("origen", "web").order("creado_en", { ascending: false }).limit(100);
  if (estadoFiltro) q = q.eq("estado", estadoFiltro);
  const { data, error } = await q;
  const lista = $("#lista-pedidos");
  if (error) { lista.innerHTML = `<p class="vacio">No se pudieron cargar los pedidos (${esc(error.message)}).</p>`; return; }
  lista.innerHTML = data.length ? data.map(tarjetaPedido).join("") : `<p class="vacio">${estadoFiltro ? "No hay pedidos " + ESTADOS[estadoFiltro].toLowerCase() + "s." : "Todavía no entró ningún pedido por la web."}</p>`;
  const { count } = await sb.from("pedidos").select("id", { count: "exact", head: true }).eq("estado", "pendiente").eq("origen", "web");
  $("#n-pendientes").hidden = !count; $("#n-pendientes").textContent = count || "";
}

function tarjetaPedido(p) {
  const f = new Date(p.creado_en).toLocaleString("es-AR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const tel = (p.cliente_tel || "").replace(/\D/g, "");
  const wa = tel ? `https://wa.me/${tel.startsWith("54") ? tel : "549" + tel.replace(/^0/, "")}` : null;
  const botones = {
    pendiente: [["confirmado", "Confirmar", "prim"], ["cancelado", "Cancelar", "peligro"]],
    confirmado: [["entregado", "Marcar entregado", "prim"], ["pendiente", "Volver a pendiente", ""], ["cancelado", "Cancelar", "peligro"]],
    entregado: [["confirmado", "Deshacer entrega", ""]],
    cancelado: [["pendiente", "Reabrir", ""]],
  }[p.estado] || [];
  return `<article class="pedido">
    <div class="pedido-cab"><strong>#${p.numero}</strong><span class="estado ${p.estado}">${ESTADOS[p.estado]}</span>
      <span>${esc(p.cliente_nombre)} ${esc(p.cliente_apellido)}</span><span class="total num">${plata(p.total)}</span></div>
    <div class="meta"><span>${esc(f)}</span>
      <span>${p.entrega === "envio" ? "Envío: " + esc(p.direccion) : "Retira en el local"}</span>
      <span>${esc(MEDIOS[p.medio_pago] || p.medio_pago || "")}${+p.ajuste_pago ? ` (${+p.ajuste_pago < 0 ? "−" : "+"}${plata(Math.abs(p.ajuste_pago))})` : ""}</span>
      ${wa ? `<a href="${wa}" target="_blank" rel="noopener">WhatsApp ${esc(p.cliente_tel)}</a>` : ""}</div>
    <ul>${p.pedido_items.map(i => `<li class="num">${i.cantidad} × ${esc(i.producto_nombre)} (${esc(i.etiqueta)}) — ${plata(i.precio_unit * i.cantidad)}</li>`).join("")}</ul>
    ${p.notas ? `<div class="meta">Aclaraciones: ${esc(p.notas)}</div>` : ""}
    <div class="acciones">${botones.map(([e, t, c]) => `<button type="button" class="${c}" data-num="${p.numero}" data-estado="${e}">${t}</button>`).join("")}</div>
  </article>`;
}

$("#lista-pedidos").addEventListener("click", async e => {
  const b = e.target.closest("[data-estado]"); if (!b) return;
  if (b.dataset.estado === "cancelado" && !confirm(`¿Cancelar el pedido #${b.dataset.num}?`)) return;
  b.disabled = true;
  const { error } = await sb.rpc("panel_cambiar_estado", { p_numero: +b.dataset.num, p_estado: b.dataset.estado });
  if (error) { alert("No se pudo cambiar: " + error.message); b.disabled = false; return; }
  cargarPedidos();
});

/* ---------- Vender (carga de ventas en el mostrador) ---------- */
let CATALOGO = [];          // productos que se pueden vender en el local
let ticket = [];            // [{ prod, pres, gramos, cantidad, precio }]
let pago = "efectivo";
let enEdicion = null;       // { prod, modo: presentacion id | "peso", gramos, cantidad, precio, precioTocado }

async function cargarCatalogo() {
  const { data, error } = await sb.from("productos")
    .select("id, slug, nombre, activo, precio_kg, foto_url, categorias(nombre), presentaciones(id, etiqueta, gramos, precio, activo)")
    .order("nombre");
  if (error) { $("#v-resultados").innerHTML = `<li class="vacio">No se pudo cargar la lista de productos (${esc(error.message)}).</li>`; return; }
  CATALOGO = data.map(p => ({
    ...p,
    cat: p.categorias?.nombre || "",
    pres: (p.presentaciones || []).filter(x => x.activo && x.precio > 0).sort((a, b) => (a.gramos ?? 1e9) - (b.gramos ?? 1e9)),
    k: normalizar(p.nombre + " " + (p.categorias?.nombre || "")),
  })).filter(p => p.pres.length || p.precio_kg);
  CATALOGO.forEach(p => p.porPeso = !!p.precio_kg || p.pres.some(x => x.gramos));
  pintarPagos(); pintarTicket(); llenarCategorias();
}

// precio por kilo para vender por peso: el de la hoja PRECIO X KG, si no el de la presentación de tamaño más parecido
function precioPorKg(prod, gramos) {
  if (prod.precio_kg) return +prod.precio_kg;
  const conPeso = prod.pres.filter(x => x.gramos);
  if (!conPeso.length) return 0;
  const cerca = conPeso.reduce((a, b) => Math.abs(b.gramos - gramos) < Math.abs(a.gramos - gramos) ? b : a);
  return cerca.precio / cerca.gramos * 1000;
}
const redondear = n => Math.round(n / 10) * 10;   // a $10, como en el mostrador

$("#v-buscar").addEventListener("input", () => buscar());
function buscar() {
  const q = normalizar($("#v-buscar").value.trim()), ul = $("#v-resultados");
  if (q.length < 2) { ul.innerHTML = ""; return; }
  const palabras = q.split(/\s+/);
  const lista = CATALOGO.filter(p => palabras.every(w => p.k.includes(w)))
    .sort((a, b) => (normalizar(a.nombre).startsWith(palabras[0]) ? 0 : 1) - (normalizar(b.nombre).startsWith(palabras[0]) ? 0 : 1))
    .slice(0, 8);
  ul.innerHTML = lista.length ? lista.map(p => `<li><button type="button" data-prod="${p.id}">
      <span class="r-nombre">${esc(p.nombre)}${STOCK.has(p.id) ? ` <span class="r-stock ${claseStock(STOCK.get(p.id))}">${textoStock(STOCK.get(p.id))}</span>` : ""}</span>
      <span class="r-info num">${esc(p.cat)}${p.pres.length ? " · " + p.pres.map(x => esc(x.etiqueta === "unidad" ? "unidad" : x.etiqueta) + " " + plata(x.precio)).join(" · ") : ""}${p.precio_kg ? " · " + plata(p.precio_kg) + " el kg" : ""}</span>
    </button></li>`).join("") : `<li class="vacio">No encontré "${esc($("#v-buscar").value.trim())}". Probá con otra palabra.</li>`;
}
$("#v-resultados").addEventListener("click", e => {
  const b = e.target.closest("[data-prod]"); if (!b) return;
  const prod = CATALOGO.find(p => p.id === +b.dataset.prod);
  enEdicion = { prod, modo: prod.pres[0]?.id ?? "peso", gramos: 100, cantidad: 1, precio: 0, precioTocado: false };
  recalcular(); pintarEditor();
  $("#v-resultados").innerHTML = ""; $("#v-buscar").value = "";
  $("#v-editor").scrollIntoView({ block: "start", behavior: "smooth" });
});

function recalcular() {
  const ed = enEdicion; if (!ed || ed.precioTocado) return;
  if (ed.modo === "peso") ed.precio = redondear(precioPorKg(ed.prod, ed.gramos) * ed.gramos / 1000);
  else ed.precio = ed.prod.pres.find(x => x.id === ed.modo)?.precio || 0;
}
function pintarEditor() {
  const ed = enEdicion, box = $("#v-editor");
  if (!ed) { box.hidden = true; box.innerHTML = ""; return; }
  const opciones = ed.prod.pres.map(x => `<button type="button" data-modo="${x.id}" aria-pressed="${ed.modo === x.id}">${esc(x.etiqueta === "unidad" ? "Unidad" : x.etiqueta)}<small class="num">${plata(x.precio)}</small></button>`).join("")
    + (ed.prod.porPeso ? `<button type="button" data-modo="peso" aria-pressed="${ed.modo === "peso"}">Por peso<small class="num">${plata(precioPorKg(ed.prod, ed.gramos))}/kg</small></button>` : "");
  box.hidden = false;
  box.innerHTML = `<div class="ed-cab"><h2>${esc(ed.prod.nombre)}</h2><button type="button" class="cerrar" id="ed-cerrar" aria-label="Cancelar">×</button></div>
    <div class="opciones-pres" role="group" aria-label="Presentación">${opciones}</div>
    ${ed.modo === "peso" ? `<div class="campo"><label for="ed-gramos">Gramos</label>
        <div class="fila-gramos"><input id="ed-gramos" type="number" inputmode="numeric" min="1" max="50000" value="${ed.gramos}">
        ${[100, 250, 500, 1000].map(g => `<button type="button" class="chip-g" data-g="${g}">${g >= 1000 ? g / 1000 + " kg" : g + " g"}</button>`).join("")}</div></div>` : ""}
    <div class="ed-fila">
      <div class="campo"><label>Cantidad</label><div class="stepper"><button type="button" data-cant="-1" aria-label="Uno menos">−</button><span class="num" id="ed-cant">${ed.cantidad}</span><button type="button" data-cant="1" aria-label="Uno más">+</button></div></div>
      <div class="campo"><label for="ed-precio">Precio c/u</label><input id="ed-precio" type="number" inputmode="numeric" min="0" value="${Math.round(ed.precio)}"></div>
    </div>
    <p class="nota" id="ed-sub">Subtotal: <b class="num">${plata(ed.precio * ed.cantidad)}</b>${ed.precioTocado ? " · precio cambiado a mano" : ""}</p>
    <button type="button" class="btn btn-ancho" id="ed-agregar">Agregar a la venta</button>`;
}
$("#v-editor").addEventListener("click", e => {
  const ed = enEdicion; if (!ed) return;
  const m = e.target.closest("[data-modo]"), g = e.target.closest("[data-g]"), c = e.target.closest("[data-cant]");
  if (e.target.closest("#ed-cerrar")) { enEdicion = null; pintarEditor(); $("#v-buscar").focus(); return; }
  if (m) { ed.modo = m.dataset.modo === "peso" ? "peso" : +m.dataset.modo; ed.precioTocado = false; }
  else if (g) { ed.gramos = +g.dataset.g; ed.precioTocado = false; }
  else if (c) { ed.cantidad = Math.min(99, Math.max(1, ed.cantidad + +c.dataset.cant)); }
  else if (e.target.closest("#ed-agregar")) return agregarAlTicket();
  else return;
  recalcular(); pintarEditor();
});
$("#v-editor").addEventListener("input", e => {
  const ed = enEdicion; if (!ed) return;
  if (e.target.id === "ed-gramos") { ed.gramos = Math.max(0, Math.round(+e.target.value || 0)); ed.precioTocado = false; recalcular(); $("#ed-precio").value = Math.round(ed.precio); }
  if (e.target.id === "ed-precio") { ed.precio = Math.max(0, +e.target.value || 0); ed.precioTocado = true; }
  $("#ed-sub").innerHTML = `Subtotal: <b class="num">${plata(ed.precio * ed.cantidad)}</b>${ed.precioTocado ? " · precio cambiado a mano" : ""}`;
});
function agregarAlTicket() {
  const ed = enEdicion;
  if (ed.modo === "peso" && !(ed.gramos >= 1 && ed.gramos <= 50000)) { alert("Poné los gramos (entre 1 y 50.000)."); return; }
  const pres = ed.modo === "peso" ? null : ed.prod.pres.find(x => x.id === ed.modo);
  ticket.push({ prod: ed.prod, pres, gramos: pres ? null : ed.gramos, cantidad: ed.cantidad, precio: Math.round(ed.precio) });
  enEdicion = null; pintarEditor(); pintarTicket(); $("#v-buscar").focus();
}
const etiquetaItem = it => it.pres ? (it.pres.etiqueta === "unidad" ? "unidad" : it.pres.etiqueta) : (it.gramos >= 1000 ? String(it.gramos / 1000).replace(".", ",") + " kg" : it.gramos + " g");
function pintarTicket() {
  $("#v-items").innerHTML = ticket.length ? ticket.map((it, i) => `<li><div><span class="num">${it.cantidad} × ${esc(it.prod.nombre)}</span><small>${esc(etiquetaItem(it))} · ${plata(it.precio)} c/u</small></div>
      <strong class="num">${plata(it.precio * it.cantidad)}</strong><button type="button" class="quitar" data-quitar="${i}" aria-label="Quitar ${esc(it.prod.nombre)}">Quitar</button></li>`).join("")
    : `<li class="vacio">Buscá un producto arriba para empezar.</li>`;
  $("#v-total").textContent = plata(ticket.reduce((s, it) => s + it.precio * it.cantidad, 0));
  $("#v-guardar").disabled = !ticket.length;
}
$("#v-items").addEventListener("click", e => { const b = e.target.closest("[data-quitar]"); if (b) { ticket.splice(+b.dataset.quitar, 1); pintarTicket(); } });
function pintarPagos() {
  $("#v-pagos").innerHTML = Object.entries(MEDIOS).map(([k, t]) => `<button type="button" data-pago="${k}" aria-pressed="${pago === k}">${t}</button>`).join("");
}
$("#v-pagos").addEventListener("click", e => { const b = e.target.closest("[data-pago]"); if (b) { pago = b.dataset.pago; pintarPagos(); } });

$("#v-guardar").addEventListener("click", async () => {
  const b = $("#v-guardar"), err = $("#v-error"); err.hidden = true;
  const f = $("#v-fecha").value;
  b.disabled = true; b.textContent = "Guardando…";
  const { data, error } = await sb.rpc("panel_cargar_venta", {
    p_fecha: f ? new Date(f).toISOString() : null, p_pago: pago, p_notas: null,
    p_items: ticket.map(it => ({ producto_id: it.prod.id, presentacion_id: it.pres?.id ?? null, gramos: it.gramos, cantidad: it.cantidad, precio_unit: it.precio })),
  });
  b.textContent = "Guardar venta";
  if (error) { err.textContent = "No se pudo guardar: " + error.message; err.hidden = false; b.disabled = false; return; }
  const v = data?.[0];
  ticket = []; $("#v-fecha").value = ""; $("#v-fecha").closest("details").open = false;
  cargarStock(); pintarTicket(); avisar(`Venta guardada${v ? ` · ${plata(v.total)}` : ""}`);
});
let timerToast;
function avisar(txt) { const t = $("#toast"); t.textContent = txt; t.hidden = false; clearTimeout(timerToast); timerToast = setTimeout(() => t.hidden = true, 3000); }

/* ---------- Stock ---------- */
let STOCK = new Map(), filtroStock = "alerta";
const cantStock = (n, u) => u === "kg" ? (+n).toLocaleString("es-AR", { maximumFractionDigits: 2 }) + " kg" : Math.round(+n).toLocaleString("es-AR") + " u";
const claseStock = s => +s.stock <= 0 ? "sin" : s.minimo != null && +s.stock <= +s.minimo ? "poco" : "ok";
const textoStock = s => +s.stock <= 0 ? "sin stock" : "quedan " + cantStock(s.stock, s.unidad);
async function cargarStock() {
  const { data, error } = await sb.rpc("panel_stock");
  if (error) { $("#s-lista").innerHTML = `<p class="vacio">No se pudo cargar el stock (${esc(error.message)}).</p>`; return; }
  STOCK = new Map((data || []).map(s => [s.producto_id, s]));
  const alertas = data.filter(s => claseStock(s) !== "ok").length;
  $("#n-stock").hidden = !alertas; $("#n-stock").textContent = alertas || "";
  pintarStock();
}
function pintarStock() {
  const q = normalizar($("#s-buscar").value.trim()), todos = [...STOCK.values()];
  const orden = { sin: 0, poco: 1, ok: 2 };
  let lista = todos.filter(s => (!q || normalizar(s.producto + " " + s.categoria).includes(q)) && (filtroStock === "todos" || q || claseStock(s) !== "ok"));
  lista.sort((a, b) => orden[claseStock(a)] - orden[claseStock(b)] || a.producto.localeCompare(b.producto, "es"));
  const caja = $("#s-lista");
  if (!todos.length) { caja.innerHTML = `<p class="vacio">Todavía no hay stock cargado. Agreguen la hoja <b>STOCK</b> al Excel del Drive con un conteo inicial (abajo está cómo).</p>`; return; }
  if (!lista.length) { caja.innerHTML = `<p class="vacio">${q ? "No hay productos con ese nombre en el stock." : "Nada para reponer: todo está por encima del mínimo."}</p>`; return; }
  caja.innerHTML = lista.map(s => `<article class="stock-item ${claseStock(s)}">
      <div><strong>${esc(s.producto)}</strong><small>${esc(s.categoria)} · contado el ${fechaCorta(s.fecha_conteo)}: ${cantStock(s.contado, s.unidad)}${+s.entradas ? ` · entró ${cantStock(s.entradas, s.unidad)}` : ""} · vendido ${cantStock(s.vendido, s.unidad)}</small></div>
      <div class="stock-num"><b class="num">${+s.stock <= 0 ? "Sin stock" : cantStock(s.stock, s.unidad)}</b>${s.minimo != null ? `<small>mín. ${cantStock(s.minimo, s.unidad)}</small>` : ""}</div>
    </article>`).join("");
}
$("#s-buscar").addEventListener("input", pintarStock);
$("#s-filtro").addEventListener("click", e => {
  const b = e.target.closest("[data-f]"); if (!b) return;
  filtroStock = b.dataset.f; b.parentElement.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); pintarStock();
});

/* ---------- Fotos de productos ---------- */
let FOTOS_REPO = new Map(), filtroFotos = "sin", fotoPara = null;
fetch("../data/catalogo.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : []).then(c => {
  FOTOS_REPO = new Map(c.filter(p => p.f && !/^https?:/.test(p.f)).map(p => [p.s, "../img/productos/" + p.f]));
  if (!$("#tab-productos").hidden) pintarFotos();
}).catch(() => {});
// archivos de la carpeta del Drive cuyo nombre no coincide con ningún producto
fetch("../data/fotos_drive.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : null).then(d => {
  if (!d?.sin_asociar?.length) return;
  const box = $("#p-drive"); box.hidden = false;
  box.innerHTML = `<b>${d.sin_asociar.length} ${d.sin_asociar.length === 1 ? "foto del Drive no coincide" : "fotos del Drive no coinciden"} con ningún producto.</b> Cambiales el nombre para que sea igual al del Excel:
    <ul>${d.sin_asociar.slice(0, 30).map(n => `<li>${esc(n)}</li>`).join("")}</ul>`;
}).catch(() => {});
const fotoActual = p => p.foto_url || FOTOS_REPO.get(p.slug) || null;
function pintarFotos() {
  const q = normalizar($("#p-buscar").value.trim());
  const activos = CATALOGO.filter(p => p.activo);
  $("#p-n-sin").textContent = activos.filter(p => !fotoActual(p)).length;
  const lista = activos.filter(p => (!q || p.k.includes(q)) &&
    (filtroFotos === "todos" || (filtroFotos === "sin" ? !fotoActual(p) : !!fotoActual(p)))).slice(0, 60);
  $("#p-lista").innerHTML = lista.length ? lista.map(p => {
    const f = fotoActual(p);
    return `<article class="foto-item">
      <div class="foto-marco">${f ? `<img src="${esc(f)}" alt="" loading="lazy">` : `<span>Sin foto</span>`}</div>
      <div class="foto-datos"><strong>${esc(p.nombre)}</strong><small>${esc(p.cat)}${p.foto_url ? " · subida desde el panel" : ""}</small>
        <div class="acciones"><button type="button" class="${f ? "" : "prim"}" data-foto="${p.id}">${f ? "Cambiar foto" : "Subir foto"}</button>
        ${p.foto_url ? `<button type="button" class="peligro" data-quitar-foto="${p.id}">Quitar</button>` : ""}</div></div>
    </article>`;
  }).join("") : `<p class="vacio">${q ? "No encontré productos con ese nombre." : filtroFotos === "sin" ? "¡Todos los productos tienen foto!" : "No hay productos para mostrar."}</p>`;
}
$("#p-buscar").addEventListener("input", pintarFotos);
$("#p-filtro").addEventListener("click", e => {
  const b = e.target.closest("[data-f]"); if (!b) return;
  filtroFotos = b.dataset.f; b.parentElement.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); pintarFotos();
});
$("#p-lista").addEventListener("click", async e => {
  const sub = e.target.closest("[data-foto]"), quitar = e.target.closest("[data-quitar-foto]");
  if (sub) { fotoPara = CATALOGO.find(p => p.id === +sub.dataset.foto); $("#p-archivo").value = ""; $("#p-archivo").click(); }
  if (quitar) {
    const p = CATALOGO.find(x => x.id === +quitar.dataset.quitarFoto);
    if (!confirm(`¿Quitar la foto de ${p.nombre}?`)) return;
    const { error } = await sb.from("productos").update({ foto_url: null }).eq("id", p.id);
    if (error) return alert("No se pudo quitar: " + error.message);
    borrarArchivo(p.foto_url); p.foto_url = null; pintarFotos(); avisar("Foto quitada");
  }
});
const rutaEnBucket = url => (url || "").split("/storage/v1/object/public/productos/")[1] || null;
function borrarArchivo(url) { const r = rutaEnBucket(url); if (r) sb.storage.from("productos").remove([r]); }

// achica la foto en el celu antes de subirla (máx. 900 px, JPG): sube rápido y pesa poco
async function achicar(archivo) {
  const url = URL.createObjectURL(archivo);
  try {
    const img = await new Promise((ok, mal) => { const i = new Image(); i.onload = () => ok(i); i.onerror = mal; i.src = url; });
    const k = Math.min(1, 900 / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement("canvas"); c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    const ctx = c.getContext("2d"); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(img, 0, 0, c.width, c.height);
    return await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.85));
  } finally { URL.revokeObjectURL(url); }
}
$("#p-archivo").addEventListener("change", async e => {
  const archivo = e.target.files[0], p = fotoPara; if (!archivo || !p) return;
  avisar("Subiendo foto…");
  let blob;
  try { blob = await achicar(archivo); } catch { return alert("No pude leer esa imagen. Probá con otra (JPG o PNG)."); }
  const ruta = `${p.slug || "producto-" + p.id}-${Date.now()}.jpg`;
  const { error: e1 } = await sb.storage.from("productos").upload(ruta, blob, { contentType: "image/jpeg", cacheControl: "31536000" });
  if (e1) return alert("No se pudo subir la foto: " + e1.message);
  const url = sb.storage.from("productos").getPublicUrl(ruta).data.publicUrl;
  const { error: e2 } = await sb.from("productos").update({ foto_url: url }).eq("id", p.id);
  if (e2) { sb.storage.from("productos").remove([ruta]); return alert("No se pudo guardar la foto: " + e2.message); }
  const vieja = p.foto_url; p.foto_url = url; if (vieja) borrarArchivo(vieja);
  pintarFotos(); avisar("Foto guardada · en la página se ve en menos de una hora");
});

/* ---------- Ventas del día ---------- */
$("#d-fecha").value = isoLocal(new Date());
$("#d-fecha").addEventListener("change", cargarDia);
$("#d-ant").addEventListener("click", () => moverDia(-1));
$("#d-sig").addEventListener("click", () => moverDia(1));
function moverDia(n) { const d = new Date($("#d-fecha").value + "T12:00"); d.setDate(d.getDate() + n); $("#d-fecha").value = isoLocal(d); cargarDia(); }

async function cargarDia() {
  const dia = $("#d-fecha").value || isoLocal(new Date());
  const desde = new Date(dia + "T00:00"), hasta = new Date(dia + "T00:00"); hasta.setDate(hasta.getDate() + 1);
  const { data, error } = await sb.from("pedidos")
    .select("numero, origen, estado, medio_pago, total, creado_en, cliente_nombre, cliente_apellido, pedido_items(producto_nombre, etiqueta, cantidad, precio_unit, costo_unit)")
    .in("estado", ["confirmado", "entregado"]).gte("creado_en", desde.toISOString()).lt("creado_en", hasta.toISOString())
    .order("creado_en", { ascending: false });
  const lista = $("#d-lista");
  if (error) { lista.innerHTML = `<p class="vacio">No se pudieron cargar las ventas (${esc(error.message)}).</p>`; return; }
  const total = data.reduce((s, v) => s + +v.total, 0);
  const costo = data.reduce((s, v) => s + v.pedido_items.reduce((a, i) => a + (i.costo_unit ?? i.precio_unit) * i.cantidad, 0), 0);
  $("#d-total").textContent = plata(total); $("#d-cant").textContent = entero(data.length); $("#d-gan").textContent = plata(total - costo);
  lista.innerHTML = data.length ? data.map(v => {
    const hora = new Date(v.creado_en).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" });
    return `<article class="pedido">
      <div class="pedido-cab"><strong class="num">${hora}</strong><span class="estado ${v.origen === "web" ? "confirmado" : "local"}">${v.origen === "web" ? "Web #" + v.numero : "Local"}</span>
        <span>${esc(MEDIOS[v.medio_pago] || v.medio_pago || "")}</span><span class="total num">${plata(v.total)}</span></div>
      <ul>${v.pedido_items.map(i => `<li class="num">${i.cantidad} × ${esc(i.producto_nombre)} (${esc(i.etiqueta)}) — ${plata(i.precio_unit * i.cantidad)}</li>`).join("")}</ul>
      ${v.origen === "manual" ? `<div class="acciones"><button type="button" class="peligro" data-borrar="${v.numero}">Borrar venta</button></div>` : ""}
    </article>`;
  }).join("") : `<p class="vacio">No hay ventas este día.</p>`;
}
$("#d-lista").addEventListener("click", async e => {
  const b = e.target.closest("[data-borrar]"); if (!b) return;
  if (!confirm("¿Borrar esta venta? No se puede deshacer.")) return;
  b.disabled = true;
  const { error } = await sb.rpc("panel_borrar_venta", { p_numero: +b.dataset.borrar });
  if (error) { alert("No se pudo borrar: " + error.message); b.disabled = false; return; }
  cargarDia();
});

sb.auth.onAuthStateChange(ev => { if (ev === "SIGNED_OUT") mostrarLogin(); });
arrancar();
