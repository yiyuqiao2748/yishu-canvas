-- Team cloud MVP schema for Supabase.
-- Run this in Supabase SQL Editor before enabling the online team mode.

create extension if not exists "pgcrypto";

create table if not exists public.teams (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) > 0),
  owner_id uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.team_members (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null,
  email text not null default '',
  role text not null check (role in ('owner', 'admin', 'member')),
  created_at timestamptz not null default now(),
  unique (team_id, user_id)
);

create table if not exists public.invitations (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  email text not null,
  role text not null check (role in ('owner', 'admin', 'member')),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'revoked')),
  invited_by uuid not null,
  created_at timestamptz not null default now(),
  accepted_at timestamptz,
  unique (team_id, email, status)
);

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  name text not null check (char_length(trim(name)) > 0),
  description text not null default '',
  created_by uuid not null,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.canvases (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  project_id uuid not null references public.projects(id) on delete cascade,
  title text not null default 'Untitled canvas',
  data jsonb not null default '{}'::jsonb,
  version integer not null default 1,
  created_by uuid not null,
  updated_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.canvas_versions (
  id uuid primary key default gen_random_uuid(),
  canvas_id uuid not null references public.canvases(id) on delete cascade,
  version integer not null,
  data jsonb not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  unique (canvas_id, version)
);

create table if not exists public.assets (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  project_id uuid references public.projects(id) on delete set null,
  canvas_id uuid references public.canvases(id) on delete set null,
  kind text not null default 'image',
  name text not null,
  storage_provider text not null default 'r2',
  storage_key text not null,
  public_url text not null,
  thumbnail_url text not null default '',
  thumbnail_storage_key text not null default '',
  mime_type text not null default '',
  byte_size bigint not null default 0,
  width integer,
  height integer,
  created_by uuid not null,
  created_at timestamptz not null default now()
);

create table if not exists public.api_providers (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  provider_id text not null,
  label text not null,
  encrypted_config jsonb not null default '{}'::jsonb,
  created_by uuid not null,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (team_id, provider_id)
);

create table if not exists public.generation_logs (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  project_id uuid references public.projects(id) on delete set null,
  canvas_id uuid references public.canvases(id) on delete set null,
  user_id uuid not null,
  provider_id text not null default '',
  model text not null default '',
  status text not null default 'pending',
  request_summary jsonb not null default '{}'::jsonb,
  result_summary jsonb not null default '{}'::jsonb,
  error text not null default '',
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists idx_team_members_user_id on public.team_members(user_id);
create index if not exists idx_projects_team_id on public.projects(team_id);
create index if not exists idx_canvases_project_id on public.canvases(project_id);
create index if not exists idx_assets_team_id on public.assets(team_id);
create index if not exists idx_generation_logs_team_id on public.generation_logs(team_id);

alter table public.assets add column if not exists thumbnail_url text not null default '';
alter table public.assets add column if not exists thumbnail_storage_key text not null default '';
alter table public.api_providers add column if not exists updated_by uuid;

alter table public.teams enable row level security;
alter table public.team_members enable row level security;
alter table public.invitations enable row level security;
alter table public.projects enable row level security;
alter table public.canvases enable row level security;
alter table public.canvas_versions enable row level security;
alter table public.assets enable row level security;
alter table public.api_providers enable row level security;
alter table public.generation_logs enable row level security;

-- The FastAPI backend uses SUPABASE_SERVICE_ROLE_KEY for server-side access.
-- Client-side access should go through FastAPI endpoints, not direct table writes.
