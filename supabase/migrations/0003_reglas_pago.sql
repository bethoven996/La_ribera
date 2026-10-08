-- =====================================================================
-- 0003: descuentos y recargos por forma de pago
--   * Efectivo: 10% de descuento si el pedido SUPERA $20.000
--   * Tarjeta de crédito: 10% de recargo
--   * Transferencia: sin cambios (alias La.ribera780)
-- Las reglas viven en una tabla: el dueño las puede cambiar desde el panel
-- sin tocar código. La base calcula el total: el cliente no puede inventarlo.
-- Correr DESPUÉS de 0002.
-- =====================================================================

-- La forma de pago pasa de enum a texto con clave foránea a reglas_pago:
-- así se pueden agregar medios nuevos desde el panel sin migraciones.
create table public.reglas_pago (
  medio        text primary key check (medio ~ '^[a-z]+$'),
  nombre       text not null,
  porcentaje   numeric(5,2) not null default 0,   -- negativo = descuento, positivo = recargo
  minimo       numeric(12,2) not null default 0,  -- se aplica si el subtotal SUPERA este monto
  activo       boolean not null default true,     -- si está en false, no se ofrece en la web
  datos        text                               -- ej. alias para transferir
);
insert into public.reglas_pago (medio, nombre, porcentaje, minimo, activo, datos) values
  ('efectivo',      'Efectivo',           -10, 20000, true,  null),
  ('transferencia', 'Transferencia',        0,     0, true,  'La.ribera780'),
  ('credito',       'Tarjeta de crédito',  10,     0, true,  null),
  ('mercadopago',   'Mercado Pago',         0,     0, false, null);

alter table public.pedidos alter column medio_pago type text using medio_pago::text;
alter table public.pedidos add constraint pedidos_medio_pago_fk foreign key (medio_pago) references public.reglas_pago(medio);
drop function if exists public.crear_pedido(text, text, text, public.tipo_entrega, text, public.medio_pago, text, jsonb);
drop type public.medio_pago;

alter table public.reglas_pago enable row level security;
create policy "reglas: lectura publica" on public.reglas_pago for select using (true);
create policy "admin" on public.reglas_pago for all using (public.es_admin()) with check (public.es_admin());

alter table public.pedidos
  add column subtotal    numeric(12,2) not null default 0,
  add column ajuste_pago numeric(12,2) not null default 0;   -- descuento (−) o recargo (+)

-- Calcula el ajuste según la regla vigente
create or replace function public.ajuste_por_pago(p_medio text, p_subtotal numeric)
returns numeric language sql stable security definer set search_path = '' as $$
  select coalesce((select round(p_subtotal * r.porcentaje / 100)
                     from public.reglas_pago r
                    where r.medio = p_medio and p_subtotal > r.minimo), 0);
$$;

-- Total = subtotal + ajuste. Se recalcula si el admin edita los ítems.
create or replace function public.recalcular_total() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_id bigint := coalesce(new.pedido_id, old.pedido_id); v_sub numeric; v_aj numeric;
begin
  select coalesce(sum(precio_unit * cantidad), 0) into v_sub from public.pedido_items where pedido_id = v_id;
  select public.ajuste_por_pago(medio_pago, v_sub) into v_aj from public.pedidos where id = v_id;
  update public.pedidos set subtotal = v_sub, ajuste_pago = coalesce(v_aj, 0),
         total = v_sub + coalesce(v_aj, 0), actualizado_en = now()
   where id = v_id;
  return null;
end $$;

-- crear_pedido: misma firma que en 0002, ahora valida que el medio esté activo
-- y deja que el trigger calcule subtotal, ajuste y total
create or replace function public.crear_pedido(
  p_nombre text, p_apellido text, p_tel text, p_entrega public.tipo_entrega,
  p_direccion text, p_pago text, p_notas text, p_items jsonb
) returns table (numero bigint, subtotal numeric, ajuste numeric, total numeric)
language plpgsql security definer set search_path = '' as $$
declare
  v_pedido bigint; v_numero bigint; it jsonb; v_cant int; r record;
begin
  if coalesce(trim(p_nombre), '') = '' or coalesce(trim(p_apellido), '') = '' then
    raise exception 'Faltan nombre y apellido';
  end if;
  if p_pago is null or not exists (select 1 from public.reglas_pago where medio = p_pago and activo) then
    raise exception 'Forma de pago no disponible';
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
  end loop;

  return query select p.numero, p.subtotal, p.ajuste_pago, p.total from public.pedidos p where p.id = v_pedido;
end $$;

revoke all on function public.crear_pedido(text, text, text, public.tipo_entrega, text, text, text, jsonb) from public;
grant execute on function public.crear_pedido(text, text, text, public.tipo_entrega, text, text, text, jsonb) to anon, authenticated;
revoke all on function public.ajuste_por_pago(text, numeric) from public;
grant execute on function public.ajuste_por_pago(text, numeric) to anon, authenticated;
