# DAILY RUN — Job-Search Orchestrator

## Active daily flow

The daily run executes four unified stages with two human gates:

```
Step 1: FETCH (ATS + Apify) ──▶ Step 2: GATE 0 & SCORE ──▶ 🧑 GATE A (Shortlist Approval)
                                                                 │
🧑 GATE B (you Applies & Networks) ◀── Step 4: SUPABASE & REBUILD ◀── Step 3: CUSTOMIZE & PDF VERIFY
```

### Stage 1: Fetch (`python3 tools/fetch_jobs.py`)
Every batch is **today only** — nothing is carried over from a previous run, and the fetcher never
writes `seen_jobs.csv`. Six passes, each with its own window and Apify cap
(`search.pass_days`, `search.apify_pass_caps` in `config/search_profile.json`):

| Pass | Source | Window | What it searches |
|---|---|---|---|
| 0 | Your hand-found postings | — | `--jds=<folder>` of Markdown JDs and/or `--url=<LinkedIn job URL>`; the agent asks first |
| 1 | Company career sites (free) | 3 days | `tools/ats_scan.mjs` over `tools/portals.json`; Greenhouse, Workday and SmartRecruiters descriptions are fetched per job; portals in `known_non_sponsors` are skipped and flagged |
| 2 | LinkedIn, target companies | 3 days | `target_anchors` × `role_titles` |
| 3 | LinkedIn, all domains | 24 hours | every domain's `company_keywords` × `role_titles`, plus the bare titles |
| 4 | LinkedIn, non-full-time | 24 hours | contract / temporary / internship / co-op, plus `adjacent_titles` (technicians) |
| 5 | LinkedIn, international | 3 days | `role_titles` + `adjacent_titles` per `intl_locations`, no level filter; bypasses the country block |

- **Filter order:** unusable → reposted (text or >14 days old) → outside the US (word-bounded, US
  states and regions never blocked; international rows exempt) → already in the seen ledger
  (requisition id, URL, job id, company+title) → duplicate in this run → same company+title folded
  into one multi-city row.
- **Handoffs:** `.pipeline/fetched.json` (the record), `.pipeline/fetched.md` (rendered, with the
  per-pass table and the "worth a job description" list), `.pipeline/fetch_report.json`
  (status / raw / kept / cap / reason per pass, drop counts, skipped portals).
- **Blank descriptions:** a career-site row the scanner could not enrich stays in the batch flagged
  `needs_jd`; the ranker cannot score it. The fetcher lists the best 10 for the user to fetch by hand.
- Offline checks: `python3 tools/fetch_jobs.py --self-test`, `--dry-run` (fixture, no network).

### Stage 2: Gate 0 & Scoring (`python3 tools/gate_and_score.py`)
One formula, out of 100, every knob in `config/search_profile.json` → `scoring` (defaults in the
script): **Coverage 40** (truthful ATS keyword coverage from `data/keyword_taxonomy.json`) +
**Sponsorship 25** (stated in the JD, else H-1B filings, else your `known_sponsors`; silence is a
neutral 8) + **Domain 15** (order of your `domains` list) + **Role fit 15** (your titles = core,
years required vs `candidate.max_years`) + **Logistics 5** (fresh, direct employer).

- **Gate 0** first, with the quoted snippet: `known_non_sponsors`, no-sponsorship / export-control /
  citizenship / clearance language (all skipped when `candidate.needs_sponsorship` is false),
  `title_drop_cues`, non-English text (unless in `candidate.languages`), residency-only, seen ledger.
  Export-control boilerplate and "may require a license" wording are cautions shown at Gate A, not drops.
- **Buckets:** `Apply` (top 15 confident rows ≥ 50, max 2 per company) · `Reserve` (held by the caps) ·
  `Unverified` (above 50 but the keyword check was thin) · `Needs JD` (no text) · `Drop` (gated,
  off-discipline, below 50). Nothing is dropped silently; every bucket is on the page.
- **Ledger:** every row is appended to `seen_jobs.csv` with its bucket as status. **Carry-over:** yesterday's
  Apply/Reserve rows not yet applied are re-scored today, marked ↩︎, once (`daily_run/ranked_<date>.json`).
- **Handoffs:** `.pipeline/ranked.json` (the record), `.pipeline/ranked.md` (Gate A page),
  `.pipeline/ranked_summary.json` (decisions only, what the ranker skill reads).
- 🧑 **GATE A**: you review the Apply table, promote Reserve/Unverified rows by number, and name the rows to tailor.

### Stage 3: Customise & Verify (the `customiser` subagent — `.claude/agents/customiser.md`)
- One resume per Gate-A-approved row, tailored **inline, one at a time**, from the single master
  `Resume/Final_Resumes/Resume_Master.tex` (`\ifcase\ResumeType` 0–5 picks the track's Skills block).
  JD text comes from `.pipeline/ranked.json` (`description`); there are no per-job JD files.
- Rules: `playbook/P1_03_resume_customization_rules.md`. Tailoring reorders Skills, bullets and
  projects and rewords for emphasis; it never renames an entry, adds a method, or invents a fact.
  **The master template wins over the playbook inventory on names, links and dates.**
- Every output passes the agent's hard self-check gate (diff vs the resolved track base via
  `tools/resolve_track.py`, unique md5, no company name, employer headers unchanged, LaTeX-safety,
  `pdflatex` → exactly 1 page, 0 bad boxes, no adjacent/gap keyword in a reworded bullet).
