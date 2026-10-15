-- =====================================================================
-- 0004: panel del dueño
--   * crear_pedido_web: la web registra el pedido usando slug + presentación
--     (la web lee el catálogo de un archivo, no conoce los id de la base).
--   * panel_estadisticas: ventas, ganancia, más y menos vendidos.
--   * panel_cambiar_estado: confirmar / entregar / cancelar un pedido.
-- Correr DESPUÉS de 0003.
-- =====================================================================

-- ---------- Pedido desde la web ---------------------------------------
-- p_items: [{"slug": "almendras", "etiqueta": "250 g", "cantidad": 2}, ...]
create or replace function public.crear_pedido_web(
  p_nombre text, p_apellido text, p_tel text, p_entrega public.tipo_entrega,
  p_direccion text, p_pago text, p_notas text, p_items jsonb
) returns table (numero bigint, subtotal numeric, ajuste numeric, total numeric)
language plpgsql security definer set search_path = '' as $$
declare
  v_items jsonb := '[]'; it jsonb; v_id bigint;
begin
  -- freno anti-spam: un visitante no puede llenar el panel de pedidos falsos
  if (select count(*) from public.pedidos where origen = 'web' and creado_en > now() - interval '10 minutes') >= 40 then
    raise exception 'Demasiados pedidos seguidos. Probá en unos minutos.';
  end if;
  if jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0
     or jsonb_array_length(p_items) > 50 then
    raise exception 'El pedido tiene que tener entre 1 y 50 productos';
  end if;
  for it in select * from jsonb_array_elements(p_items) loop
    v_id := null;
    select pr.id into v_id
      from public.presentaciones pr
      join public.productos p on p.id = pr.producto_id
     where p.slug = it->>'slug' and pr.etiqueta = it->>'etiqueta';
    if v_id is null then
      raise exception 'Producto no disponible: % %', it->>'slug', it->>'etiqueta';
    end if;
    v_items := v_items || jsonb_build_object('presentacion_id', v_id, 'cantidad', it->'cantidad');
  end loop;
  return query select * from public.crear_pedido(p_nombre, p_apellido, p_tel, p_entrega,
                                                 p_direccion, p_pago, p_notas, v_items);
end $$;

revoke all on function public.crear_pedido_web(text, text, text, public.tipo_entrega, text, text, text, jsonb) from public;
grant execute on function public.crear_pedido_web(text, text, text, public.tipo_entrega, text, text, text, jsonb) to anon, authenticated;

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
    select i.*, pr.producto_id
      from public.pedido_items i
      join venta v on v.id = i.pedido_id
      left join public.presentaciones pr on pr.id = i.presentacion_id
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

-- ---------- Cambiar estado de un pedido (solo admin) -----------------
create or replace function public.panel_cambiar_estado(p_numero bigint, p_estado public.estado_pedido)
returns void language plpgsql security definer set search_path = '' as $$
begin
  if not public.es_admin() then
    raise exception 'Solo para el dueño';
  end if;
  update public.pedidos set estado = p_estado, actualizado_en = now() where numero = p_numero;
  if not found then
    raise exception 'No existe el pedido %', p_numero;
  end if;
end $$;

revoke all on function public.panel_cambiar_estado(bigint, public.estado_pedido) from public, anon;
grant execute on function public.panel_cambiar_estado(bigint, public.estado_pedido) to authenticated;
