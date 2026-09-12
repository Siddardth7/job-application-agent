# Fortify 45-Day Sprint — Antigravity Workspace Rules & Orchestrator

## Overview
This workspace automates an agentic end-to-end job search pipeline across multiple sub-agents (Fetcher, Ranker, Customiser, Contact-Finder).
Candidate profile configuration lives in `data/candidate_resume_database.json` and `Resume/Final_Resumes/Resume_Master.tex`.

## First run: onboarding (required)
A fresh clone is not personalized. Run `/setup` (Claude Code) — or follow `.claude/commands/setup.md`
manually in Antigravity/Codex — before any pipeline stage. It reads the user's documents from
`documents/` and writes `config/search_profile.json`, `profile.md`,
`data/candidate_resume_database.json`, the two `playbook/` rule files, and the master `.tex`.

**`config/search_profile.json` is the file every stage actually executes on**: search titles,
skill-fit keywords, domain classification, blocked geographies, eligibility gate lists, and
anchor companies. Until it exists, `tools/lib/profile_config.py` falls back to
`config/search_profile.example.json` — the template author's profile — and every score is
computed against the wrong candidate. Never run a real pipeline on the example config.

After an interview is scheduled, `/interview` (see `.claude/commands/interview.md`) builds the
prep manual from the submitted resume plus the JD. `/reset` clears personal data back to templates.

## The Two-Track Architecture
1. **Track 1: High-Velocity Broad-Fit Lane (Daily Batch)**
   - Target: Strong-fit technical, process, and quality engineering roles at verified sponsors.
   - Sourcing via `fetch_subagent` / `tools/fetch_jobs.py` (Free direct ATS boards + optional LinkedIn scraper).
   - Gate 0: Verbatim ITAR / Visa Eligibility Gating.
   - Scoring & Base Selection: `rank_subagent` / `tools/gate_and_score.py`.
   - Customization & PDF Verification: the `customiser` subagent (`.claude/agents/customiser.md`), `pdflatex` + `tools/resolve_track.py`.
   - Logging & Tracker Rebuild: `tools/log_and_refresh.py` (optional Supabase sync + live `./refresh.sh --fetch`).
   - Candidate applies directly to all verified resumes.

2. **Track 2: Curated Target-Company Lane (High-Touch Apps/Week)**
   - Target: Anchored by top wishlist employers and high-scoring matches.
   - Tailoring: Line-by-line custom alignment, highlighting specific project case studies and verified metrics.
   - Research & Networking: Public evidence research and recruiter / team lead outreach.

## Hard Rules & Guardrails
1. **Never Apply or Send Messages:** The agent prepares resumes, pre-fills forms if requested, and logs applications. The candidate performs every application submission and sends all networking outreach.
2. **Gate 0 (Non-Negotiable Eligibility Gate):** Every posting is checked for ITAR, export control, U.S. Citizen only, security clearance, or explicit "no visa sponsorship". Failing roles are marked `VISA RISK (SKIP)` with the verbatim quoted snippet and dropped.
3. **Truth-Only Customization & Grounding Audit:** Start from `Resume/Final_Resumes/Resume_Master.tex`. Ground every claim, employer, metric, and degree in the candidate master inventory (`data/candidate_resume_database.json`). Never invent tools, employers, or metrics.
4. **Strict 1-Page & ATS Text-Layer Validation:** Every compiled resume must pass `tools/verify_pdf.py` (LaTeX syntax safety, clean compilation, exactly 1 page, clean extractable ATS text layer with no replacement glyphs, and single ASCII hyphen date ranges).
5. **Database of Record:** Optional Supabase `applications` table or local JSON tracker. Tracker rebuilds use `./refresh.sh`.
6. **Source Contacts Place:** All recruiter and team-lead links (and networking contacts) live in the `contacts` table or export sheet. Stage 4 (`tools/log_and_refresh.py`) auto-persists 1-click recruiter/team-lead people-search links per logged role (recruiter → `RECRUITER`, team lead → `SENIOR_MANAGER`). Ad-hoc: `python3 networking_sheet.py add <json>`. See DAILY_RUN.md → "Source Contacts Place".
7. **Search Scope (global + technicians):** The search area is worldwide — US plus Europe, Australia, and beyond (`fetch_jobs.py --pass=4` covers curated international). Quality & process **technician** roles are in scope (they convert into engineering); pure machinist / operator / assembler roles are dropped by the ranker's technician gate.
8. **Resume Storage:** `Job_Applications_Resumes/<YYYY-MM-DD>/resume_{Company}_{ShortRole}.pdf` (the files the candidate submits) with the LaTeX source in `Job_Applications_Resumes/<YYYY-MM-DD>/src/`. No build artifacts (`.aux/.log/.out`) are kept.
9. **Anti-Spraying Policy (Max 2 Roles per Company per Day):** In any daily shortlist batch, cap applications at a maximum of 2 roles per employer. When a high-match employer has multiple matching openings, select only the top 1–2 highest-scoring roles for that day's batch, holding remaining matches in reserve for subsequent runs. This prevents ATS spam flags and preserves candidate credibility.

## Subagents
- `fetch_subagent`: Automated discovery via ATS and Apify scraper -> `.pipeline/fetched.json` / `.pipeline/fetched.md`. Passes 1-3 are US (P3 now includes quality/process/CMM **technician** roles); **Pass 4 is curated international (Europe + Australia)** and bypasses the US-only geo gate.
- `rank_subagent`: Gate 0 eligibility gating and 0-100 fit scoring -> `.pipeline/ranked.json` / `.pipeline/ranked.md` (Gate A Shortlist).
- `customiser`: tailors `Resume_Master.tex` per approved row against the JD text in `ranked.json`, runs the hard self-check gate, compiles to `Job_Applications_Resumes/<YYYY-MM-DD>/` -> `.pipeline/tailored.md` (Gate B Handoff).

