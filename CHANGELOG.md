# Changelog

Newest first. One entry per merged change that alters what the pipeline does.

## 2026-09-11 — Fetcher rebuilt to the six-pass spec; offline test suite

Fetcher (`tools/fetch_jobs.py`, `tools/ats_scan.mjs`, `tools/lib/ledger.py`)
- Six passes with per-pass windows and caps: hand-found postings (0), career sites (1, 3 d),
  LinkedIn target companies (2, 3 d), all domains (3, 24 h), contract/technician/intern/co-op
  (4, 24 h), international (5, 3 d). Pass 1 results are no longer mislabelled Pass 2.
- No carry-over: the batch is what today's passes found. Nothing is reloaded from the previous
  `fetched.json`.
- Workday and SmartRecruiters rows now get their descriptions and requisition ids via each
  board's per-job detail endpoint (Greenhouse already did). Rows still blank are flagged
  `needs_jd` and the best 10 are listed for the user.
- Geo gate is word-bounded and never blocks a US state or region (Indianapolis, New England).
- Freshness is decided by posting date and repost wording; the hard-coded LinkedIn id cutoff
  is gone.
- Requisition id extracted from URL or text and used as the strongest dedup key; the ledger
  loader is one shared module (`tools/lib/ledger.py`) with an optional `req_id` column.
- Career-site portals whose company is in `known_non_sponsors` are skipped and flagged.
- Per-pass status / raw / kept / cap / failure reason written to `fetch_report.json` and the
  Markdown handoff. A failed Apify call is reported as failed, not as zero results.
- Apify input updated to the actor's current schema (`limitPerSource`, `maxTotalChargeUsd` as a
  run parameter); the old `count` and body-level cap were being ignored.
- Hand-found postings: Markdown JDs from any folder (`--jds=`), LinkedIn URLs via the public
  guest endpoint (`--url=`). The hard-coded employer list is gone.
- `classify_domain` is word-bounded ("ev" no longer matches "Development").

Process
- `tools/check.sh` runs every offline self-test; `tools/hooks/pre-commit.sh` runs the PII guard
  then `check.sh`; `.github/workflows/check.yml` runs the same on push and PR.
- `.agents/skills/fetcher/SKILL.md` replaces the stale manual fetcher agent; `/fetch` and
  `/apply-run` point at it.

Known follow-ups (ranker phase)
- Ranker still routes on v1 unless `--v2`; Gate 0 still drops intern/technician titles that
  Pass 4 now fetches; ranker should record dropped rows in `seen_jobs.csv` and carry
  yesterday's ranked-but-unapplied rows for one day.
