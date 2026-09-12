# 🗄️ Supabase Backend & Interactive Artifact Setup

This directory contains the database schema, seed data, and instructions for setting up the Supabase PostgreSQL backend that powers the Job Search Cockpit and interactive tracker artifact.

---

## 🌟 Why Supabase?

The Job Application Agent uses Supabase as a centralized cloud database of record. It enables:
1. **Multi-Device Sync**: Track applications from your laptop, mobile, or AI coding assistant (Google Antigravity, Claude Code, OpenAI Codex).
2. **Deterministic Logging**: Stage 4 (`tools/log_and_refresh.py`) auto-persists approved job applications and generates 1-click recruiter/manager LinkedIn links.
3. **Interactive Artifact Hydration**: The generated HTML dashboard (`job_tracker.html`) dynamically reads the latest live database state or falls back cleanly to offline snapshots.
4. **Zero-API Cost**: Works completely on Supabase's generous free tier.

---

## 🚀 Setup Guide (Takes ~3 minutes)

### Step 1: Create a Free Supabase Project
1. Go to [supabase.com](https://supabase.com) and create a free account (or log in).
2. Click **"New project"**.
3. Choose a name (e.g., `job-search-tracker`), a database password, and select your nearest region.
4. Wait ~1 minute for Supabase to provision your PostgreSQL database.

### Step 2: Run the Schema Migration
1. In your Supabase project dashboard, navigate to the **SQL Editor** tab (icon `>_` on the left sidebar).
2. Click **"New query"**.
3. Copy the entire contents of [`schema.sql`](./schema.sql) and paste it into the editor.
4. Click **"Run"** (or press `Ctrl+Enter` / `Cmd+Enter`).
   - This creates all necessary enums (`lane_t`, `app_status_t`, `outreach_status_t`), the `applications`, `contacts` and `seen_jobs` tables, triggers, indexes, and Row Level Security (RLS) policies.
   - **Already have a project from before 2026-09-12?** Run only section 7 of `schema.sql` (the `seen_jobs` ledger), then `python3 tools/lib/ledger.py --push` once to backfill it from your `seen_jobs.csv`.

### Step 3: Run Optional Seed Data
1. In the SQL Editor, open another query tab.
2. Copy and paste the contents of [`seed.sql`](./seed.sql).
3. Click **"Run"**.
   - This inserts a couple of sample applications and networking contacts so you can immediately see the dashboard rendered with data.

### Step 4: Configure Project Environment Variables
1. In Supabase, go to **Project Settings** (gear icon) -> **API**.
2. Copy:
   - **Project URL** (e.g., `https://abcdefghijklm.supabase.co`)
   - **anon / public key** or **service_role key** (under Project API keys)
3. In your local repository root, create or edit your `.env` file:
   ```bash
   cp .env.example .env
   ```
4. Set the keys in `.env`:
   ```env
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_KEY=your-service-role-or-anon-key
   ```

---

## 📊 Data Schema Reference

### `applications` Table
Primary ledger for all jobs tracked by the agent:

| Column | Type | Description |
| :--- | :--- | :--- |
| `job_id` | `text` (PK) | Unique ID in format `ja-MMDD-NN` (e.g. `ja-0901-01`) |
| `company` | `text` | Employer name |
| `role` | `text` | Position title |
| `location` | `text` | Job location |
| `lane` | `lane_t` | `direct-apply`, `staffing`, or `outreach` (`referral` is legacy, retired 2026-08-13) |
| `score` | `int` | 0–100 match score from `gate_and_score.py` |
| `track` | `text` | Your track label — free text, defined in `config/search_profile.json` |
| `resume` | `text` | Filename of the tailored PDF resume |
| `job_url` | `text` | Direct application URL |
| `req_id` | `text` | Employer job requisition number |
| `status` | `app_status_t`| `pending`, `applied`, `shortlisted`, `interviewing`, `offer`, `rejected`, `dropped` |
| `applied_date`| `date` | Date the application was submitted |
| `follow_up_by`| `date` | Target date to follow up on the application |
| `top_contact` | `text` | Highlighted key contact summary |
| `legit_flags` | `text` | Caution flags from legitimacy checks |
| `notes` | `text` | Running notes, referral leads, or interview details |

### `contacts` Table
Stores all hiring managers, recruiters, and alumni contacts:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `bigserial` (PK)| Auto-incrementing contact ID |
| `name` | `text` | Contact's full name |
| `title` | `text` | Job title (e.g. "Senior Technical Recruiter") |
| `company` | `text` | Associated company |
| `application_id` | `text` (FK) | References `applications(job_id)` |
| `persona` | `text` | `RECRUITER`, `SENIOR_MANAGER`, `PEER`, etc. |
| `hook_signal` | `text` | Connection angle / conversation starter |
| `channel` | `contact_channel_t`| `linkedin`, `inmail`, `email` |
| `linkedin_url`| `text` | LinkedIn profile or 1-click search URL |
| `email` | `text` | Email address (if known) |
| `is_alum` | `boolean` | Alumnus indicator |
| `outreach_status` | `outreach_status_t` | `sourced`, `drafted`, `sent`, `replied`, `meeting_scheduled`, etc. |
| `last_touch` | `date` | Date of last interaction |
| `next_action`| `text` | Recommended next outreach step |

---

## 🔄 How the Pipeline Interacts with Supabase

```
┌─────────────────────────────────────────────────────────────┐
│ tools/fetch_jobs.py -> tools/gate_and_score.py              │
│ (Discovers postings and generates 1-click LinkedIn searches)│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ tools/log_and_refresh.py (Stage 4)                          │
│ 1. POSTs approved records to Supabase `applications`        │
│ 2. POSTs generated recruiter & manager links to `contacts`  │
│ 3. Executes ./refresh.sh --fetch to rebuild the UI tracker  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ refresh.py / refresh.sh                                     │
│ 1. GETs latest records from Supabase REST API               │
│ 2. Compiles self-contained `job_tracker.html` dashboard     │
│ 3. Deploys live view for browser or Claude Artifacts       │
└─────────────────────────────────────────────────────────────┘
```

### The Tracker Page:
```bash
# Write job_tracker.html once, then bookmark it. It reads Supabase live on every open
# and writes edits straight back — no rebuild after runs, no artifact, no hosting.
python3 refresh.py

# Sync the tracker's drop-review notes into learning_log.md (the daily run does this):
./refresh.sh --fetch
```
The page asks for your Supabase key on first open and keeps it in the browser's
`localStorage`. The service_role key works as-is (it bypasses RLS). To use the
anon/publishable key instead, add policies granting `anon` select + update on
`applications` and `contacts`.

---

## 🎨 The Tracker Page (`job_tracker.html`)

A standalone page you bookmark. It reads the `applications` table live on every open and writes
status / note edits straight back — no rebuild, no artifact, no hosting.
- **Dashboard**: sourced / applied / shortlisted / interviews / rejected / overdue, distribution by
  status, lane and track, recently found.
- **Tracker**: a dense spreadsheet of every application (sticky header, row numbers, colored status
  cells, sort by any column, filter by status / lane / track / score / search). Each row expands to
  the posting link, resume, follow-up, a drop-review note, and the recruiter / team-lead LinkedIn
  searches generated from the company and role.
- Networking is **not** tracked in the page. The `contacts` table still receives the people-search
  links from Stage 4 for any other tooling that wants them.
