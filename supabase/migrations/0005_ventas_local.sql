-- =====================================================================
-- 0005: ventas del local, venta por peso y gastos del mes
--   * Las ventas del mostrador son pedidos con origen 'manual' y ya confirmados.
--   * Un ítem puede ser una presentación (250 g, unidad) o un peso libre (350 g).
--   * pedido_items guarda el producto: así se rankea aunque se venda por peso.
--   * gastos: alquiler, luz, impuestos... para la ganancia neta del mes.
-- Correr DESPUÉS de 0004.
-- =====================================================================

-- Precio por kilo de la hoja PRECIO X KG (para vender por peso en el local)
alter table public.productos add column if not exists precio_kg numeric(12,2);

-- Ítems: producto y gramos
alter table public.pedido_items
  add column if not exists producto_id bigint references public.productos(id) on delete set null,
  add column if not exists gramos int check (gramos between 1 and 50000);
create index if not exists pedido_items_producto on public.pedido_items (producto_id);
update public.pedido_items i set producto_id = pr.producto_id
  from public.presentaciones pr where pr.id = i.presentacion_id and i.producto_id is null;

-- Completa producto_id solo cuando viene una presentación (pedidos web)
create or replace function public.item_producto() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.producto_id is null and new.presentacion_id is not null then
    select producto_id into new.producto_id from public.presentaciones where id = new.presentacion_id;
  end if;
  return new;
end $$;
drop trigger if exists pedido_items_producto on public.pedido_items;
create trigger pedido_items_producto before insert or update on public.pedido_items
  for each row execute function public.item_producto();
revoke all on function public.item_producto() from public, anon, authenticated;

-- Más formas de pago para el local (no se ofrecen en la web: activo = false)
insert into public.reglas_pago (medio, nombre, porcentaje, minimo, activo) values
  ('debito', 'Tarjeta de débito', 0, 0, false)
on conflict (medio) do nothing;

-- En el local la forma de pago es solo informativa: el descuento/recargo aplica a la web
create or replace function public.recalcular_total() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_id bigint := coalesce(new.pedido_id, old.pedido_id); v_sub numeric; v_aj numeric;
begin
  select coalesce(sum(precio_unit * cantidad), 0) into v_sub from public.pedido_items where pedido_id = v_id;
  select case when origen = 'web' then public.ajuste_por_pago(medio_pago, v_sub) else 0 end
    into v_aj from public.pedidos where id = v_id;
  update public.pedidos set subtotal = v_sub, ajuste_pago = coalesce(v_aj, 0),
         total = v_sub + coalesce(v_aj, 0), actualizado_en = now()
   where id = v_id;
  return null;
end $$;

-- ---------- Cargar una venta del local (solo admin) -------------------
-- p_items: [{"producto_id": 12, "presentacion_id": 40, "cantidad": 2, "precio_unit": 2500},
--           {"producto_id": 15, "gramos": 350, "cantidad": 1, "precio_unit": 4200}]
create or replace function public.panel_cargar_venta(
  p_fecha timestamptz, p_pago text, p_notas text, p_items jsonb
) returns table (numero bigint, total numeric)
language plpgsql security definer set search_path = '' as $$
declare
  v_pedido bigint; v_numero bigint; it jsonb; v_cant int; v_gr int; v_precio numeric;
  v_prod record; v_pres_id bigint; v_costo numeric; v_etq text;
