---
description: Daily job-search run (core-4 sweep, niche fetch, triage, review, log)
---
Run today's job-search loop exactly as `playbook/P1_workflow.md` says. Arguments: $ARGUMENTS (e.g. "niche day", "core only", a folder of pasted JDs).

1. Run `python3 tools/log_apps.py review` (yesterday's tracker Status + Review), read its learning_log.md entry and TODO.md, and propose rule changes from repeated skip reasons. Decide the day type: core-4 only, or core-4 plus niche (every other day).
2. Gather Pass 6 (Indeed / ZipRecruiter / Dice connectors, query set in config search.connectors, raw responses to .pipeline/connectors/, then `python3 tools/connectors.py build`), then fetch (passes 1-6), then triage. Show the pass table (status, raw, kept, spend) and anything that arrived without a JD.
3. Read the JDs for the top triage rows. Present them for Sid's row-by-row Keep/Drop. STOP and wait; never bulk-approve.
4. For Keeps, pick a lane base from Resume/lanes/ (never Resume_Master.tex), tailor and verify per P3.
5. Never apply, message or log in. Sid does that.
6. Run `python3 tools/tailor.py .pipeline/keeps_candidates.json`, verify every PDF, then `python3 tools/log_apps.py queue`. Sid applies from job_tracker.html and sets Status + Review on every row; tomorrow's step 1 reads it.
