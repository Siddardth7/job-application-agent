# 🚀 Job Application Agent

An autonomous, multi-agent AI job search, screening, and resume customization cockpit. Built to operate seamlessly with **Google Antigravity**, **Claude Code**, **OpenAI Codex**, or as a standalone CLI pipeline.

Designed to eliminate tedious manual job hunting through intelligent 2-track sourcing, strict Gate 0 eligibility checks (ITAR, citizenship, visa sponsorship), truth-grounded LaTeX resume tailoring, strict 1-page PDF validation, and automated networking contact discovery.

---

## 🏗️ Architecture & Pipeline Flow

The framework divides job applications into a 4-stage deterministic pipeline with human-in-the-loop gates:

```mermaid
flowchart LR
    A[Step 1: Fetch\nATS + LinkedIn] --> B[Step 2: Gate 0 & Score\nITAR / Fit 0-100]
    B --> C{🧑 GATE A\nReview Shortlist}
    C -->|Approved Roles| D[Step 3: Customise & Verify\nLaTeX -> 1-Page PDF]
    D --> E[Step 4: Contact Link & Log\nTracker & Supabase]
    E --> F[🧑 GATE B\nDirect Apply & Network]
```

### 1. Sourcing & Discovery (`fetcher` / `tools/fetch_jobs.py`)
- **Direct ATS Scraper**: High-performance, zero-token scans across 44+ direct ATS boards (Greenhouse, Lever, Workday, SmartRecruiters, Ashby, etc.) via vendored providers in `tools/lib/providers/`.
- **Apify LinkedIn Scraper**: Optional automated targeted queries for specific target companies and roles with configurable spend caps.
- **Deduplication Ledger**: Automatically skips previously evaluated jobs tracked in `seen_jobs.csv`.

### 2. Hard Gating & Fit Scoring (`ranker` / `tools/gate_and_score.py`)
- **Gate 0 (Eligibility Gating)**: Verbatim regex screening for ITAR restrictions, security clearances, U.S. citizenship requirements, and explicit "no sponsorship" disclaimers. Fails immediately to `VISA RISK (SKIP)` with the exact quoted snippet.
- **5-Axis Fit Scoring (0–100)**:
  - **Sponsorship Odds (30 pts)**: Cross-referenced against the embedded USCIS H-1B sponsor database (`data/uscis_h1b_lookup.json`).
  - **Role & Technical Fit (30 pts)**: Domain keyword density and qualification alignment.
  - **Seniority Fit (20 pts)**: Title and experience range matching.
  - **Domain Priority (10 pts)**: Priority alignment with wishlist domains.
  - **Logistics & Integrity (10 pts)**: Location, recency, and verified employer status.
- **Human Gate A**: You review the ranked shortlist (`.pipeline/ranked.md`) and select approved roles.

### 3. Truth-Grounded Customization (`customiser` / `tools/customise_resume.py`)
- **Truth-Only Customization**: All claims, bullet points, skills, and metrics are strictly grounded in your candidate database (`data/candidate_resume_database.json`). Never invents employers, credentials, or fake metrics.
- **Dynamic Semantic Reordering**: Surfaces the most JD-relevant skills, experience bullet points, and project case studies.
- **Strict Verification (`tools/verify_pdf.py`)**: Compiles via `pdflatex`, enforces strict 1-page limits, verifies ASCII date formatting, and inspects the extractable text layer for clean ATS parsing (no replacement glyphs or unescaped characters).
- **Directory Hierarchy**:
  - `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/Apply/`: Holds final verified PDFs ready for submission.
  - `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/Archive/`: LaTeX source files, compilation logs, and build artifacts.

### 4. Application Logging & Contact Discovery (`tools/log_and_refresh.py`)
- **1-Click Recruiter & Team-Lead Links**: Generates instant LinkedIn people-search URLs for hiring managers and recruiters per role.
- **Application Tracker**: Syncs to an interactive HTML tracker (`job_tracker.html`), optional Supabase database, or exportable Excel sheets (`networking_sheet.py`).

---

## ⚡ Quickstart

