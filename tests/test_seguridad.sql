\set ON_ERROR_STOP 0
\echo '===== Como visitante anonimo ====='
set role anon;
select 'catalogo visible: ' || count(*) from productos;
select 'presentaciones visibles: ' || count(*) from presentaciones;
select 'inactivos visibles (debe ser 0): ' || count(*) from productos where not activo;
select 'costos visibles (debe ser 0): ' || count(*) from presentaciones_costos;
select 'proveedores visibles (debe ser 0): ' || count(*) from productos_privado;
select 'pedidos visibles (debe ser 0): ' || count(*) from pedidos;
\echo '-- intento cambiar un precio (no debe afectar filas):'
update presentaciones set precio = 1 where true;
\echo '-- intento insertar un pedido directo con precio trucho (debe fallar):'
insert into pedidos (cliente_nombre, total) values ('Hacker', 1);
\echo '-- pedido legitimo via crear_pedido:'
select * from crear_pedido('Juan', 'Perez', '3415555555', 'retiro', null, 'efectivo', null,
  (select jsonb_agg(jsonb_build_object('presentacion_id', id, 'cantidad', 2)) from (select id from presentaciones order by id limit 2) x));
\echo '-- intento mandar mi propio precio en el item (se ignora, usa el de la base):'
select * from crear_pedido('Juan', 'Perez', null, 'retiro', null, 'efectivo', null,
  jsonb_build_array(jsonb_build_object('presentacion_id', (select min(id) from presentaciones), 'cantidad', 1, 'precio_unit', 1)));
\echo '-- envio sin direccion (debe fallar):'
select * from crear_pedido('Juan', 'Perez', null, 'envio', '', 'efectivo', null, jsonb_build_array(jsonb_build_object('presentacion_id', (select min(id) from presentaciones), 'cantidad', 1)));
\echo '-- sin forma de pago (debe fallar):'
select * from crear_pedido('Juan', 'Perez', null, 'retiro', null, null, null, jsonb_build_array(jsonb_build_object('presentacion_id', (select min(id) from presentaciones), 'cantidad', 1)));
\echo '-- cantidad 500 (debe fallar):'
select * from crear_pedido('Juan', 'Perez', null, 'retiro', null, 'efectivo', null, jsonb_build_array(jsonb_build_object('presentacion_id', (select min(id) from presentaciones), 'cantidad', 500)));
\echo '-- producto inactivo (debe fallar):'
select * from crear_pedido('Juan', 'Perez', null, 'retiro', null, 'efectivo', null, '[{"presentacion_id":999999,"cantidad":1}]');
reset role;
\echo '===== Como admin ====='
insert into auth.users (id, email) values ('11111111-1111-1111-1111-111111111111', 'admin@laribera.test') on conflict do nothing;
insert into admins values ('11111111-1111-1111-1111-111111111111') on conflict do nothing;
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
select 'admin ve costos: ' || count(*) from presentaciones_costos;
select 'admin ve pedidos: ' || count(*) from pedidos;
select numero, cliente_nombre, total from pedidos order by numero;
\echo '-- admin cambia cantidad de un item y el total se recalcula:'
update pedido_items set cantidad = 1 where pedido_id = (select min(id) from pedidos);
select numero, total from pedidos order by numero limit 1;
\echo '===== Usuario logueado que NO es admin ====='
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select 'no-admin ve costos (debe ser 0): ' || count(*) from presentaciones_costos;
select 'no-admin ve pedidos (debe ser 0): ' || count(*) from pedidos;
reset role;
