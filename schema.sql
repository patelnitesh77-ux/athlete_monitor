-- Athlete Monitoring Pilot — Supabase Postgres schema
-- Run once in Supabase: SQL Editor -> New query -> paste -> Run.

create extension if not exists pgcrypto;

-- ---------- People ----------
create table if not exists athletes (
    id            uuid primary key default gen_random_uuid(),
    name          text not null,
    sport         text not null check (sport in ('wrestling','archery')),
    weight_category text,                       -- wrestlers
    access_token  text unique not null default encode(gen_random_bytes(16),'hex'),
    active        boolean not null default true,
    created_at    timestamptz not null default now()
);

create table if not exists staff_users (
    id            uuid primary key default gen_random_uuid(),
    username      text unique not null,
    display_name  text not null,
    role          text not null check (role in ('admin','coach','physio')),
    -- pbkdf2 fields, managed by the app (lib/auth.py)
    pw_salt       text not null,
    pw_hash       text not null,
    active        boolean not null default true,
    created_at    timestamptz not null default now()
);

-- ---------- Athlete self-report ----------
create table if not exists wellness_entries (
    id            uuid primary key default gen_random_uuid(),
    athlete_id    uuid not null references athletes(id) on delete cascade,
    entry_date    date not null,
    sleep_quality smallint not null check (sleep_quality between 1 and 5),
    sleep_hours   numeric(3,1) not null check (sleep_hours between 0 and 14),
    fatigue       smallint not null check (fatigue between 1 and 5),
    soreness      smallint not null check (soreness between 1 and 5),
    stress        smallint not null check (stress between 1 and 5),
    mood          smallint not null check (mood between 1 and 5),
    hydration     smallint not null check (hydration between 1 and 5),
    body_weight_kg numeric(5,2),                -- wrestlers mainly; optional
    pain_flag     boolean not null default false,
    pain_location text,
    pain_type     text,
    pain_days     smallint,
    created_at    timestamptz not null default now(),
    unique (athlete_id, entry_date)             -- one form per day; resubmit = update
);

-- ---------- Load ----------
create table if not exists training_sessions (
    id            uuid primary key default gen_random_uuid(),
    athlete_id    uuid not null references athletes(id) on delete cascade,
    session_date  date not null,
    session_type  text not null check (session_type in ('field','gym','rehab')),
    duration_min  numeric(5,1) not null check (duration_min > 0),
    rpe           numeric(3,1) not null check (rpe between 0 and 10),
    load_au       numeric(8,1) generated always as (duration_min * rpe) stored,
    arrows        integer check (arrows >= 0), -- archery shot count for this session
    notes         text,
    source        text not null default 'coach' check (source in ('athlete','coach','physio')),
    created_by    text,                         -- username or 'athlete-link'
    created_at    timestamptz not null default now()
);

create table if not exists gym_exercises (
    id            uuid primary key default gen_random_uuid(),
    session_id    uuid not null references training_sessions(id) on delete cascade,
    exercise      text not null,
    sets          smallint not null check (sets > 0),
    reps          smallint not null check (reps > 0),
    weight_kg     numeric(6,2) not null check (weight_kg >= 0),
    position      smallint not null default 1
);

-- ---------- Medical (physio/admin only in app) ----------
create table if not exists injuries (
    id            uuid primary key default gen_random_uuid(),
    athlete_id    uuid not null references athletes(id) on delete cascade,
    onset_date    date not null,
    body_region   text not null,
    side          text check (side in ('left','right','bilateral','n/a')),
    injury_type   text check (injury_type in ('muscle','tendon','ligament','joint','bone','other')),
    mechanism     text check (mechanism in ('training','competition','gym','non-sport','unknown')),
    severity      text,                         -- physio free choice / expected timeloss
    diagnosis_notes text,                       -- PHYSIO-ONLY content
    status        text not null default 'open' check (status in ('open','closed')),
    created_at    timestamptz not null default now()
);

create table if not exists rehab_phases (
    id            uuid primary key default gen_random_uuid(),
    injury_id     uuid not null references injuries(id) on delete cascade,
    phase         text not null check (phase in
                    ('Acute','Rehab','Reconditioning','Modified Training','Full RTP')),
    start_date    date not null,
    notes         text
);

create table if not exists rehab_sessions (
    id            uuid primary key default gen_random_uuid(),
    injury_id     uuid not null references injuries(id) on delete cascade,
    session_date  date not null,
    notes         text,
    -- optional matching training_sessions row (type='rehab') so load counts
    training_session_id uuid references training_sessions(id) on delete set null,
    created_at    timestamptz not null default now()
);

-- Coach-visible availability; restrictions text is written FOR coaches by physio
create table if not exists availability (
    athlete_id    uuid primary key references athletes(id) on delete cascade,
    status        text not null default 'Full'
                  check (status in ('Full','Modified','Rehab only','Out')),
    restrictions  text,                         -- do's & don'ts, coach-visible
    updated_by    text,
    updated_at    timestamptz not null default now()
);

create index if not exists idx_wellness_athlete_date on wellness_entries (athlete_id, entry_date);
create index if not exists idx_sessions_athlete_date on training_sessions (athlete_id, session_date);
create index if not exists idx_injuries_athlete on injuries (athlete_id, status);

-- ---------- Default staff logins (CHANGE PASSWORDS after first login) ----------
-- Passwords below are 'changeme123' hashed with pbkdf2 (salt 'pilotsalt') —
-- generated by lib/auth.py:hash_password('changeme123', 'pilotsalt').
insert into staff_users (username, display_name, role, pw_salt, pw_hash) values
 ('yogi',   'Yogi (Admin)',  'admin',  'pilotsalt', 'f97ee7b5151406eed4075562ab285b7846c9044bf8169c11ee8f67a775a2378e'),
 ('coach1', 'Head Coach',    'coach',  'pilotsalt', 'f97ee7b5151406eed4075562ab285b7846c9044bf8169c11ee8f67a775a2378e'),
 ('physio1','Lead Physio',   'physio', 'pilotsalt', 'f97ee7b5151406eed4075562ab285b7846c9044bf8169c11ee8f67a775a2378e')
on conflict (username) do nothing;
-- NOTE: run seed of real hash via app's "Reset password" (admin panel) or
-- regenerate with: python -c "from lib.auth import hash_password; print(hash_password('yourpass','pilotsalt'))"
