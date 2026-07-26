create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  username text not null unique check (username ~ '^[a-z0-9][a-z0-9_-]{2,31}$'),
  display_name text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_user_profiles_username on public.user_profiles(username);

alter table public.user_profiles enable row level security;

grant all on table public.user_profiles to service_role;
