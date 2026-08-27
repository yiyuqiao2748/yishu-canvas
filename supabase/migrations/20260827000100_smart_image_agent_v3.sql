-- Smart Canvas Image Agent v3 additive migration.
-- Apply after smart_image_agent_v2.sql. Existing v2 sessions, plans and runs remain intact.

create table if not exists public.smart_image_agent_policy_versions (
  id text primary key,
  models jsonb not null default '{}'::jsonb,
  capability_flags jsonb not null default '{}'::jsonb,
  planner_prompt_version text not null default '',
  created_at timestamptz not null default now(),
  retired_at timestamptz
);

insert into public.smart_image_agent_policy_versions (id, models, capability_flags, planner_prompt_version)
values (
  'v3-initial',
  '{"gpt-image-2":{"provider_id":"custom-api","quality":"standard","unit_points":6},"nano-banana-2":{"provider_id":"custom-api","quality":"standard","unit_points":12},"nano-banana-pro":{"provider_id":"custom-api","quality":"pro","unit_points":18},"gpt-image-2-vip":{"provider_id":"custom-api","quality":"vip","unit_points":20}}'::jsonb,
  '{"generate_image":true,"edit_image":true,"compose_images":true,"create_variants":true,"expand_image":true,"generate_image_set":true,"upload_reference":true,"add_asset_reference":true,"save_generated_result":true,"focus_result":true,"fit_all":true,"zoom_in":true,"zoom_out":true,"reset_zoom":true,"arrange_selection":true}'::jsonb,
  'v3-initial'
)
on conflict (id) do nothing;

