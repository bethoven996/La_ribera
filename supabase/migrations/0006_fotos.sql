-- =====================================================================
-- 0006: fotos de productos subidas desde el panel
--   * Bucket público "productos" en Supabase Storage (la web muestra las fotos).
--   * Solo el dueño puede subir, cambiar o borrar fotos.
--   * La URL queda en productos.foto_url (la sync del Excel nunca la pisa).
-- Correr DESPUÉS de 0005.
-- =====================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('productos', 'productos', true, 3145728, array['image/jpeg', 'image/webp', 'image/png'])
on conflict (id) do update set public = true, file_size_limit = excluded.file_size_limit,
                               allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "fotos productos: dueño ve"     on storage.objects;
drop policy if exists "fotos productos: dueño sube"   on storage.objects;
drop policy if exists "fotos productos: dueño cambia" on storage.objects;
drop policy if exists "fotos productos: dueño borra"  on storage.objects;

create policy "fotos productos: dueño ve" on storage.objects for select to authenticated
  using (bucket_id = 'productos' and public.es_admin());
create policy "fotos productos: dueño sube" on storage.objects for insert to authenticated
  with check (bucket_id = 'productos' and public.es_admin());
create policy "fotos productos: dueño cambia" on storage.objects for update to authenticated
  using (bucket_id = 'productos' and public.es_admin()) with check (bucket_id = 'productos' and public.es_admin());
create policy "fotos productos: dueño borra" on storage.objects for delete to authenticated
  using (bucket_id = 'productos' and public.es_admin());
