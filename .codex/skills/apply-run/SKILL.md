---
name: apply-run
description: Run the Fortify daily job-application preparation workflow from discovery through verified resumes and Supabase rebuild, with mandatory human gates and no application submission or outreach sending.
---

# Apply Run

Use `/Users/sid/Documents/Claude/Projects/Job_Applications`. Read `AGENTS.md`, then `DAILY_RUN.md`,
before every run. They override `.claude/**`, `ANTIGRAVITY_APPLY_RUN.md`, `README.md`, `archive/**`,
`outputs/**`, and historical `daily_run/**`.

1. Run Stage 1 through `fetcher` or `tools/fetch_jobs.py` passes 1-4. Require
   `.pipeline/fetched.{json,md}`.
2. Run Stage 2 through `ranker` or `tools/gate_and_score.py`. Enforce Gate 0 and at most two roles per
   employer per day. Require `.pipeline/ranked.{json,md}`.
3. Present the shortlist and stop at **Gate A**. Do not customize until Sid approves specific rows.
4. Run Stage 3 through `customiser` or `tools/customise_resume.py` only for approved rows. Verify every
   PDF with `tools/verify_pdf.py`. Require `.pipeline/tailored.{json,md}` and the monthly/date layout.
5. Run Stage 4 with `tools/log_and_refresh.py` only after Stage 3 succeeds. Require
   `./refresh.sh --fetch`.
6. Stop at **Gate B** with exact PDF paths and job links. Sid submits and sends all outreach.

Never submit or send. Gate visa/ITAR/export/citizenship/clearance/no-sponsor failures with evidence.
Ground every resume fact. `Apply/` contains only verified one-page ATS PDFs. Supabase `applications` is
the application record and Supabase `contacts` in project `chsrkysjongzgdbwqhlu` is the only contact
store. Search globally; include scoped quality/process/CMM technicians; drop pure operators,
machinists, and assemblers. Never silently continue after a required stage or rebuild fails.

Standalone stages: `$job-fetch`, `$job-rank`, `$resume-customise`, `$job-contacts`.