create table if not exists public.smart_image_agent_executions (
  id uuid primary key default gen_random_uuid(),
  plan_id uuid not null unique references public.smart_image_agent_plans(id) on delete restrict,
  session_id uuid not null references public.smart_image_agent_sessions(id) on delete cascade,
  user_id uuid not null,
  team_id uuid references public.teams(id) on delete cascade,
  project_id text,
  canvas_id text not null,
  original_intent text not null default '',
  context jsonb not null default '{}'::jsonb,
  protocol_version text not null default '1',
  policy_version text not null references public.smart_image_agent_policy_versions(id),
  status text not null default 'awaiting_confirmation' check (status in ('awaiting_confirmation', 'queued', 'running', 'succeeded', 'failed', 'cancelled')),
  approval_key uuid not null unique,
  approved_idempotency_key uuid unique,
  run_ids jsonb not null default '[]'::jsonb,
  artifact_run_ids jsonb not null default '[]'::jsonb,
  billing_intent jsonb not null default '{}'::jsonb,
  next_sequence integer not null default 1 check (next_sequence > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  approved_at timestamptz,
  completed_at timestamptz
);

create table if not exists public.smart_image_agent_events (
  id uuid primary key default gen_random_uuid(),
  execution_id uuid not null references public.smart_image_agent_executions(id) on delete cascade,
  user_id uuid not null,
  protocol_version text not null default '1',
  sequence integer not null check (sequence > 0),
  type text not null check (type in ('context.ready', 'plan.proposed', 'plan.updated', 'approval.requested', 'approval.decided', 'tool.started', 'tool.progressed', 'tool.completed', 'tool.failed', 'tool.cancelled', 'artifact.created', 'execution.completed')),
  occurred_at timestamptz not null default now(),
  payload jsonb not null default '{}'::jsonb,
  unique (execution_id, sequence)
);

create table if not exists public.smart_image_agent_feedback (
  id uuid primary key default gen_random_uuid(),
  execution_id uuid not null references public.smart_image_agent_executions(id) on delete cascade,
  user_id uuid not null,
  kind text not null check (kind in ('adopted', 'plan_edited', 'dismissed', 'cancelled', 'retried', 'rated', 'continued', 'failed')),
  rating integer check (rating between 1 and 5),
  reason text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_smart_image_agent_executions_user_canvas on public.smart_image_agent_executions(user_id, canvas_id, updated_at desc);
create index if not exists idx_smart_image_agent_events_execution_sequence on public.smart_image_agent_events(execution_id, sequence asc);
create index if not exists idx_smart_image_agent_feedback_execution_time on public.smart_image_agent_feedback(execution_id, created_at desc);

create or replace function public.smart_image_agent_v3_approve_execution(
  p_execution_id uuid,
  p_user_id uuid,
  p_idempotency_key uuid
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_execution public.smart_image_agent_executions%rowtype;
  v_plan public.smart_image_agent_plans%rowtype;
  v_run_ids jsonb;
  v_now timestamptz := now();
  v_sequence integer;
begin
  select * into v_execution
  from public.smart_image_agent_executions
  where id = p_execution_id and user_id = p_user_id
  for update;

  if not found then
    raise exception 'Image Agent v3 execution not found' using errcode = 'P0002';
  end if;
  if v_execution.approval_key <> p_idempotency_key then
    raise exception 'Invalid Smart Image Agent v3 approval key' using errcode = '22023';
  end if;
  if v_execution.approved_idempotency_key is not null then
    if v_execution.approved_idempotency_key = p_idempotency_key then
      return to_jsonb(v_execution);
    end if;
    raise exception 'Smart Image Agent v3 execution was already approved' using errcode = '22023';
  end if;
  if v_execution.status <> 'awaiting_confirmation' then
    raise exception 'Smart Image Agent v3 execution is not awaiting confirmation' using errcode = '22023';
  end if;

  select * into v_plan
  from public.smart_image_agent_plans
  where id = v_execution.plan_id and user_id = p_user_id
  for update;
  if not found or v_plan.status <> 'awaiting_confirmation' then
    raise exception 'Image Agent plan is not awaiting confirmation' using errcode = '22023';
  end if;

  insert into public.smart_image_agent_runs (
    id, plan_id, session_id, user_id, team_id, canvas_id, sequence, attempt, status,
    progress_stage, provider_id, model, result, error, created_at, updated_at
  )
  select
    gen_random_uuid(), v_plan.id, v_plan.session_id, v_plan.user_id, v_plan.team_id, v_plan.canvas_id,
    series.sequence, 1, 'queued', 'queued', v_plan.provider_id, v_plan.model, '{}'::jsonb, '', v_now, v_now
  from generate_series(1, v_plan.count) as series(sequence)
  on conflict (plan_id, sequence) do nothing;

  select coalesce(jsonb_agg(id order by sequence), '[]'::jsonb) into v_run_ids
  from public.smart_image_agent_runs
  where plan_id = v_plan.id and user_id = p_user_id;

  update public.smart_image_agent_plans
  set status = 'queued', confirmed_at = v_now, updated_at = v_now
  where id = v_plan.id;
  update public.smart_image_agent_sessions
  set updated_at = v_now, last_activity_at = v_now
  where id = v_plan.session_id and user_id = p_user_id;

  v_sequence := v_execution.next_sequence;
  insert into public.smart_image_agent_events (execution_id, user_id, protocol_version, sequence, type, occurred_at, payload)
  values (
    v_execution.id, p_user_id, v_execution.protocol_version, v_sequence, 'approval.decided', v_now,
    jsonb_build_object('decision', 'approved', 'run_ids', v_run_ids)
  );
  insert into public.smart_image_agent_events (execution_id, user_id, protocol_version, sequence, type, occurred_at, payload)
  values (
    v_execution.id, p_user_id, v_execution.protocol_version, v_sequence + 1, 'tool.started', v_now,
    jsonb_build_object('capability_id', v_plan.action, 'dispatch', 'smart_canvas_bridge', 'run_ids', v_run_ids)
  );

  update public.smart_image_agent_executions
  set
    status = 'queued',
    approved_idempotency_key = p_idempotency_key,
    run_ids = v_run_ids,
    billing_intent = jsonb_build_object(
      'id', gen_random_uuid()::text,
      'status', 'pending_provider_charge',
      'estimated_points', v_plan.estimated_points,
      'model', v_plan.model,
      'run_ids', v_run_ids
    ),
    next_sequence = v_sequence + 2,
    approved_at = v_now,
    updated_at = v_now
  where id = v_execution.id
  returning * into v_execution;

  return to_jsonb(v_execution);
end;
$$;

alter table public.smart_image_agent_policy_versions enable row level security;
alter table public.smart_image_agent_executions enable row level security;
alter table public.smart_image_agent_events enable row level security;
alter table public.smart_image_agent_feedback enable row level security;

grant all on table public.smart_image_agent_policy_versions to service_role;
grant all on table public.smart_image_agent_executions to service_role;
grant all on table public.smart_image_agent_events to service_role;
grant all on table public.smart_image_agent_feedback to service_role;
grant execute on function public.smart_image_agent_v3_approve_execution(uuid, uuid, uuid) to service_role;
