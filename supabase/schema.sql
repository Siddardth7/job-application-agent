-- ==============================================================================
-- Job Application Agent — Supabase PostgreSQL Schema
-- ==============================================================================
-- Run this script in your Supabase SQL Editor (https://app.supabase.com/project/_/sql)
-- It creates all custom enums, tables, indexes, triggers, and RLS policies.
-- ==============================================================================

-- 1. ENUM TYPES
--------------------------------------------------------------------------------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'lane_t') then
    -- 'referral' is legacy: that lane was retired 2026-08-13. Kept so historical rows
    -- still load; new rows use 'direct-apply', 'staffing', or 'outreach'.
    create type lane_t as enum ('referral', 'direct-apply', 'staffing', 'outreach');
  end if;
  if not exists (select 1 from pg_type where typname = 'referral_state_t') then
    create type referral_state_t as enum ('searching', 'reached', 'conversation', 'referral_asked', 'referred', 'direct-apply', 'none');
  end if;
  if not exists (select 1 from pg_type where typname = 'app_status_t') then
    -- 'referral-pending' is legacy (retired referral lane); kept for historical rows.
    create type app_status_t as enum ('referral-pending', 'pending', 'applied', 'dropped', 'expired', 'shortlisted', 'interviewing', 'offer', 'rejected');
  end if;
  -- NOTE: `track` is deliberately NOT an enum. Track labels are yours to define in
  -- config/search_profile.json; a fixed enum would force one taxonomy on every user.
  if not exists (select 1 from pg_type where typname = 'contact_channel_t') then
    create type contact_channel_t as enum ('linkedin', 'inmail', 'email');
  end if;
  if not exists (select 1 from pg_type where typname = 'outreach_status_t') then
    create type outreach_status_t as enum (
      'sourced', 'drafted', 'sent', 'not_accepted', 'accepted', 'replied',
      'positive', 'meeting_scheduled', 'negative', 'referral_asked',
      'referral_secured', 'no_response', 'dropped'
    );
  end if;
end $$;

-- 2. APPLICATIONS TABLE
--------------------------------------------------------------------------------
create table if not exists applications (
  job_id          text primary key,                 -- Format: ja-MMDD-NN (e.g., ja-0901-01)
  company         text not null,
  role            text not null,
  location        text,
  lane            lane_t not null default 'direct-apply',
  score           int,                               -- 0-100 fit score from ranker
  track           text,                              -- your track label, free text (see config/search_profile.json)
  resume          text,                              -- Generated resume file name
  job_url         text,                              -- Link to the original posting
  req_id          text,                              -- Job requisition ID from employer
  found_date      date default current_date,
  fed_date        date,
  referral_state  referral_state_t default 'none',
  status          app_status_t not null default 'pending',
  applied_date    date,
  follow_up_by    date,
  top_contact     text,                              -- Key contact name summary
  legit_flags     text,                              -- Flags from trust/legitimacy validator
  notes           text,
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);

-- 3. CONTACTS TABLE
--------------------------------------------------------------------------------
create table if not exists contacts (
  id              bigserial primary key,
  name            text not null,
  title           text,
  company         text,
  application_id  text references applications(job_id) on delete set null,
  persona         text,                              -- RECRUITER, SENIOR_MANAGER, PEER, etc.
  focus_area      text,
  hook_signal     text,                              -- Contextual hook for connection note
  channel         contact_channel_t default 'linkedin',
  linkedin_url    text,
  email           text,
  is_alum         boolean default false,
  outreach_status outreach_status_t default 'sourced',
  last_touch      date,
  next_action     text,
  notes           text,
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);

-- 4. AUTOMATIC UPDATED_AT TIMESTAMP TRIGGER
--------------------------------------------------------------------------------
create or replace function touch_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_app_touch on applications;
create trigger trg_app_touch
  before update on applications
  for each row execute function touch_updated_at();

drop trigger if exists trg_ct_touch on contacts;
create trigger trg_ct_touch
  before update on contacts
  for each row execute function touch_updated_at();

-- 5. PERFORMANCE INDEXES
--------------------------------------------------------------------------------
create index if not exists idx_applications_lane_status on applications (lane, status);
create index if not exists idx_applications_found_date on applications (found_date desc);
create index if not exists idx_applications_follow_up_by on applications (follow_up_by);
create index if not exists idx_contacts_application_id on contacts (application_id);
create index if not exists idx_contacts_outreach_status on contacts (outreach_status);
create index if not exists idx_contacts_name_company on contacts (lower(name), lower(company));

-- 6. ROW LEVEL SECURITY (RLS) POLICIES
--------------------------------------------------------------------------------
-- Enables table access via the Supabase REST API (used by tools/log_and_refresh.py and refresh.py)
alter table applications enable row level security;
alter table contacts enable row level security;

-- Allow read/write for authenticated users (or anon key if public job hunt tracker)
drop policy if exists "Enable read access for all users" on applications;
create policy "Enable read access for all users" on applications
  for select using (true);

drop policy if exists "Enable insert/update for all users" on applications;
create policy "Enable insert/update for all users" on applications
  for all using (true) with check (true);

drop policy if exists "Enable read access for all users" on contacts;
create policy "Enable read access for all users" on contacts
  for select using (true);

drop policy if exists "Enable insert/update for all users" on contacts;
create policy "Enable insert/update for all users" on contacts
  for all using (true) with check (true);

-- 7. SEEN-JOB LEDGER (shared across machines and agent platforms)
--------------------------------------------------------------------------------
-- Every posting the ranker has scored, with its bucket as status, so a run on any
-- machine / from any tool skips what another already dropped or shortlisted.
-- tools/lib/ledger.py reads it on every run and upserts new rows after ranking;
-- seen_jobs.csv stays as the local mirror (`python3 tools/lib/ledger.py --push` backfills it).
create table if not exists seen_jobs (
  key         text primary key,   -- cleaned job_url, else the company|title|city fingerprint
  first_seen  date,
  market      text,
  company     text,
  title       text,
  city        text,
  job_url     text,
  fingerprint text,
  status      text,               -- surfaced | shortlisted | unscored | dropped | applied_pending
  req_id      text,
  updated_at  timestamptz default now()
);
create index if not exists idx_seen_jobs_fingerprint on seen_jobs (fingerprint);
create index if not exists idx_seen_jobs_status on seen_jobs (status);
alter table seen_jobs enable row level security;
drop policy if exists "seen_jobs all" on seen_jobs;
create policy "seen_jobs all" on seen_jobs for all using (true) with check (true);
