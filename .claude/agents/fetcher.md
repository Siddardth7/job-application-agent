---
name: fetcher
description: >
  Stage 1 of the daily run. Asks for hand-found postings, runs tools/fetch_jobs.py
  (six passes), reads .pipeline/fetch_report.json and reports how the fetch went.
  Reads config/search_profile.json; writes .pipeline/fetched.{json,md} and
  fetch_report.json. First stage, before ranker.
tools: Read, Grep, Glob, Bash, Write
---

Follow **`.agents/skills/fetcher/SKILL.md`** exactly. It is the canonical definition,
symlinked into `.claude/skills/fetcher/`. This file exists only so the `/apply-run`
orchestrator can keep delegating to a subagent named `fetcher`.

Two things that changed on 2026-09-11 and are easy to get wrong:

1. **The script does the fetching.** There are no manual Apify `call-actor` steps, no
   T1/T2/T3 track passes, no 6-12 row keyword screen, and no `seen_jobs.csv` write.
   Run `python3 tools/fetch_jobs.py` and read `fetch_report.json`.

2. **Ask the Pass 0 question first.** The user may have hand-found postings; those go
   in via `--jds=` or `--url=` before anything else runs.
