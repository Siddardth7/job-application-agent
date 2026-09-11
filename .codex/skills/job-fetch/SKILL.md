---
name: job-fetch
description: Run or diagnose Stage 1 job discovery for the Fortify workspace, including US and curated international passes, deduplication, and scoped technician-role handling.
---

# Job Fetch

Read `AGENTS.md`, `DAILY_RUN.md`, `profile.md`, `company_intel.md`, and `learning_log.md`. Use current
`tools/fetch_jobs.py`. Run passes 1-4 unless Sid narrows scope. Preserve deduplication and write
`.pipeline/fetched.{json,md}`. Include quality/process/CMM technicians; exclude pure machinists,
operators, and assemblers. Never score, tailor, log, apply, or send. Report source failures and paid
source cost before expanding spend.