- **Output layout**: `Job_Applications_Resumes/<YYYY-MM-DD>/resume_{Company}_{ShortRole}.pdf`
  (what you submit) and `Job_Applications_Resumes/<YYYY-MM-DD>/src/*.tex`. No `.aux/.log/.out` kept.
- **Handoff**: `.pipeline/tailored.md` (job → resume map + 3-line change summaries + gate results).
  `.pipeline/tailored.json` (what Stage 4 reads) is an open contract — see `docs/audits/` item 1.

### Stage 4: Supabase Sync (`python3 tools/log_and_refresh.py`)
- Inserts application records to Supabase `applications` table (two-track: **T1 Broad-Fit / T2 Curated Target** — T3 is retired).
- **Persists the 1-click recruiter + team-lead LinkedIn people-search links to the Supabase `contacts` table** — the source-of-truth "contacts place" — keyed to each new `job_id` (recruiter → persona `RECRUITER`, team lead → persona `SENIOR_MANAGER`). This happens automatically here; no separate step needed. See **Source Contacts Place** below.
- Appends new URLs to `seen_jobs.csv`.
- Builds `.pipeline/tailored.json` itself from the customiser's `tailored.md` table + `ranked.json` (no stage writes it by hand).
- Runs `./refresh.sh --fetch`, which only syncs tracker drop-notes into `learning_log.md`.
- **There is no tracker deploy step.** The tracker is `job_tracker.html`, a standalone page you bookmark
  (generated once by `python3 refresh.py`, or by `/setup`). It reads `applications` + `contacts` from
  Supabase over REST **every time it is opened** and writes status / note / outreach edits straight back,
  so any run from any agent (Claude Code, Codex, Antigravity, a shell) that writes rows to Supabase is
  already visible on reload. No artifact, no upload, no rebuild. The key is pasted once into the page
  and lives in the browser, never in the file.
- Exports high-score networking sheet via `python3 networking_sheet.py export --date <today>` if qualifying roles exist.
- 🧑 **GATE B**: you receives the verified PDFs and apply links to submit directly.

---

## Running from more than one tool (Claude Code · Codex · Antigravity)

**One spec, three wrappers.** Edit only `.agents/skills/*/SKILL.md`, `.claude/agents/*.md` and
`.claude/commands/*.md`. `python3 tools/sync_specs.py` regenerates `.claude/skills/`, `.codex/agents/*.toml`,
`.codex/skills/*/SKILL.md` and `.agent/workflows/*.md` (Antigravity) from them; `tools/check.sh` fails
if any wrapper is stale. Nothing in the specs is machine-specific (the networking-agent path is
`NETWORKING_AGENT_DIR` in `.env`).

**Supabase is the shared truth, not the checkout.** Three things cross machines and tools:
`applications` (what was logged), `seen_jobs` (every posting any run ranked, with its bucket — so a run
on another laptop or from another tool skips what this one dropped), and the tracker page reads both.
`seen_jobs.csv` is only the local mirror; `python3 tools/lib/ledger.py --push` backfills it once.
`job_id`s are allocated against the database: a collision with a concurrent run moves to the next id
and says so, it never silently drops a row.

**Alternating tools day to day** (Claude today, Codex tomorrow, any machine): supported as-is.

**Running two tools at the same time:** use one checkout per tool — `git worktree add ../job-apps-codex`
— because `.pipeline/`, `daily_run/<date>.md`, `Job_Applications_Resumes/<date>/` and `seen_jobs.csv` are
per-checkout scratch and would overwrite each other. The database side (job ids, seen ledger, tracker)
is already safe for concurrent runs.

## Source Contacts Place (where recruiter / team-lead links live)

There is **one** contacts store: the Supabase **`contacts`** table in project `chsrkysjongzgdbwqhlu` (DB "linkedin-memory"). Do **not** invent a new location — this is where every recruiter and team-lead link must land, and it is what the tracker's Networking tab reads.

- **Auto path (default):** Stage 4 (`tools/log_and_refresh.py`) already upserts recruiter + team-lead people-search links for every newly logged application. Antigravity does not need to do anything extra.
- **Manual / ad-hoc path:** to push links from any pipeline JSON that carries `recruiter_url` / `peer_url` **and** a `job_id`:
  ```
  python3 networking_sheet.py add <path/to.json>          # e.g. an applications export
  python3 networking_sheet.py add <path/to.json> --dry-run # preview, writes nothing
  ```
  It upserts on `(name, application_id)` so re-runs never duplicate, then run `./refresh.sh --fetch` to rebuild.
- **Schema (columns used):** `name, title, company, application_id, persona, linkedin_url, channel, hook_signal, outreach_status, notes, last_touch`. Valid `persona`: `RECRUITER`, `SENIOR_MANAGER` (team lead / hiring lead), `PEER_ENGINEER`, `ALUMNI`. New link rows start `outreach_status='sourced'`.
- **Note:** `.pipeline/tailored.json` rows do **not** carry `job_id` yet (it is assigned at Stage 4), so persist contacts *through Stage 4*, not directly from the tailored handoff.

---

## Hard Guardrails
1. **Claude/Antigravity never applies, never logs in, and never sends outreach.** you applies to every job.
2. **Never fabricate experience, metrics, or employers.**
3. **Always rebuild with `./refresh.sh --fetch`.**
4. **Never bypass Gate 0 ITAR/Visa screening.**
