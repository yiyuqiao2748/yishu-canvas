-- Idempotent production migration for workspace summaries and Smart Image Agent resolution.

alter table public.canvases add column if not exists kind text not null default 'classic';
alter table public.canvases drop constraint if exists canvases_kind_check;
alter table public.canvases add constraint canvases_kind_check check (kind in ('classic', 'smart'));

alter table public.canvases add column if not exists node_count integer not null default 0;
alter table public.canvases drop constraint if exists canvases_node_count_check;
alter table public.canvases add constraint canvases_node_count_check check (node_count >= 0);

update public.canvases
set
  kind = case
    when lower(coalesce(data->>'kind', kind, 'classic')) = 'smart' then 'smart'
    else 'classic'
  end,
  node_count = case
    when jsonb_typeof(data->'nodes') = 'array' then jsonb_array_length(data->'nodes')
    else 0
  end;

create index if not exists idx_user_profiles_username_lower
  on public.user_profiles(lower(username));
create index if not exists idx_canvases_team_project_updated
  on public.canvases(team_id, project_id, updated_at desc);

alter table public.smart_image_agent_plans
  add column if not exists resolution text not null default '1k';
alter table public.smart_image_agent_plans
  drop constraint if exists smart_image_agent_plans_resolution_check;
alter table public.smart_image_agent_plans
  add constraint smart_image_agent_plans_resolution_check
  check (resolution in ('1k', '2k', '4k'));

alter table public.smart_image_agent_plans
  drop constraint if exists smart_image_agent_plans_quality_check;
alter table public.smart_image_agent_plans
  add constraint smart_image_agent_plans_quality_check
  check (quality in ('standard', 'pro', 'vip'));
