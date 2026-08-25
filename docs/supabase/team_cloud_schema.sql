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

create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  username text not null unique check (username ~ '^[a-z0-9][a-z0-9_-]{2,31}$'),
  display_name text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.pending_user_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  email text not null unique,
  username text not null unique check (username ~ '^[a-z0-9][a-z0-9_-]{2,31}$'),
  display_name text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  verified_at timestamptz
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
  visibility text not null default 'team' check (visibility in ('private', 'team')),
  kind text not null default 'classic' check (kind in ('classic', 'smart')),
  node_count integer not null default 0 check (node_count >= 0),
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
  visibility text not null default 'team' check (visibility in ('private', 'team')),
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

create table if not exists public.api_usage_logs (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  project_id uuid references public.projects(id) on delete set null,
  canvas_id uuid references public.canvases(id) on delete set null,
  user_id uuid not null,
  operation_type text not null default 'image' check (operation_type in ('image', 'video', 'chat', 'upscale', 'workflow')),
  provider_id text not null default '',
  model text not null default '',
  status text not null default 'succeeded' check (status in ('pending', 'succeeded', 'failed')),
  points_charged integer not null default 0,
  provider_points_charged integer not null default 0,
  estimated_cost_cny numeric(12,4) not null default 0,
  request_count integer not null default 1,
  image_count integer not null default 0,
  video_count integer not null default 0,
  latency_ms integer not null default 0,
  request_summary jsonb not null default '{}'::jsonb,
  result_summary jsonb not null default '{}'::jsonb,
  error text not null default '',
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.user_points (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null,
  balance integer not null default 100,
  monthly_quota integer not null default 100,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (team_id, user_id)
);

create table if not exists public.point_ledger (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null,
  delta integer not null,
  reason text not null default '',
  source_log_id uuid references public.api_usage_logs(id) on delete set null,
  created_by uuid not null,
  note text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.user_sessions (
  id uuid primary key default gen_random_uuid(),
  session_id text not null,
  team_id uuid references public.teams(id) on delete cascade,
  user_id uuid not null,
  started_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  page text not null default '',
  user_agent_hash text not null default '',
  unique (session_id, user_id)
);

create table if not exists public.billing_prices (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  provider_id text not null default '',
  model text not null default '',
  operation_type text not null default 'image' check (operation_type in ('image', 'video', 'chat', 'upscale', 'workflow')),
  points_cost integer not null default 0,
  provider_points_cost integer not null default 0,
  enabled boolean not null default true,
  note text not null default '',
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (team_id, provider_id, model, operation_type)
);

create table if not exists public.provider_recharges (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  provider_id text not null default '',
  amount_cny numeric(12,4) not null default 0,
  provider_points_received integer not null default 0,
  app_points_received integer not null default 0,
  note text not null default '',
  recharged_at timestamptz not null default now(),
  created_by uuid,
  created_at timestamptz not null default now()
);

create table if not exists public.smart_image_agent_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  team_id uuid references public.teams(id) on delete cascade,
  project_id text,
  canvas_id text not null,
  title text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_activity_at timestamptz not null default now(),
  archived_at timestamptz
);

create table if not exists public.smart_image_agent_messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.smart_image_agent_sessions(id) on delete cascade,
  user_id uuid not null,
  canvas_id text not null,
  role text not null default 'user' check (role in ('user', 'assistant', 'system')),
  content text not null default '',
  context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.smart_image_agent_plans (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.smart_image_agent_sessions(id) on delete cascade,
  user_id uuid not null,
  team_id uuid references public.teams(id) on delete cascade,
  project_id text,
  canvas_id text not null,
  action text not null,
  message text not null default '',
  prompt text not null default '',
  "references" jsonb not null default '[]'::jsonb,
  source_node_ids jsonb not null default '[]'::jsonb,
  ratio text not null default 'auto',
  resolution text not null default '1k' check (resolution in ('1k', '2k', '4k')),
  count integer not null default 1 check (count between 1 and 8),
  quality text not null default 'standard' check (quality in ('standard', 'pro', 'vip')),
  provider_id text not null default 'custom-api',
  model text not null,
  fallback_used boolean not null default false,
  unit_points integer not null default 0,
  estimated_points integer not null default 0,
  status text not null default 'awaiting_confirmation' check (status in ('draft', 'awaiting_confirmation', 'queued', 'running', 'succeeded', 'failed', 'cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  confirmed_at timestamptz
);

create table if not exists public.smart_image_agent_runs (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null references public.smart_image_agent_plans(id) on delete cascade,
  session_id uuid not null references public.smart_image_agent_sessions(id) on delete cascade,
  user_id uuid not null,
  team_id uuid references public.teams(id) on delete cascade,
  canvas_id text not null,
  sequence integer not null default 1,
  attempt integer not null default 1,
  status text not null default 'queued' check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  provider_id text not null default 'custom-api',
  model text not null,
  result jsonb not null default '{}'::jsonb,
  error text not null default '',
  progress_stage text not null default 'queued',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  unique (plan_id, sequence)
);

create index if not exists idx_team_members_user_id on public.team_members(user_id);
create index if not exists idx_user_profiles_username on public.user_profiles(username);
create index if not exists idx_user_profiles_username_lower on public.user_profiles(lower(username));
create index if not exists idx_pending_user_profiles_email on public.pending_user_profiles(email);
create index if not exists idx_pending_user_profiles_username on public.pending_user_profiles(username);
create index if not exists idx_projects_team_id on public.projects(team_id);
create index if not exists idx_canvases_project_id on public.canvases(project_id);
create index if not exists idx_canvases_team_project_updated on public.canvases(team_id, project_id, updated_at desc);
create index if not exists idx_assets_team_id on public.assets(team_id);
create index if not exists idx_generation_logs_team_id on public.generation_logs(team_id);
create index if not exists idx_api_usage_logs_user_time on public.api_usage_logs(user_id, created_at desc);
create index if not exists idx_api_usage_logs_team_time on public.api_usage_logs(team_id, created_at desc);
create index if not exists idx_api_usage_logs_model_time on public.api_usage_logs(provider_id, model, created_at desc);
create index if not exists idx_point_ledger_user_time on public.point_ledger(user_id, created_at desc);
create index if not exists idx_user_sessions_user_seen on public.user_sessions(user_id, last_seen_at desc);
create index if not exists idx_user_sessions_team_seen on public.user_sessions(team_id, last_seen_at desc);
create index if not exists idx_billing_prices_team_model on public.billing_prices(team_id, provider_id, model, operation_type);
create index if not exists idx_provider_recharges_team_time on public.provider_recharges(team_id, recharged_at desc);
create index if not exists idx_smart_image_agent_sessions_user_canvas on public.smart_image_agent_sessions(user_id, canvas_id, updated_at desc);
create index if not exists idx_smart_image_agent_messages_session_time on public.smart_image_agent_messages(session_id, created_at asc);
create index if not exists idx_smart_image_agent_plans_session_time on public.smart_image_agent_plans(session_id, created_at desc);
create index if not exists idx_smart_image_agent_runs_user_canvas on public.smart_image_agent_runs(user_id, canvas_id, created_at desc);
create index if not exists idx_smart_image_agent_runs_status on public.smart_image_agent_runs(status, created_at asc);

alter table public.assets add column if not exists thumbnail_url text not null default '';
alter table public.smart_image_agent_sessions add column if not exists title text not null default '';
alter table public.smart_image_agent_sessions add column if not exists last_activity_at timestamptz not null default now();
alter table public.smart_image_agent_sessions add column if not exists archived_at timestamptz;
alter table public.smart_image_agent_runs add column if not exists progress_stage text not null default 'queued';
alter table public.assets add column if not exists thumbnail_storage_key text not null default '';
alter table public.api_providers add column if not exists updated_by uuid;
alter table public.api_usage_logs add column if not exists provider_points_charged integer not null default 0;
alter table public.api_usage_logs add column if not exists estimated_cost_cny numeric(12,4) not null default 0;
alter table public.canvases add column if not exists visibility text not null default 'team';
alter table public.canvases add column if not exists kind text not null default 'classic';
alter table public.canvases add column if not exists node_count integer not null default 0;
update public.canvases
set kind = case when lower(coalesce(data->>'kind', kind, 'classic')) = 'smart' then 'smart' else 'classic' end,
    node_count = case when jsonb_typeof(data->'nodes') = 'array' then jsonb_array_length(data->'nodes') else 0 end;
alter table public.canvases drop constraint if exists canvases_kind_check;
alter table public.canvases add constraint canvases_kind_check check (kind in ('classic', 'smart'));
alter table public.canvases drop constraint if exists canvases_node_count_check;
alter table public.canvases add constraint canvases_node_count_check check (node_count >= 0);
alter table public.smart_image_agent_plans add column if not exists resolution text not null default '1k';
alter table public.smart_image_agent_plans drop constraint if exists smart_image_agent_plans_resolution_check;
alter table public.smart_image_agent_plans add constraint smart_image_agent_plans_resolution_check check (resolution in ('1k', '2k', '4k'));
alter table public.smart_image_agent_plans drop constraint if exists smart_image_agent_plans_quality_check;
alter table public.smart_image_agent_plans add constraint smart_image_agent_plans_quality_check check (quality in ('standard', 'pro', 'vip'));
alter table public.assets add column if not exists visibility text not null default 'team';
create index if not exists idx_smart_image_agent_sessions_history on public.smart_image_agent_sessions(user_id, canvas_id, archived_at, last_activity_at desc);
with ranked_smart_image_agent_plans as (
  select id, row_number() over (partition by user_id, canvas_id order by created_at desc, id desc) as rank
  from public.smart_image_agent_plans
  where status = 'awaiting_confirmation'
)
update public.smart_image_agent_plans as plan
set status = 'cancelled', updated_at = now()
from ranked_smart_image_agent_plans as ranked
where plan.id = ranked.id and ranked.rank > 1;
create unique index if not exists idx_smart_image_agent_one_pending_plan
  on public.smart_image_agent_plans(user_id, canvas_id)
  where status = 'awaiting_confirmation';
alter table public.canvases drop constraint if exists canvases_visibility_check;
alter table public.canvases add constraint canvases_visibility_check check (visibility in ('private', 'team'));
alter table public.assets drop constraint if exists assets_visibility_check;
alter table public.assets add constraint assets_visibility_check check (visibility in ('private', 'team'));

alter table public.teams enable row level security;
alter table public.team_members enable row level security;
alter table public.user_profiles enable row level security;
alter table public.pending_user_profiles enable row level security;
alter table public.invitations enable row level security;
alter table public.projects enable row level security;
alter table public.canvases enable row level security;
alter table public.canvas_versions enable row level security;
alter table public.assets enable row level security;
alter table public.api_providers enable row level security;
alter table public.generation_logs enable row level security;
alter table public.api_usage_logs enable row level security;
alter table public.user_points enable row level security;
alter table public.point_ledger enable row level security;
alter table public.user_sessions enable row level security;
alter table public.billing_prices enable row level security;
alter table public.provider_recharges enable row level security;
alter table public.smart_image_agent_sessions enable row level security;
alter table public.smart_image_agent_messages enable row level security;
alter table public.smart_image_agent_plans enable row level security;
alter table public.smart_image_agent_runs enable row level security;

-- The FastAPI backend uses SUPABASE_SERVICE_ROLE_KEY for server-side access.
-- Client-side access should go through FastAPI endpoints, not direct table writes.
grant all on table public.user_profiles to service_role;
grant all on table public.pending_user_profiles to service_role;
grant all on table public.api_usage_logs to service_role;
grant all on table public.user_points to service_role;
grant all on table public.point_ledger to service_role;
grant all on table public.user_sessions to service_role;
grant all on table public.billing_prices to service_role;
grant all on table public.provider_recharges to service_role;
grant all on table public.smart_image_agent_sessions to service_role;
grant all on table public.smart_image_agent_messages to service_role;
grant all on table public.smart_image_agent_plans to service_role;
grant all on table public.smart_image_agent_runs to service_role;
