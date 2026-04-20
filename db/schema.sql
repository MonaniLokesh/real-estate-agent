-- EstateAgent AI — Supabase / Postgres schema (Phase 1 MVP)
-- Refactored for shared WhatsApp + Telegram lead storage.

create extension if not exists "uuid-ossp";
create extension if not exists vector;

create table if not exists public.leads (
  id uuid primary key default uuid_generate_v4(),
  channel text not null default 'whatsapp',
  contact_id text,
  phone text,
  chat_id text,
  display_name text,
  lead_info jsonb not null default '{}'::jsonb,
  summary text,
  human_handoff_requested boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.leads add column if not exists channel text not null default 'whatsapp';
alter table public.leads add column if not exists contact_id text;
alter table public.leads add column if not exists phone text;
alter table public.leads add column if not exists chat_id text;
alter table public.leads add column if not exists display_name text;
alter table public.leads add column if not exists lead_info jsonb not null default '{}'::jsonb;
alter table public.leads add column if not exists summary text;
alter table public.leads add column if not exists human_handoff_requested boolean not null default false;
alter table public.leads add column if not exists created_at timestamptz not null default now();
alter table public.leads add column if not exists updated_at timestamptz not null default now();
alter table public.leads alter column phone drop not null;

update public.leads
set contact_id = coalesce(contact_id, phone)
where contact_id is null and phone is not null;

update public.leads
set contact_id = id::text
where contact_id is null;

alter table public.leads alter column contact_id set not null;

create unique index if not exists leads_channel_contact_idx
  on public.leads (channel, contact_id);

create index if not exists leads_phone_idx on public.leads (phone);
create index if not exists leads_chat_id_idx on public.leads (chat_id);

create table if not exists public.properties (
  id uuid primary key default uuid_generate_v4(),
  title text not null,
  description text,
  price_inr numeric,
  location text,
  bhk int,
  possession text,
  metadata jsonb not null default '{}'::jsonb,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists properties_location_idx on public.properties (location);
create index if not exists properties_bhk_idx on public.properties (bhk);
create index if not exists properties_price_idx on public.properties (price_inr);

create index if not exists properties_embedding_ivfflat
  on public.properties using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create table if not exists public.agent_logs (
  id uuid primary key default uuid_generate_v4(),
  phone text,
  channel text,
  contact_id text,
  step text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.agent_logs add column if not exists phone text;
alter table public.agent_logs add column if not exists channel text;
alter table public.agent_logs add column if not exists contact_id text;
alter table public.agent_logs add column if not exists step text;
alter table public.agent_logs add column if not exists payload jsonb not null default '{}'::jsonb;
alter table public.agent_logs add column if not exists created_at timestamptz not null default now();
alter table public.agent_logs alter column step set not null;

create index if not exists agent_logs_contact_created_idx
  on public.agent_logs (channel, contact_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists leads_updated_at on public.leads;
create trigger leads_updated_at
  before update on public.leads
  for each row execute function public.set_updated_at();

drop trigger if exists properties_updated_at on public.properties;
create trigger properties_updated_at
  before update on public.properties
  for each row execute function public.set_updated_at();

alter table public.leads enable row level security;
alter table public.properties enable row level security;
alter table public.agent_logs enable row level security;
