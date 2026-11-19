-- Opsional untuk proyek yang memerlukan grant eksplisit untuk Supabase Data API.
-- Mengubah hak akses tabel tanpa mengubah baris atau kolom yang sudah ada.
begin;
alter table public.sources enable row level security;
revoke all privileges on table public.sources from anon, authenticated;
grant select, insert, delete on table public.sources to service_role;
commit;
