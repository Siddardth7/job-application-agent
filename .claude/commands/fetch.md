---
description: Run just the fetch → dedup → screen sweep and stop (standalone — no scoring/resume/networking). Delegates to the fetcher subagent.
---
Run the fetch sweep only: $ARGUMENTS

Standalone entry to the `fetcher` subagent — use when you want today's new-and-screened survivor list
without going into scoring/resume/networking.

1. Delegate to the **fetcher** subagent to run `DAILY_RUN.md` Steps 1-3 (ATS + optional Apify → dedup
   vs `seen_jobs.csv` → keyword/seniority screen). `$ARGUMENTS` may narrow scope (e.g. "ATS only",
   "T1 only") — pass it through; otherwise run the standard sweep.
2. Show you the survivor table + per-track/source counts + any Apify spend. Stop there — no scoring
   (that's `/rank` or `/apply-run`), no resumes, no contacts.
