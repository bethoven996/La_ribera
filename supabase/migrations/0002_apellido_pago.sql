-- =====================================================================
-- 0002: apellido y forma de pago en los pedidos
-- Correr en Supabase → SQL Editor DESPUÉS de 0001_init.sql.
-- =====================================================================

create type public.medio_pago as enum ('efectivo', 'transferencia', 'mercadopago');

alter table public.pedidos
  add column cliente_apellido text check (length(cliente_apellido) between 1 and 60),
  add column medio_pago public.medio_pago;

-- La función vieja tenía otra firma: se reemplaza por la nueva
drop function if exists public.crear_pedido(text, text, public.tipo_entrega, text, text, jsonb);

create or replace function public.crear_pedido(
  p_nombre text, p_apellido text, p_tel text, p_entrega public.tipo_entrega,
  p_direccion text, p_pago public.medio_pago, p_notas text, p_items jsonb
) returns table (numero bigint, total numeric)
language plpgsql security definer set search_path = '' as $$
declare
  v_pedido bigint; v_numero bigint; v_total numeric := 0;
  it jsonb; v_cant int; r record;
begin
  if coalesce(trim(p_nombre), '') = '' or coalesce(trim(p_apellido), '') = '' then
    raise exception 'Faltan nombre y apellido';
  end if;
  if p_pago is null then
    raise exception 'Falta la forma de pago';
  end if;
  if jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0
     or jsonb_array_length(p_items) > 50 then
    raise exception 'El pedido tiene que tener entre 1 y 50 productos';
  end if;
  if p_entrega = 'envio' and coalesce(trim(p_direccion), '') = '' then
    raise exception 'Falta la dirección de envío';
  end if;

  insert into public.pedidos (cliente_nombre, cliente_apellido, cliente_tel, entrega, direccion, medio_pago, notas, origen)
  values (trim(p_nombre), trim(p_apellido), nullif(trim(p_tel), ''), p_entrega, nullif(trim(p_direccion), ''),
          p_pago, nullif(trim(p_notas), ''), 'web')
  returning id, pedidos.numero into v_pedido, v_numero;

  for it in select * from jsonb_array_elements(p_items) loop
    v_cant := (it->>'cantidad')::int;
    if v_cant is null or v_cant not between 1 and 99 then
      raise exception 'Cantidad inválida (1 a 99)';
    end if;
    select pr.id, pr.etiqueta, pr.precio, p.nombre, c.costo into r
      from public.presentaciones pr
      join public.productos p on p.id = pr.producto_id
      left join public.presentaciones_costos c on c.presentacion_id = pr.id
     where pr.id = (it->>'presentacion_id')::bigint
       and pr.activo and p.activo and pr.precio is not null;
    if not found then
      raise exception 'Producto no disponible: %', it->>'presentacion_id';
    end if;
    insert into public.pedido_items (pedido_id, presentacion_id, producto_nombre, etiqueta, cantidad, precio_unit, costo_unit)
    values (v_pedido, r.id, r.nombre, r.etiqueta, v_cant, r.precio, r.costo);
    v_total := v_total + r.precio * v_cant;
  end loop;

  update public.pedidos set total = v_total where id = v_pedido;
  return query select v_numero, v_total;
end $$;

revoke all on function public.crear_pedido(text, text, text, public.tipo_entrega, text, public.medio_pago, text, jsonb) from public;
grant execute on function public.crear_pedido(text, text, text, public.tipo_entrega, text, public.medio_pago, text, jsonb) to anon, authenticated;