begin
  if not public.es_admin() then raise exception 'Solo para el dueño'; end if;
  if jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0 or jsonb_array_length(p_items) > 60 then
    raise exception 'La venta tiene que tener entre 1 y 60 productos';
  end if;
  if p_pago is not null and not exists (select 1 from public.reglas_pago where medio = p_pago) then
    raise exception 'Forma de pago desconocida';
  end if;
  if p_fecha is not null and (p_fecha > now() + interval '1 day' or p_fecha < now() - interval '400 days') then
    raise exception 'Fecha fuera de rango';
  end if;

  insert into public.pedidos (cliente_nombre, entrega, medio_pago, notas, origen, estado, creado_en)
  values ('Venta en el local', 'retiro', p_pago, nullif(trim(p_notas), ''), 'manual', 'confirmado', coalesce(p_fecha, now()))
  returning id, pedidos.numero into v_pedido, v_numero;

  for it in select * from jsonb_array_elements(p_items) loop
    v_cant := (it->>'cantidad')::int;
    v_gr := nullif(it->>'gramos', '')::int;
    v_precio := (it->>'precio_unit')::numeric;
    if v_cant is null or v_cant not between 1 and 99 then raise exception 'Cantidad inválida (1 a 99)'; end if;
    if v_precio is null or v_precio < 0 or v_precio > 10000000 then raise exception 'Precio inválido'; end if;

    select p.id, p.nombre, pp.costo_base into v_prod
      from public.productos p left join public.productos_privado pp on pp.producto_id = p.id
     where p.id = (it->>'producto_id')::bigint;
    if not found then raise exception 'Producto inexistente: %', it->>'producto_id'; end if;

    if it ? 'presentacion_id' and it->>'presentacion_id' is not null then
      select pr.id, pr.etiqueta, c.costo into v_pres_id, v_etq, v_costo
        from public.presentaciones pr left join public.presentaciones_costos c on c.presentacion_id = pr.id
       where pr.id = (it->>'presentacion_id')::bigint and pr.producto_id = v_prod.id;
      if not found then raise exception 'Presentación inválida'; end if;
      v_gr := null;
    elsif v_gr is not null then
      if v_gr not between 1 and 50000 then raise exception 'Gramos inválidos'; end if;
      v_pres_id := null;
      v_etq := case when v_gr >= 1000 then replace(trim_scale(round(v_gr / 1000.0, 3))::text, '.', ',') || ' kg' else v_gr || ' g' end;
      v_costo := round(v_prod.costo_base * v_gr / 1000.0, 2);
    else
      raise exception 'Falta la presentación o los gramos';
    end if;

    insert into public.pedido_items (pedido_id, presentacion_id, producto_id, producto_nombre, etiqueta, gramos,
                                     cantidad, precio_unit, costo_unit)
    values (v_pedido, v_pres_id, v_prod.id, v_prod.nombre, v_etq, v_gr, v_cant, v_precio, v_costo);
  end loop;

  return query select p.numero, p.total from public.pedidos p where p.id = v_pedido;
end $$;
revoke all on function public.panel_cargar_venta(timestamptz, text, text, jsonb) from public, anon;
grant execute on function public.panel_cargar_venta(timestamptz, text, text, jsonb) to authenticated;

-- Borrar una venta cargada a mano (los pedidos web se cancelan, no se borran)
create or replace function public.panel_borrar_venta(p_numero bigint)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if not public.es_admin() then raise exception 'Solo para el dueño'; end if;
  delete from public.pedidos where numero = p_numero and origen = 'manual';
  if not found then raise exception 'No se puede borrar el pedido %', p_numero; end if;
end $$;
revoke all on function public.panel_borrar_venta(bigint) from public, anon;
grant execute on function public.panel_borrar_venta(bigint) to authenticated;

-- ---------- Gastos del negocio (solo admin) ---------------------------
create table if not exists public.gastos (
  id          bigint generated always as identity primary key,
  fecha       date not null default current_date,
  categoria   text not null check (length(categoria) between 2 and 40),
  descripcion text check (length(descripcion) <= 200),
  monto       numeric(12,2) not null check (monto > 0 and monto < 100000000),
  creado_en   timestamptz not null default now()
);
create index if not exists gastos_fecha on public.gastos (fecha);
alter table public.gastos enable row level security;
drop policy if exists "admin" on public.gastos;
create policy "admin" on public.gastos for all using (public.es_admin()) with check (public.es_admin());

