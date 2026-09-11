---
description: Run just Stage 1 (fetch) and stop — no scoring, no resumes, no networking. Delegates to the fetcher subagent.
---
Run the fetch only: $ARGUMENTS

Standalone entry to the `fetcher` subagent (`.agents/skills/fetcher/SKILL.md`) — use when you
want today's new postings without ranking them. The full daily run is `/apply-run`; this exists
for checking what the passes return.

1. Delegate to the **fetcher** subagent. It asks whether you have hand-found postings (a JD
   folder or LinkedIn URLs), then runs `python3 tools/fetch_jobs.py`. `$ARGUMENTS` may narrow
   scope and is passed through as flags: "ATS only" → `--ats-only`, "pass 1 and 2" → `--pass=1,2`.
2. Show the pass table from `.pipeline/fetch_report.json` (status, raw, kept, cap, failure
   reason per pass), any career sites skipped as known non-sponsors, the postings worth a job
   description, and the survivor count. Stop there.
