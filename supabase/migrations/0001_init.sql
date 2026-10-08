-- =====================================================================
-- La Ribera — esquema inicial
-- Pegar entero en Supabase → SQL Editor → Run.
--
-- Seguridad:
--   * Todo con RLS activado. El público (anon) solo LEE catálogo activo.
--   * Costos, proveedores, márgenes e historial viven en tablas aparte
--     que el público no puede leer (RLS filtra filas, no columnas).
--   * Los pedidos NO se insertan directo: pasan por crear_pedido(), que
--     toma los precios de la base. El cliente no puede mandar su precio.
--   * Admin = usuario de Supabase Auth listado en public.admins.
-- =====================================================================

-- ---------- Admin ----------------------------------------------------
create table public.admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  creado_en timestamptz not null default now()
);

create or replace function public.es_admin()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.admins where user_id = auth.uid());
$$;

-- ---------- Catálogo (público) ---------------------------------------
create table public.categorias (
  id      bigint generated always as identity primary key,
  slug    text not null unique,
  nombre  text not null,
  orden   int  not null default 0
);

create table public.productos (
  id            bigint generated always as identity primary key,
  clave         text not null unique,          -- clave de cruce con la planilla (no editar)
  slug          text not null unique,
  nombre        text not null,
  categoria_id  bigint references public.categorias(id),
  -- Campos de la web (los edita el admin, la sync nunca los pisa)
  descripcion   text,
  foto_url      text,
  tags          text[] not null default '{}',  -- sin-tacc, vegano, keto...
  -- Estado
  activo        boolean not null default true,  -- lo maneja la sync
  en_planilla   boolean not null default true,  -- false si desapareció del Drive
  actualizado_en timestamptz not null default now()
);
create index on public.productos (categoria_id);

create table public.presentaciones (
  id           bigint generated always as identity primary key,
  producto_id  bigint not null references public.productos(id) on delete cascade,
  etiqueta     text not null,                  -- "250 g", "1 kg", "unidad"
  gramos       int,                            -- null = por unidad
  precio       numeric(12,2),                  -- null = sin precio, no se muestra
  activo       boolean not null default true,
  unique (producto_id, etiqueta)
);

-- ---------- Datos privados del negocio (solo admin) ------------------
create table public.productos_privado (
  producto_id      bigint primary key references public.productos(id) on delete cascade,
  proveedor        text,
  costo_base       numeric(12,2),              -- costo x kg o unidad
  nombre_original  text                        -- tal cual figura en la planilla
);

create table public.presentaciones_costos (
  presentacion_id  bigint primary key references public.presentaciones(id) on delete cascade,
  costo            numeric(12,2),              -- costo total (packaging + reposición)
  margen           numeric(6,4)
);

create table public.historial_precios (
  id               bigint generated always as identity primary key,
  presentacion_id  bigint not null references public.presentaciones(id) on delete cascade,
  precio           numeric(12,2),
  costo            numeric(12,2),
  fecha            timestamptz not null default now()
);
create index on public.historial_precios (presentacion_id, fecha);

create table public.sync_log (
  id         bigint generated always as identity primary key,
  fecha      timestamptz not null default now(),
  ok         boolean not null,
  resumen    jsonb not null default '{}',
  revisar    jsonb not null default '[]'      -- filas con problemas de la planilla
);

-- ---------- Pedidos --------------------------------------------------
create type public.estado_pedido as enum ('pendiente', 'confirmado', 'entregado', 'cancelado');
create type public.origen_pedido as enum ('web', 'manual');
create type public.tipo_entrega  as enum ('retiro', 'envio');

create table public.pedidos (
  id              bigint generated always as identity primary key,
  numero          bigint generated always as identity (start with 1001) unique,
  cliente_nombre  text not null check (length(cliente_nombre) between 2 and 80),
  cliente_tel     text check (length(cliente_tel) <= 30),
  entrega         public.tipo_entrega not null default 'retiro',
  direccion       text check (length(direccion) <= 200),
  notas           text check (length(notas) <= 500),
  origen          public.origen_pedido not null default 'web',
  estado          public.estado_pedido not null default 'pendiente',
  total           numeric(12,2) not null default 0,
  creado_en       timestamptz not null default now(),
  actualizado_en  timestamptz not null default now()
);
create index on public.pedidos (estado, creado_en);

