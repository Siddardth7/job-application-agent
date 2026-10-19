# Job Applications - niche sprint (from 2026-10-17)

Daily pipeline for Sid's job search: composites / materials & process roles at startups to mid-size companies, plus a daily sweep of AST, Joby, Micron and Tesla. The previous (Fortify) setup is archived in `archive/fortify_2026-10-17/` and at git tag `fortify-sprint-end-2026-10-16`.

## Read first
`playbook/P1_workflow.md` (the daily loop), `profile.md`, `TODO.md`, `learning_log.md`.

## Hard rules
1. **Never apply or message.** The agent fetches, triages, tailors resumes and logs. Sid applies, networks and sends everything. Never log in, fill forms or solve CAPTCHAs.
2. **Gate 0.** Drop on stated US-person / citizenship / clearance / ITAR-required / no-sponsorship wording, with the quoted snippet. "May require a license" is a caution.
3. **Sid chooses Keep/Drop on every row** after the JD is read. No bulk approvals, no "tailor the rest".
4. **Truth only** on resumes. Facts come from Sid and `Interview_Prep/2026-10-01_Tesla_Resume_LineByLine.md`. One page, no em dashes, ATS text layer verified with `tools/verify_pdf.py`.
5. **State.** Supabase `applications` (project chsrkysjongzgdbwqhlu, key in `.env`) is the tracker; `job_tracker.html` reads it live. `seen_jobs.csv` is the dedup ledger.
6. **Inline work.** Do the run in the main session; do not fan out parallel subagents.

## Layout
- `tools/` fetch_jobs.py (passes 0 to 5), ats_scan.mjs + lib/providers (career-site APIs), triage.py, log_apps.py, verify_pdf.py, check_usage.py, check.sh (all offline self-tests).
- `config/search_profile.json` (every knob), `tools/portals.json` (career-site feeds), `playbook/`, `outputs/<date>/applications_<date>.md`, `Job_Applications_Resumes/<date>/`.
- `Interview_Prep/`, `documents/` (source documents), `archive/`.

## Commands
`/run` the daily loop. `/outcome` log an interview, rejection or offer.
