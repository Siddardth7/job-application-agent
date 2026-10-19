---
description: Daily job-search run (core-4 sweep, niche fetch, triage, review, log)
---
Run today's job-search loop exactly as `playbook/P1_workflow.md` says. Arguments: $ARGUMENTS (e.g. "niche day", "core only", a folder of pasted JDs).

1. Read learning_log.md and TODO.md. Decide the day type: core-4 only, or core-4 plus niche (every other day).
2. Fetch, then triage. Show the pass table (status, raw, kept, spend) and anything that arrived without a JD.
3. Read the JDs for the top triage rows. Present them for Sid's row-by-row Keep/Drop. STOP and wait; never bulk-approve.
4. For Keeps, tailor and verify resumes once the niche master exists (P3).
5. Never apply, message or log in. Sid does that.
6. When Sid says he is done applying, ask which Keeps he applied to, write .pipeline/applied.json, run tools/log_apps.py add, and give him the path of the daily file.
7. Ask the end-of-run question and log the answer to learning_log.md.
