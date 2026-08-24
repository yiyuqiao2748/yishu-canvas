-- Smart Canvas Image Agent v2 production migration.
-- This is intentionally identical to the Agent-specific section in
-- team_cloud_schema.sql and is safe to apply once in the Supabase SQL Editor.

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
  count integer not null default 1 check (count between 1 and 8),
  quality text not null default 'standard' check (quality in ('standard', 'pro')),
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

create index if not exists idx_smart_image_agent_sessions_user_canvas on public.smart_image_agent_sessions(user_id, canvas_id, updated_at desc);
create index if not exists idx_smart_image_agent_messages_session_time on public.smart_image_agent_messages(session_id, created_at asc);
create index if not exists idx_smart_image_agent_plans_session_time on public.smart_image_agent_plans(session_id, created_at desc);
create index if not exists idx_smart_image_agent_runs_user_canvas on public.smart_image_agent_runs(user_id, canvas_id, created_at desc);
create index if not exists idx_smart_image_agent_runs_status on public.smart_image_agent_runs(status, created_at asc);

alter table public.smart_image_agent_sessions add column if not exists title text not null default '';
alter table public.smart_image_agent_sessions add column if not exists last_activity_at timestamptz not null default now();
alter table public.smart_image_agent_sessions add column if not exists archived_at timestamptz;
alter table public.smart_image_agent_runs add column if not exists progress_stage text not null default 'queued';

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

alter table public.smart_image_agent_sessions enable row level security;
alter table public.smart_image_agent_messages enable row level security;
alter table public.smart_image_agent_plans enable row level security;
alter table public.smart_image_agent_runs enable row level security;

-- The application writes these tables through FastAPI using SUPABASE_SERVICE_ROLE_KEY.
grant all on table public.smart_image_agent_sessions to service_role;
grant all on table public.smart_image_agent_messages to service_role;
grant all on table public.smart_image_agent_plans to service_role;
grant all on table public.smart_image_agent_runs to service_role;