```bash
git clone https://github.com/Siddardth7/job-application-agent.git my-job-search
cd my-job-search
rm -rf .git && git init          # start your own private history

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Then drop your resume and LinkedIn export into `documents/` and run, in Claude Code:

```
/setup
```

`/setup` reads your documents (or interviews you), and writes your search profile, scoring
rubric, resume truth-source, and master LaTeX template. **Everything it writes is
gitignored.** Full instructions, prerequisites, and troubleshooting: **[SETUP.md](SETUP.md)**.

> **Until `/setup` runs**, the pipeline falls back to `config/search_profile.example.json` —
> the template author's targets and keywords. It runs, but it scores every posting against
> the wrong candidate. Run setup first.

### Making it yours

Everything profile-specific lives in `config/search_profile.json`: the titles you search
for, the keywords that earn skill-fit points, your priority domains and anchor companies,
the geographies you block, and which eligibility gates apply to you. `/setup` writes it;
edit it by hand any time, or re-run `/setup --section search`.

The single highest-leverage answer in setup is **work authorization**. If you need
sponsorship, the visa gates and the 30-point sponsorship axis stay on. If you're a citizen
or permanent resident, they come off and those points redistribute — leaving them on would
silently discard most of your real market.

---

## 🗄️ Supabase Backend & Interactive Tracker Artifact

This framework includes an interactive dual-tab dashboard (`job_tracker.html` and `job_tracker.artifact.html`) backed by Supabase PostgreSQL:

- **Interactive Dashboard**:
  - **Applications View**: Track application status (`applied`, `interviewing`, `offer`, `rejected`), match scores (0–100), job requisition IDs, direct links, and follow-up deadlines.
  - **Networking View**: Automated 1-click recruiter and team-lead LinkedIn outreach links, contact personas (`RECRUITER`, `SENIOR_MANAGER`), and touchpoint tracking.
  - **Metrics Bar**: Visual conversion rates, total pipeline counts, and overdue reminders.
- **Database Schema**: Full PostgreSQL definitions in [`supabase/schema.sql`](supabase/schema.sql) with custom ENUMs (`app_status_t`, `lane_t`, `outreach_status_t`), automatic `updated_at` triggers, RLS policies, and performance indexes.
- **Live Sync & Hydration**:
  - `tools/log_and_refresh.py` automatically POSTs approved roles and recruiter contacts to Supabase.
  - `./refresh.sh --fetch` pulls live database state via REST and rebuilds the HTML artifact.
  - In Claude Artifacts or Cowork, the page dynamically hydrates directly from Supabase.
  - In offline mode, `./refresh.sh` builds the dashboard from local `tracker_data.json`.

## 🖥️ Running the Pipeline

### Option A: Using the CLI Runner

```bash
# Run the interactive daily flow (Fetch -> Score -> Gate A -> Customize -> Log)
./tools/daily_run.sh

# Run individual stages independently:
./tools/daily_run.sh fetch        # Stage 1: Fetch jobs
./tools/daily_run.sh score        # Stage 2: Filter Gate 0 and score matches
./tools/daily_run.sh customize    # Stage 3: Customize approved shortlist
./tools/daily_run.sh sync         # Stage 4: Sync to tracker and export links
```

### Option B: Using AI Agents (Antigravity / Claude Code / Codex)

This repository includes native sub-agent definitions:
- **Google Antigravity**: Configured via `AGENTS.md` and workspace rules.
- **Claude Code**: Run commands directly in Claude Code:
  - `/setup`: One-time onboarding — builds your profile from your documents.
  - `/apply-run`: Orchestrates the entire daily pipeline.
  - `/fetch`: Runs Stage 1 discovery.
  - `/rank`: Runs Stage 2 scoring.
  - `/customise`: Runs Stage 3 resume generation.
  - `/find-contacts`: Discovers networking targets.
  - `/interview`: Builds a full interview prep manual for a tracked role.
  - `/reset`: Clears personal data back to templates.
- **OpenAI Codex**: Configured via `.codex/agents/*.toml`.

---

## 📁 Repository Structure

```
job-application-agent/
├── .claude/                  # Claude Code subagents & slash commands
├── SETUP.md                  # Full setup + troubleshooting guide
├── config/
│   └── search_profile.example.json  # Search/scoring config — /setup writes your own
├── documents/                # Drop your resume & LinkedIn export here for /setup
├── playbook/                 # Scoring rubric & customization rule templates
├── .codex/                   # OpenAI Codex agent configurations
├── AGENTS.md                 # Orchestration rules & Antigravity configuration
├── DAILY_RUN.md              # Operational SOP handbook
├── data/
│   ├── candidate_resume_database.template.json  # Master profile schema
│   ├── candidate_resume_database.json           # Your active candidate inventory
│   └── uscis_h1b_lookup.json                    # H-1B sponsor database (Gate 0)
├── profile.template.md       # Becomes your profile.md at setup
├── Resume/
│   └── Final_Resumes/
│       └── Resume_NewStrategy_Master.tex        # Master LaTeX template
├── tools/
│   ├── lib/                  # 44+ ATS scraping providers & trust engines
│   ├── ats_scan.mjs          # Zero-token direct ATS board scanner
│   ├── fetch_jobs.py         # Multi-pass job fetcher (ATS + Apify)
│   ├── gate_and_score.py     # Hard ITAR/visa gating & 0-100 rubric scoring
│   ├── customise_resume.py   # Truth-grounded LaTeX resume tailor
│   ├── verify_pdf.py         # LaTeX compiler & 1-page ATS PDF validator
│   ├── log_and_refresh.py    # Tracker updater & contact link generator
│   └── daily_run.sh          # All-in-one daily runner script
├── supabase/                 # Supabase PostgreSQL schema, seed, and docs
│   ├── schema.sql            # Table definitions, ENUMs, triggers, and RLS
│   ├── seed.sql              # Initial sample data
│   └── README.md             # Complete Supabase setup guide
├── job_tracker.html          # Interactive dual-tab UI dashboard
├── tracker_data.template.json# Sample application and contact data
├── networking_sheet.py       # Excel / Supabase networking contact manager
├── refresh.py                # Dashboard & tracker artifact builder
├── refresh.sh                # One-click dashboard rebuilder
├── requirements.txt          # Python dependencies
└── .env.example              # Environment variables template
```

---

## 🛡️ Core Rules & Ethics

1. **Human in the Loop**: The AI prepares resumes, inspects job criteria, and generates outreach links. You review every application and make the final submission.
2. **Strict Truthfulness**: Never hallucinate experiences or invent tools. Customization reorders and emphasizes existing verified qualifications to match JD language.
3. **No Spray-and-Pray**: Capped at a maximum of 2 roles per company per day to preserve candidate credibility and prevent ATS spam filters.

---

## 📄 License
MIT License. Open source and free to customize.
