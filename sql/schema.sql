-- Clan Manager Bot schema

create table if not exists manager_application_scores (
    id bigserial primary key,
    application_id bigint not null,
    user_id bigint not null,
    username text not null default '',
    score int not null,
    grade text not null,
    verdict text not null,
    reasons jsonb not null default '[]'::jsonb,
    risks jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique(application_id)
);

create table if not exists manager_event_state (
    event_id bigint primary key,
    last_reminded_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists manager_user_strikes (
    user_id bigint primary key,
    warnings_count int not null default 0,
    muted_until timestamptz,
    is_banned bool not null default false,
    updated_at timestamptz not null default now()
);

create table if not exists manager_moderation_actions (
    id bigserial primary key,
    user_id bigint not null,
    actor_id bigint not null,
    action text not null,
    reason text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists manager_chat_metrics_daily (
    day date not null,
    user_id bigint not null,
    username text not null default '',
    messages_count int not null default 0,
    helpful_answers int not null default 0,
    toxicity_flags int not null default 0,
    active_minutes int not null default 0,
    primary key (day, user_id)
);

create table if not exists manager_message_log (
    id bigserial primary key,
    source text not null default 'live',
    source_message_id bigint,
    chat_id bigint not null,
    user_id bigint not null,
    username text not null default '',
    text text not null default '',
    is_newbie bool not null default false,
    created_at timestamptz not null default now(),
    unique(source, source_message_id)
);

alter table manager_message_log add column if not exists source text not null default 'live';
alter table manager_message_log add column if not exists source_message_id bigint;
alter table manager_message_log add column if not exists is_newbie bool not null default false;

create index if not exists idx_manager_message_log_created_at on manager_message_log(created_at);
create index if not exists idx_manager_message_log_user_created_at on manager_message_log(user_id, created_at);
create unique index if not exists idx_manager_message_log_source_message on manager_message_log(source, source_message_id);
