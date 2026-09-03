# DAILY RUN — Job-Search Orchestrator (Fortify 45-Day Sprint)

## ★ ACTIVE DAILY FLOW (Hardened Dual-Track Setup)

The daily run executes four unified stages with two human gates:

```
Step 1: FETCH (ATS + Apify) ──▶ Step 2: GATE 0 & SCORE ──▶ 🧑 GATE A (Shortlist Approval)
                                                                 │
🧑 GATE B (Sid Applies & Networks) ◀── Step 4: SUPABASE & REBUILD ◀── Step 3: CUSTOMIZE & PDF VERIFY
```

### Stage 1: Fetch (`python3 tools/fetch_jobs.py --pass=N`)
- **Direct ATS Scan**: Scans public Greenhouse, Workday, SmartRecruiters, and Lever boards (free, zero-token) for target companies (AST SpaceMobile, Supernal, Archer Aviation, Beta Technologies, Lucid Motors, Re:Build Manufacturing, BorgWarner, Robert Bosch, etc.).
- **Apify LinkedIn Scraper**: Runs targeted queries for anchor targets (Joby Aviation, AST SpaceMobile, Micron) and aerospace/composites manufacturing & quality roles with $\le \$0.50$ spend cap and compact field extraction.
  - **Pass 1** — anchors + aerospace/composites (US). **Pass 2** — semiconductor & EV sponsors (US). **Pass 3** — broad quality/process **+ quality/process/CMM technician** roles (US). **Pass 4** — **curated international (Europe + Australia)**, engineer *and* technician roles; these bypass the US-only geo gate.
- **Scope (new strategy):** Search area is **global** — US plus Europe, Australia, and beyond (run `--pass=4`). **Quality & process technician roles are in scope** (they convert into engineering); pure machinist/operator/assembler roles stay dropped by the ranker's technician gate.
- **Dedup**: Gated against `seen_jobs.csv` ledger.
- **Handoff**: `.pipeline/fetched.json` & `.pipeline/fetched.md`.

### Stage 2: Gate 0 & Scoring (`python3 tools/gate_and_score.py`)
- **Gate 0 (Eligibility Gate)**: Verbatim check for ITAR, export control, U.S. Citizenship, Security Clearance, or explicit "no sponsorship". Fails immediately to `VISA RISK (SKIP)` with the quoted snippet.
- **Fit Scoring (0–100)**: Evaluates aerospace/composites domain, quality toolkit (PFMEA, SPC, 8D, AS9102 FAIR, MRB/NCR, GD&T/CMM), and sponsorship odds.
- **Routing**:
  - `Track 2: Curated Target` (Joby, AST, Micron, or top aerospace fit $\ge 75$)
  - `Track 1: Broad-Fit Apply` (Score $\ge 50$, strong sponsor)
  - `Drop` (Score $< 50$ or VISA RISK)
- **Handoff**: `.pipeline/ranked.md` & `.pipeline/ranked.json`.
- 🧑 **GATE A**: Sid reviews the scored shortlist and approves rows to customize.

### Stage 3: Customize & Verify (`python3 tools/customise_resume.py`)
- Full Drafter-Reviewer Agent architecture grounded against `data/candidate_resume_database.json`.
- Dynamically tailors `Skills`, semantically reframes `Experience` bullets using JD-aligned action verbs & priority keywords, and retains all 3 project case studies.
- Compiles `.tex` and executes `tools/verify_pdf.py` (syntax check, clean compilation, strict 1-page PDF).
- **Directory Hierarchy**:
  - Saved under `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/` (e.g. `September/2026-09-01/`).
  - `Apply/`: Holds **strictly the approved tailored PDFs** for direct user submission (zero clutter).
  - `Archive/`: Holds all LaTeX `.tex` sources (under `src/`), compilation `.log`, `.aux`, `.out` files, and intermediate build assets.
- **Handoff**: `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/Apply/` and `.pipeline/tailored.md`.

### Stage 4: Supabase Sync & Artifact Rebuild (`python3 tools/log_and_refresh.py`)
- Inserts application records to Supabase `applications` table (two-track: **T1 Broad-Fit / T2 Curated Target** — T3 is retired).
- **Persists the 1-click recruiter + team-lead LinkedIn people-search links to the Supabase `contacts` table** — the source-of-truth "contacts place" — keyed to each new `job_id` (recruiter → persona `RECRUITER`, team lead → persona `SENIOR_MANAGER`). This happens automatically here; no separate step needed. See **Source Contacts Place** below.
- Appends new URLs to `seen_jobs.csv`.
- Executes `./refresh.sh --fetch` (MANDATORY: pulls live database state to rebuild `job_tracker.html` and deploy Cowork `index.html`).
- Exports high-score networking sheet via `python3 networking_sheet.py export --date <today>` if qualifying roles exist.
- 🧑 **GATE B**: Sid receives the verified PDFs and apply links to submit directly.

---

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
1. **Claude/Antigravity never applies, never logs in, and never sends outreach.** Sid applies to every job.
2. **Never fabricate experience, metrics, or employers.**
3. **Always rebuild with `./refresh.sh --fetch`.**
4. **Never bypass Gate 0 ITAR/Visa screening.**