create table public.pedido_items (
  id               bigint generated always as identity primary key,
  pedido_id        bigint not null references public.pedidos(id) on delete cascade,
  presentacion_id  bigint references public.presentaciones(id) on delete set null,
  -- Foto del momento de la venta: si mañana cambia el precio, la venta no cambia
  producto_nombre  text not null,
  etiqueta         text not null,
  cantidad         int  not null check (cantidad between 1 and 99),
  precio_unit      numeric(12,2) not null,
  costo_unit       numeric(12,2)
);
create index on public.pedido_items (pedido_id);
create index on public.pedido_items (presentacion_id);

-- ---------- Crear pedido (lo único que el público puede escribir) ----
-- items: [{"presentacion_id": 12, "cantidad": 2}, ...]
create or replace function public.crear_pedido(
  p_nombre text, p_tel text, p_entrega public.tipo_entrega,
  p_direccion text, p_notas text, p_items jsonb
) returns table (numero bigint, total numeric)
language plpgsql security definer set search_path = '' as $$
declare
  v_pedido bigint; v_numero bigint; v_total numeric := 0;
  it jsonb; v_cant int; r record;
begin
  if jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0
     or jsonb_array_length(p_items) > 50 then
    raise exception 'El pedido tiene que tener entre 1 y 50 productos';
  end if;
  if p_entrega = 'envio' and coalesce(trim(p_direccion), '') = '' then
    raise exception 'Falta la dirección de envío';
  end if;

  insert into public.pedidos (cliente_nombre, cliente_tel, entrega, direccion, notas, origen)
  values (trim(p_nombre), trim(p_tel), p_entrega, nullif(trim(p_direccion), ''), nullif(trim(p_notas), ''), 'web')
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

-- Recalcula el total cuando el admin edita los ítems de un pedido
create or replace function public.recalcular_total() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  update public.pedidos p
     set total = coalesce((select sum(precio_unit * cantidad) from public.pedido_items where pedido_id = p.id), 0),
         actualizado_en = now()
   where p.id = coalesce(new.pedido_id, old.pedido_id);
  return null;
end $$;
create trigger pedido_items_total after insert or update or delete on public.pedido_items
  for each row execute function public.recalcular_total();

-- ---------- RLS ------------------------------------------------------
alter table public.admins                enable row level security;
alter table public.categorias            enable row level security;
alter table public.productos             enable row level security;
alter table public.presentaciones        enable row level security;
alter table public.productos_privado     enable row level security;
alter table public.presentaciones_costos enable row level security;
alter table public.historial_precios     enable row level security;
alter table public.sync_log              enable row level security;
alter table public.pedidos               enable row level security;
alter table public.pedido_items          enable row level security;

-- Público: solo catálogo activo
create policy "catalogo: lectura publica" on public.categorias
  for select using (true);
create policy "productos: activos publicos" on public.productos
  for select using (activo or public.es_admin());
create policy "presentaciones: activas publicas" on public.presentaciones
  for select using ((activo and precio is not null) or public.es_admin());

-- Admin: todo
create policy "admin" on public.categorias            for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.productos             for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.presentaciones        for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.productos_privado     for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.presentaciones_costos for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.historial_precios     for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.sync_log              for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.pedidos               for all using (public.es_admin()) with check (public.es_admin());
create policy "admin" on public.pedido_items          for all using (public.es_admin()) with check (public.es_admin());
create policy "admin: se ve a si mismo" on public.admins for select using (user_id = auth.uid());

-- Permisos de ejecución
revoke all on function public.crear_pedido(text, text, public.tipo_entrega, text, text, jsonb) from public;
grant execute on function public.crear_pedido(text, text, public.tipo_entrega, text, text, jsonb) to anon, authenticated;
revoke all on function public.recalcular_total() from public, anon, authenticated;
