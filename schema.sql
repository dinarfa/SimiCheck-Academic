-- Jalankan sekali di Supabase Dashboard > SQL Editor.
-- Hanya aplikasi backend yang memegang SERVICE_ROLE_KEY boleh membaca tabel.
create table if not exists public.sources (
  id text primary key,
  title text not null,
  origin text not null,
  doi text default '',
  license text default '',
  source_url text default '',
  text_content text not null,
  word_count integer not null,
  created_at timestamptz not null default now()
);
alter table public.sources enable row level security;
-- Sengaja tidak membuat policy SELECT/INSERT untuk anon atau authenticated.
-- Service Role (hanya di server) dapat mengakses; jangan taruh key di browser.
create index if not exists sources_created_at_idx on public.sources(created_at desc);
