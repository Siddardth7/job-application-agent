---
name: fetcher
description: >
  Stage 1 of the daily run. Asks the user for any hand-found postings, runs
  tools/fetch_jobs.py (six passes: your JDs, company career sites, LinkedIn target
  companies, all domains, contract/technician/intern, international), then reads
  .pipeline/fetch_report.json and tells the user how the fetch went and which blank
  postings are worth a job description. Writes nothing the script does not write.
  First stage, before ranker.
---

# Fetcher

No `model:` pin. The script produces every row; this skill runs it, reads its report,
and talks to the user about it. It never screens, scores, or invents a posting.

Cockpit root: the repository root (the directory containing `DAILY_RUN.md`).

## Step 1 — ask about hand-found postings (Pass 0)

Before running anything, ask once:

> Did you find any postings today you want in this run? Give me a folder of Markdown
> JDs, or paste LinkedIn job URLs. Say "no" to skip.

- A folder → pass it as `--jds=<folder>`. Each file needs a `**Title:**` line, a
  `**Company:**` line (or a filename shaped `Company - Title.md`), and the posting
  text. `**Location:**` and a `**Source:**` link are optional.
- URLs → one `--url=<url>` each. LinkedIn URLs are fetched from the public guest
  endpoint, no login. Any other URL is recorded as a lead without a description.
- "No" → run without either flag.

## Step 2 — run the fetch

```bash
python3 tools/fetch_jobs.py [--jds=DIR] [--url=URL ...]     # all six passes
python3 tools/fetch_jobs.py --ats-only                      # free passes only, no Apify
python3 tools/fetch_jobs.py --pass=1,2                       # a subset
```

Windows are 3 days for career sites, target companies and international; 24 hours
for all-domains and contract/technician. Caps are per pass in
`config/search_profile.json` (`search.apify_pass_caps`, `search.pass_days`).

It writes three handoffs:

| File | Purpose |
|---|---|
| `.pipeline/fetched.json` | every new posting, with descriptions, for the ranker — **the record** |
| `.pipeline/fetched.md` | the same, rendered, plus the pass table and the needs-JD list |
| `.pipeline/fetch_report.json` | per-pass status, raw/kept counts, cap, failure reason, drop counts |

The batch is **today only**. Nothing is reloaded from a previous run, and the
fetcher never writes `seen_jobs.csv`.

If the script itself errors, report the error and stop. Do not assemble a batch by
hand.

## Step 3 — read the report and tell the user

Read `fetch_report.json`. Report, in this order:

1. **The pass table**: for each pass, ok / failed / skipped, raw rows, rows kept, the
   cap. A failed pass must say why (the `reason` field). "Pass 2 returned 0" and
   "Pass 2 failed: Apify call timed out" are different sentences; use the right one.
2. **Career sites skipped** because the company is in `known_non_sponsors`
   (`portals_skipped_non_sponsor`). Tell the user to remove them from
   `tools/portals.json`.
3. **Postings worth a job description** (`needs_jd`, at most 10): rows that arrived
   without text. The ranker cannot score them. Say: "I could not get the description
   for these; if you want any of them ranked, paste the text into `JDs/<today>/` or give
   me the URL, and I will rerun pass 0."
4. The survivor count, and whether it is enough to be worth ranking. If every Apify
   pass failed, say so plainly; an ATS-only batch is a valid but smaller day.

## MUST
- Ask the Pass 0 question before running. Once.
- Run the script; report its numbers. Show the pass table.
- Name every failed pass and its reason.

## NEVER
- Never carry rows over from a previous run.
- Never write `seen_jobs.csv`, Supabase, or the tracker.
- Never screen on keywords or seniority, score, or drop a row the script kept. That is
  the ranker's job.
- Never pull descriptions by hand for rows the script left blank; ask the user instead.

## STOP conditions
The script errors; `.pipeline/fetched.json` is empty and every pass failed;
`config/search_profile.json` is missing (run `/setup`). Write an **OPEN QUESTIONS**
block at the top of `.pipeline/fetched.md` and stop.
