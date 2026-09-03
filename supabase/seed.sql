-- ==============================================================================
-- Job Application Agent — Supabase Seed Data
-- ==============================================================================
-- Run this script in your Supabase SQL Editor after running schema.sql.
-- ==============================================================================

insert into applications
  (job_id, company, role, location, lane, score, track, resume, job_url, req_id,
   found_date, fed_date, referral_state, status, applied_date, follow_up_by, top_contact, legit_flags, notes)
values
  ('ja-0901-01', 'Acme Aerospace', 'Manufacturing Quality Engineer', 'San Jose, CA', 'direct-apply', 92, 'T1',
   'resume_AcmeAerospace_MfgQualityEngineer', 'https://example.com/jobs/acme-qe-1', 'REQ-10101',
   current_date, current_date, 'none', 'applied', current_date, current_date + 7,
   'Jane Recruiter (Technical Recruiter)', null, 'Direct applied with tailored 1-page resume.'),

  ('ja-0901-02', 'Orbit Composites', 'Process Engineer', 'Austin, TX', 'direct-apply', 85, 'T2',
   'resume_OrbitComposites_ProcessEngineer', 'https://example.com/jobs/orbit-pe-2', 'REQ-20202',
   current_date, current_date, 'none', 'shortlisted', null, current_date + 4,
   'John Manager (Manufacturing Engineering Lead)', null, 'Approved at Gate A review.')
on conflict (job_id) do update set
  company = excluded.company,
  role = excluded.role,
  score = excluded.score,
  status = excluded.status;

insert into contacts
  (name, title, company, application_id, persona, focus_area, hook_signal,
   channel, linkedin_url, email, is_alum, outreach_status, last_touch, next_action, notes)
values
  ('Jane Recruiter', 'Senior Technical Recruiter', 'Acme Aerospace', 'ja-0901-01',
   'RECRUITER', 'Engineering & Operations', 'Hiring lead for manufacturing quality team',
   'linkedin', 'https://linkedin.com/in/example-recruiter', 'janerecruiter@example.com', false,
   'sent', current_date, 'Follow up if no reply within 7 days', '1-click outreach generated from pipeline.'),

  ('John Manager', 'Manufacturing Engineering Lead', 'Orbit Composites', 'ja-0901-02',
   'SENIOR_MANAGER', 'Process Engineering & Composites', 'Team lead for composite manufacturing line',
   'linkedin', 'https://linkedin.com/in/example-manager', null, false,
   'sourced', null, 'Send connection note referencing composite tooling project', 'Found via 1-click team lead search.');
