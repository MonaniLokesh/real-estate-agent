-- EstateAgent AI — minimal Supabase / Postgres schema (Phase 1 MVP)
-- Apply in Supabase SQL Editor or: supabase db push (if using Supabase CLI)

create extension if not exists "uuid-ossp";
create extension if not exists vector;

-- Leads: one row per WhatsApp phone; long-term summary + structured fields
create table if not exists public.leads (
  id uuid primary key default uuid_generate_v4(),
  phone text not null unique,
  lead_info jsonb not null default '{}'::jsonb,
  summary text,
  human_handoff_requested boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists leads_phone_idx on public.leads (phone);

-- Properties: factual inventory + embedding for semantic search (pgvector)
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

-- IVFFLAT index (lists=100); rebuild after bulk load if needed
create index if not exists properties_embedding_ivfflat
  on public.properties using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- Full trace: decisions, tool calls, errors (backend uses service role)
create table if not exists public.agent_logs (
  id uuid primary key default uuid_generate_v4(),
  phone text,
  step text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists agent_logs_phone_created_idx on public.agent_logs (phone, created_at desc);

-- Touch updated_at on leads
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

-- RLS: deny public access; backend uses service_role (bypasses RLS)
alter table public.leads enable row level security;
alter table public.properties enable row level security;
alter table public.agent_logs enable row level security;

-- No policies for anon/authenticated = no direct client access via anon key