-- Estadísticas: ahora el ítem trae el producto (también en ventas por peso)
-- ---------- Estadísticas (solo admin) ---------------------------------
-- Cuentan como venta los pedidos CONFIRMADOS o ENTREGADOS.
-- Los pendientes (todavía no respondidos por WhatsApp) y cancelados no suman.
create or replace function public.panel_estadisticas(p_desde date, p_hasta date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  tz constant text := 'America/Argentina/Buenos_Aires';
  r jsonb;
begin
  if not public.es_admin() then
    raise exception 'Solo para el dueño';
  end if;

  with ped as (
    select p.*, (p.creado_en at time zone tz)::date as dia
      from public.pedidos p
     where (p.creado_en at time zone tz)::date between p_desde and p_hasta
  ), venta as (
    select * from ped where estado in ('confirmado', 'entregado')
  ), items as (
    select i.* from public.pedido_items i join venta v on v.id = i.pedido_id
  ), por_producto as (
    select coalesce(producto_id::text, producto_nombre) as k, max(producto_nombre) as producto,
           sum(cantidad) as unidades, sum(precio_unit * cantidad) as ventas,
           sum((precio_unit - coalesce(costo_unit, precio_unit)) * cantidad) as ganancia
      from items group by 1
  )
  select jsonb_build_object(
    'ventas',        coalesce((select sum(total) from venta), 0),
    'costo',         coalesce((select sum(costo_unit * cantidad) from items), 0),
    'ganancia',      coalesce((select sum(total) from venta), 0)
                     - coalesce((select sum(coalesce(costo_unit, precio_unit) * cantidad) from items), 0),
    'items_sin_costo', (select count(*) from items where costo_unit is null),
    'pedidos',       (select count(*) from venta),
    'pendientes',    (select count(*) from ped where estado = 'pendiente'),
    'cancelados',    (select count(*) from ped where estado = 'cancelado'),
    'ticket_promedio', coalesce((select round(avg(total)) from venta), 0),
    'por_dia', coalesce((select jsonb_agg(jsonb_build_object('dia', dia, 'ventas', v, 'pedidos', n) order by dia)
                           from (select dia, sum(total) v, count(*) n from venta group by dia) d), '[]'),
    'por_pago', coalesce((select jsonb_agg(jsonb_build_object('medio', coalesce(rp.nombre, v.medio_pago), 'pedidos', v.n, 'ventas', v.t) order by v.t desc)
                            from (select medio_pago, count(*) n, sum(total) t from venta group by medio_pago) v
                            left join public.reglas_pago rp on rp.medio = v.medio_pago), '[]'),
    'mas_vendidos', coalesce((select jsonb_agg(x order by (x->>'unidades')::numeric desc, (x->>'ventas')::numeric desc)
                                from (select jsonb_build_object('producto', producto, 'unidades', unidades, 'ventas', ventas, 'ganancia', ganancia) x
                                        from por_producto order by unidades desc, ventas desc limit 15) t), '[]'),
    'mas_ganancia', coalesce((select jsonb_agg(x order by (x->>'ganancia')::numeric desc)
                                from (select jsonb_build_object('producto', producto, 'unidades', unidades, 'ventas', ventas, 'ganancia', ganancia) x
                                        from por_producto order by ganancia desc limit 15) t), '[]'),
    -- menos vendidos: productos ACTIVOS de la web, incluidos los que no vendieron nada
    'menos_vendidos', coalesce((select jsonb_agg(x order by (x->>'unidades')::numeric, x->>'producto')
                                  from (select jsonb_build_object('producto', p.nombre, 'unidades', coalesce(pp.unidades, 0),
                                                                  'ventas', coalesce(pp.ventas, 0)) x
                                          from public.productos p
                                          left join por_producto pp on pp.k = p.id::text
                                         where p.activo
                                         order by coalesce(pp.unidades, 0), p.nombre limit 15) t), '[]'),
    'sin_ventas', (select count(*) from public.productos p
                    where p.activo and not exists (select 1 from por_producto pp where pp.k = p.id::text))
  ) into r;
  return r;
end $$;

revoke all on function public.panel_estadisticas(date, date) from public, anon;
grant execute on function public.panel_estadisticas(date, date) to authenticated;


-- ---------- Dashboard (solo admin) ------------------------------------
-- Período actual vs el período anterior de igual largo. Cuentan los pedidos
-- confirmados o entregados (ventas del local + pedidos web confirmados).
-- p_categoria opcional: filtra todo por categoría (los gastos no se filtran).
-- p_ant_desde / p_ant_hasta: período para comparar (ej. "este mes" contra los mismos días del mes pasado).
-- Si no vienen, se compara con el período inmediatamente anterior de igual largo.
create or replace function public.panel_dashboard(p_desde date, p_hasta date, p_categoria text default null,
                                                  p_ant_desde date default null, p_ant_hasta date default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  tz constant text := 'America/Argentina/Buenos_Aires';
  v_dias int := p_hasta - p_desde + 1;
  v_ant_desde date := coalesce(p_ant_desde, p_desde - (p_hasta - p_desde + 1));
  v_ant_hasta date := coalesce(p_ant_hasta, p_desde - 1);
  r jsonb;
begin
  if not public.es_admin() then raise exception 'Solo para el dueño'; end if;
  if p_hasta < p_desde or v_dias > 1100 or v_ant_hasta < v_ant_desde or v_ant_hasta >= p_desde
     or v_ant_hasta - v_ant_desde > 1100 then raise exception 'Período inválido'; end if;

  with base as (
    select p.id as pedido_id, p.origen::text as origen, p.medio_pago, p.ajuste_pago,
           (p.creado_en at time zone tz)::date as dia,
           case when (p.creado_en at time zone tz)::date >= p_desde then 'act' else 'ant' end as per,
           i.producto_id, i.producto_nombre, i.cantidad, i.gramos, i.precio_unit,
           coalesce(i.costo_unit, i.precio_unit) as costo_unit, coalesce(c.nombre, 'Sin categoría') as categoria
      from public.pedidos p
      join public.pedido_items i on i.pedido_id = p.id
      left join public.productos pr on pr.id = i.producto_id
      left join public.categorias c on c.id = pr.categoria_id
     where p.estado in ('confirmado', 'entregado')
       and ((p.creado_en at time zone tz)::date between p_desde and p_hasta
            or (p.creado_en at time zone tz)::date between v_ant_desde and v_ant_hasta)
       and (p_categoria is null or c.nombre = p_categoria)
  ),
  ped as (   -- un renglón por pedido: el ajuste de pago se suma una sola vez
    select distinct pedido_id, per, dia, origen, medio_pago,
           case when p_categoria is null then ajuste_pago else 0 end as ajuste
      from base
  ),
  kp as (
    select b.per, sum(b.precio_unit * b.cantidad) + coalesce(max(a.aj), 0) as ventas,
           sum(b.costo_unit * b.cantidad) as costo, count(distinct b.pedido_id) as n
      from base b left join (select per, sum(ajuste) aj from ped group by per) a on a.per = b.per
     group by b.per
  ),
  gas as (
    select case when fecha >= p_desde then 'act' else 'ant' end as per, sum(monto) as g
      from public.gastos where fecha between p_desde and p_hasta or fecha between v_ant_desde and v_ant_hasta group by 1
  ),
  kpis as (
    select per.per, jsonb_build_object(
             'ventas', coalesce(kp.ventas, 0), 'costo', coalesce(kp.costo, 0),
             'ganancia', coalesce(kp.ventas, 0) - coalesce(kp.costo, 0),
             'gastos', coalesce(gas.g, 0),
             'neta', coalesce(kp.ventas, 0) - coalesce(kp.costo, 0) - coalesce(gas.g, 0),
             'ventas_n', coalesce(kp.n, 0),
             'ticket', case when kp.n > 0 then round(kp.ventas / kp.n) else 0 end,
             'margen', case when kp.ventas > 0 then round((kp.ventas - kp.costo) / kp.ventas * 100, 1) else 0 end) as k
      from (values ('act'), ('ant')) per(per)
      left join kp on kp.per = per.per left join gas on gas.per = per.per
  ),
  act as (select * from base where per = 'act'),
  por_prod as (
    select coalesce(producto_id::text, producto_nombre) as k, max(producto_nombre) as producto,
           sum(cantidad) filter (where gramos is null) as unidades,
           round(sum(gramos * cantidad) filter (where gramos is not null) / 1000.0, 2) as kilos,
           sum(precio_unit * cantidad) as ventas, sum((precio_unit - costo_unit) * cantidad) as ganancia
      from act group by 1
  ),
  prod_json as (select k, jsonb_build_object('producto', producto, 'unidades', coalesce(unidades, 0), 'kilos', coalesce(kilos, 0),
                                             'ventas', ventas, 'ganancia', ganancia) as j, ventas, ganancia from por_prod)
  select jsonb_build_object(
    'actual', (select k from kpis where per = 'act'),
    'anterior', (select k from kpis where per = 'ant'),
    'dias', v_dias,
    'por_dia', coalesce((select jsonb_agg(jsonb_build_object('dia', d.dia, 'ventas', d.v + coalesce(a.aj, 0), 'ganancia', d.g + coalesce(a.aj, 0), 'n', d.n) order by d.dia)
                           from (select dia, sum(precio_unit * cantidad) v, sum((precio_unit - costo_unit) * cantidad) g, count(distinct pedido_id) n from act group by dia) d
                           left join (select dia, sum(ajuste) aj from ped where per = 'act' group by dia) a on a.dia = d.dia), '[]'),
    'por_canal', coalesce((select jsonb_agg(jsonb_build_object('canal', case when origen = 'web' then 'Web' else 'Local' end, 'ventas', v, 'n', n) order by v desc)
                             from (select b.origen, sum(b.precio_unit * b.cantidad) + coalesce(max(a.aj), 0) v, count(distinct b.pedido_id) n
                                     from act b left join (select origen, sum(ajuste) aj from ped where per = 'act' group by origen) a on a.origen = b.origen
                                    group by b.origen) x), '[]'),
    'por_pago', coalesce((select jsonb_agg(jsonb_build_object('medio', coalesce(rp.nombre, 'Sin dato'), 'ventas', x.v, 'n', x.n) order by x.v desc)
                            from (select medio_pago, sum(precio_unit * cantidad) v, count(distinct pedido_id) n from act group by medio_pago) x
                            left join public.reglas_pago rp on rp.medio = x.medio_pago), '[]'),
    'por_categoria', coalesce((select jsonb_agg(jsonb_build_object('categoria', categoria, 'ventas', v, 'ganancia', g) order by v desc)
                                 from (select categoria, sum(precio_unit * cantidad) v, sum((precio_unit - costo_unit) * cantidad) g from act group by categoria) x), '[]'),
    'top_ventas',   coalesce((select jsonb_agg(j order by ventas desc) from (select j, ventas from prod_json order by ventas desc limit 10) t), '[]'),
    'top_ganancia', coalesce((select jsonb_agg(j order by ganancia desc) from (select j, ganancia from prod_json order by ganancia desc limit 10) t), '[]'),
    'menos_vendidos', coalesce((select jsonb_agg(jsonb_build_object('producto', nombre, 'ventas', v) order by v, nombre)
                                  from (select p.nombre, coalesce(pp.ventas, 0) v
                                          from public.productos p left join public.categorias c on c.id = p.categoria_id
                                          left join por_prod pp on pp.k = p.id::text
                                         where p.activo and (p_categoria is null or c.nombre = p_categoria)
                                         order by 2, 1 limit 10) t), '[]'),
    'sin_ventas', (select count(*) from public.productos p left join public.categorias c on c.id = p.categoria_id
                    where p.activo and (p_categoria is null or c.nombre = p_categoria)
                      and not exists (select 1 from por_prod pp where pp.k = p.id::text)),
    'pendientes_web', (select count(*) from public.pedidos p where p.origen = 'web' and p.estado = 'pendiente'
                         and (p.creado_en at time zone tz)::date between p_desde and p_hasta),
    'gastos', coalesce((select jsonb_agg(jsonb_build_object('categoria', categoria, 'monto', m) order by m desc)
                          from (select categoria, sum(monto) m from public.gastos where fecha between p_desde and p_hasta group by categoria) x), '[]')
  ) into r;
  return r;
end $$;
revoke all on function public.panel_dashboard(date, date, text, date, date) from public, anon;
grant execute on function public.panel_dashboard(date, date, text, date, date) to authenticated;

-- ---------- Stock (hoja STOCK del Excel + ventas) ----------------------
-- Los movimientos se copian de la hoja STOCK del Drive en cada sync (origen 'excel').
-- Stock = último conteo + ingresos y ajustes posteriores − lo vendido desde ese día.
create table if not exists public.stock_movimientos (
  id          bigint generated always as identity primary key,
  producto_id bigint not null references public.productos(id) on delete cascade,
  fecha       date not null,
  tipo        text not null check (tipo in ('conteo', 'ingreso', 'ajuste', 'minimo')),
  cantidad    numeric(12,3) not null,
  unidad      text not null check (unidad in ('kg', 'u')),
  nota        text check (length(nota) <= 200),
  fila        int,                      -- fila del Excel (desempata movimientos del mismo día)
  origen      text not null default 'excel',
  creado_en   timestamptz not null default now()
);
create index if not exists stock_mov_producto on public.stock_movimientos (producto_id, fecha);
alter table public.stock_movimientos enable row level security;
drop policy if exists "admin" on public.stock_movimientos;
create policy "admin" on public.stock_movimientos for all using (public.es_admin()) with check (public.es_admin());

create or replace function public.panel_stock()
returns table (producto_id bigint, producto text, categoria text, unidad text, stock numeric, minimo numeric,
               fecha_conteo date, contado numeric, entradas numeric, vendido numeric)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.es_admin() then raise exception 'Solo para el dueño'; end if;
  return query
  with conteo as (
    select distinct on (m.producto_id) m.producto_id, m.fecha, coalesce(m.fila, 0) as fila, m.cantidad, m.unidad
      from public.stock_movimientos m where m.tipo = 'conteo'
     order by m.producto_id, m.fecha desc, m.fila desc nulls last, m.id desc
  ),
  minimo as (
    select distinct on (m.producto_id) m.producto_id, m.cantidad, m.unidad
      from public.stock_movimientos m where m.tipo = 'minimo'
     order by m.producto_id, m.fecha desc, m.fila desc nulls last, m.id desc
  ),
  entradas as (   -- ingresos y ajustes posteriores al conteo (mismo día: los que están más abajo en el Excel)
    select c.producto_id, sum(m.cantidad) as e
      from conteo c join public.stock_movimientos m on m.producto_id = c.producto_id and m.unidad = c.unidad
     where m.tipo in ('ingreso', 'ajuste') and (m.fecha, coalesce(m.fila, 0)) > (c.fecha, c.fila)
     group by c.producto_id
  ),
  vendido as (    -- ventas confirmadas desde el día del conteo, en la unidad del stock
    select c.producto_id,
           sum(case when c.unidad = 'kg' then coalesce(i.gramos, pr.gramos) * i.cantidad / 1000.0
                    when i.gramos is null then i.cantidad end) as v
      from conteo c
      join public.pedido_items i on i.producto_id = c.producto_id
      join public.pedidos p on p.id = i.pedido_id
      left join public.presentaciones pr on pr.id = i.presentacion_id
     where p.estado in ('confirmado', 'entregado')
       and (p.creado_en at time zone 'America/Argentina/Buenos_Aires')::date >= c.fecha
     group by c.producto_id
  )
  select c.producto_id, pr.nombre, coalesce(cat.nombre, ''), c.unidad,
         round(c.cantidad + coalesce(e.e, 0) - coalesce(v.v, 0), 3),
         case when mi.unidad = c.unidad then mi.cantidad end,
         c.fecha, c.cantidad, coalesce(e.e, 0), round(coalesce(v.v, 0), 3)
    from conteo c
    join public.productos pr on pr.id = c.producto_id
    left join public.categorias cat on cat.id = pr.categoria_id
    left join entradas e on e.producto_id = c.producto_id
    left join vendido v on v.producto_id = c.producto_id
    left join minimo mi on mi.producto_id = c.producto_id
   order by pr.nombre;
end $$;
revoke all on function public.panel_stock() from public, anon;
grant execute on function public.panel_stock() to authenticated;
