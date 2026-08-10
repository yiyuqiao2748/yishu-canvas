create extension if not exists "pgcrypto";

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

create index if not exists idx_api_usage_logs_user_time on public.api_usage_logs(user_id, created_at desc);
create index if not exists idx_api_usage_logs_team_time on public.api_usage_logs(team_id, created_at desc);
create index if not exists idx_api_usage_logs_model_time on public.api_usage_logs(provider_id, model, created_at desc);
create index if not exists idx_point_ledger_user_time on public.point_ledger(user_id, created_at desc);
create index if not exists idx_user_sessions_user_seen on public.user_sessions(user_id, last_seen_at desc);
create index if not exists idx_user_sessions_team_seen on public.user_sessions(team_id, last_seen_at desc);

alter table public.api_usage_logs enable row level security;
alter table public.user_points enable row level security;
alter table public.point_ledger enable row level security;
alter table public.user_sessions enable row level security;

grant all on table public.api_usage_logs to service_role;
grant all on table public.user_points to service_role;
grant all on table public.point_ledger to service_role;
grant all on table public.user_sessions to service_role;
