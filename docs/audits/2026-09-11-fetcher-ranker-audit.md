# Fetcher + Ranker audit — 2026-09-11

Scope: `tools/fetch_jobs.py`, `tools/ats_scan.mjs` (runner only), `tools/gate_and_score.py`,
`tools/keyword_engine.py`, `tools/lib/profile_config.py`, `data/domain_priority.json`,
`data/keyword_taxonomy.json`, the ranker skill, the fetcher/ranker agent definitions, the
`/fetch` `/rank` `/apply-run` commands, and `DAILY_RUN.md`. Verified against the live
163-row batch in `.pipeline/` (fetched 2026-09-09, ranked 2026-09-11) and a live ATS scan.

Health checks at audit time: all five self-tests pass (`gate_and_score --self-test`,
`keyword_engine --self-test`, `keyword_engine --audit`, `profile_config` demo,
`ats_scan --self-test`). Scorer output is byte-identical across two runs. The fetcher
`pass_num` crash was fixed the same day (uncommitted).

## Headline

The ranker rewrite is sound in design and reproducible, but it is **not live** and it
**cannot score the ATS channel**. Today's batch under v2 routing would shortlist 14 rows
instead of 36, and 36 of the 51 rows that pass Gate 0 are flagged as unscoreable
(THIN/EMPTY_JD/UNSCOPED/NONE). Two silent filters in the fetcher (geo substring, hard-coded
LinkedIn ID threshold) drop rows before the ranker ever sees them. Several gate patterns
have false positives that removed real US roles today.

Batch numbers (v1 routing, current default):

| Evaluated | Shortlisted | Cap reserve | Below 50 | Gated out |
|---:|---:|---:|---:|---:|
| 163 | 36 | 8 | 7 | 112 |

Gated-out breakdown: 63 VISA RISK (35 of them "Company Gate"), 20 already seen, 17
non-English, 11 non-engineering, 1 international staffing.

## Ranker findings (higher weight)

**R1 · CRITICAL · v2 is not routing.** `gate_and_score.py` routes on v1 unless `--v2` is
passed. `DAILY_RUN.md` Stage 2, the ranker SKILL step 1 (first line), `/rank`, and
`/apply-run` all call it without the flag. Today's `ranked_summary.json` says
`routing_model: "v1 (v2 shadow)"`. The new coverage numbers appear in the table, but who
gets shortlisted is still decided by the old density model. Decide the flip and put it in
one place (DAILY_RUN + SKILL + commands).

**R2 · CRITICAL · v2 cannot score any ATS row.** All 44 `ats_direct` rows in the batch have
an empty description; a live scan today returned 67 empty of 74 (all 47 Workday and all 20
SmartRecruiters rows; only Greenhouse is enriched). Under v2 those rows get coverage 0 and
drop below 50 (BorgWarner, Lucid, Archer today). Gate 0 cannot visa-check them either. The
ATS boards are the anchor-company channel, free, and highest quality. Fix on the fetch side:
per-job detail fetch for Workday (`/job/<id>` JSON) and SmartRecruiters
(`/postings/<id>`) in `ats_scan.mjs`, mirroring the Greenhouse `?content=true` path.

**R3 · HIGH · Most of the batch is unscoreable under v2.** Of 51 gate-passing rows: THIN 17,
EMPTY_JD 11, UNSCOPED 4, NONE 4, OK 15. The v2 shortlist of 14 contains 2 THIN and 4
UNSCOPED rows, and the #1 row (Plexus rotational, 77) is 100% coverage off 3 terms scaled by
0.75. The 88-term taxonomy is too small for what JDs actually name, and THIN scaling still
lets a thin row outrank a well-measured one. Recommend: (a) THIN and EMPTY_JD rows cannot
enter the shortlist; they go to a "needs JD / manual" bucket, (b) grow the taxonomy from
today's gap lists before the next run (the design already intends this), (c) six families
have zero claimable terms (semiconductor, battery, erp, regulated, automation, joining_am),
so any Micron/semiconductor JD can never earn coverage even though it is an anchor. Add the
evidenced terms you do have there, or accept that anchors are routed by Domain, not Coverage.

**R4 · HIGH · Non-English gate has English words in it.** Dutch cue list contains `taken`.
RTP Company, Quality Engineer, Fort Worth TX was gated as "Dutch language posting" on the
sentence "corrective and preventive actions to be taken". French list has `travail`,
`qualité`, `ingénieur`, which show up in bilingual US/Canadian postings. Fix: require two or
more distinct cues from the same language, drop common-English tokens, and only apply the
language gate to non-US sources.

**R5 · HIGH · Export-control boilerplate is a hard gate.** `export control|controlled` is
non-rescuable, so "comply with all applicable export control laws" (standard US
manufacturer boilerplate, no US-person requirement) drops the row. 7 rows today. Make
export-control rescuable: gate only when the same sentence also carries a requirement
verb or person-status term (`must`, `required`, `eligib`, `US person`, `citizen`);
otherwise CAUTION.

**R6 · HIGH · The ATS scan targets companies the config says never sponsor.** 29 of the 35
"Company Gate" drops come from `portals.json` entries General Motors, Robert Bosch and
Caterpillar, all listed in `known_non_sponsors`. That is 18% of the batch scanned, ranked,
and printed at Gate A for nothing. Remove them from `portals.json`, or have the fetcher skip
`known_non_sponsors` before writing `fetched.json`.

**R7 · MEDIUM · Years-of-experience regex reads the whole JD.** `\b(6|7|8|9|10)\+?\s*years`
anywhere in the text zeroes Role fit: "founded 10 years ago" scored 0 in a probe. "2-5
years" is scored as level II (4 pts) because the regex sees the 5. Scope the regex to the
REQUIREMENT zone that `keyword_engine.zone_lines` already computes, and parse ranges by the
low bound.

**R8 · MEDIUM · v1 domain classifier uses substrings.** `classify_domain` in
`profile_config.py` (used by the fetcher `track` column and the v1 Domain axis): `ev`
matches "Development", `cell` matches "Excellence", `packaging` matches food packaging.
Probes: "Product Development Engineer" → CleanTech & EV; "Packaging Engineer" at Kraft →
Semiconductor. The v2 domain scorer uses `word_match` and is correct. If v1 is retired,
delete it; otherwise switch to `word_match`.

**R9 · MEDIUM · Gate A rendering is wrong under `--v2`.** The "Why These Ranked Highest"
block hard-codes v1 axis labels (Spon /30, Skills /30, Sen /20 …) and reads v1 keys, so
under v2 it prints zeros next to the wrong labels. Fix before flipping the flag.

**R10 · LOW · USCIS lookup substring match on short names.** `get_uscis_approvals` does
`co_norm in name` with no length guard in that direction, so "KLA" matches every USCIS
employer containing KLA (Oklahoma…), "GE" matches thousands. Require exact or
token-boundary match for names shorter than 5 characters.

**R11 · LOW · `known_sponsors` tiers are ignored by v2.** Joby, Archer, Supernal, Beta,
Rivian etc. in config contribute nothing to the v2 Sponsorship axis; only the JD text and
USCIS file do. Either wire the tiers into `score_sponsorship_v2` or drop them from the
config so friends do not maintain dead data.

**R12 · LOW · Anti-spray cap keys on the raw company string.** "American Honda Motor
Company" and "Honda South Carolina Manufacturing" are counted separately: 5 Honda rows in
the 14-row v2 shortlist. Key the cap on `normalize_company()`.

**R13 · LOW · Duplicate ledger loaders.** `fetch_jobs.py` and `gate_and_score.py` each carry
their own ~80-line copy of `load_seen_*`, `normalize_company`, `normalize_title`. They have
already diverged: the ranker checks normalized fingerprints and the CSV `fingerprint`
column, the fetcher does not, which is why 20 rows the fetcher passed were caught as
ALREADY SEEN by the ranker. Move one copy to `tools/lib/ledger.py`.

## Fetcher findings

**F1 · CRITICAL · Geo gate blocks Indiana and New England.** `is_geo_blocked` is a substring
test over `blocked_locations`: `india` matches "Indianapolis, IN" and "Fort Wayne, Indiana";
`england` matches "New England". Verified with probes, all three return blocked. Every
such posting is dropped silently before the ranker. `portals.json` `location_filter.block`
carries the same list for the ATS scan (its `always_allow: united states` only rescues rows
whose location string spells that out). Fix: match on word boundaries and short-circuit on
a US state code or "United States" before consulting the block list.

**F2 · CRITICAL · Batch accumulates with no expiry.** `main()` seeds `raw_jobs` with the
previous `fetched.json`, freshness is stamped once at fetch time and never recomputed, and
the fetcher never writes `seen_jobs.csv` (only `log_and_refresh.py` does, for applied rows).
Today's batch carries `posted_at` back to 2026-08-28. A surfaced-but-not-applied row
therefore reappears in every run until someone applies to it. Meanwhile `/apply-run` step 0
does `rm -rf .pipeline`, so the two orchestrations disagree about whether the batch
accumulates. Pick one: either the fetcher records surfaced rows in `seen_jobs.csv` with
`status=surfaced` and each batch is new-today only, or rows expire after N days and
freshness is recomputed on load.

**F3 · HIGH · LinkedIn ID freshness thresholds are hard-coded.** `classify_job_freshness`
drops any LinkedIn ID below 4 455 000 000 as REPOSTED, with the comment "In Sept 2026". The
constant will be wrong within weeks and nothing warns. Apify returns `postedAt`; use it
first and fall back to the ID, or derive the cutoff from the max ID seen in the batch.

**F4 · HIGH · The fetcher agent definition describes a pipeline that no longer exists.**
`.claude/agents/fetcher.md` tells the subagent to run `DAILY_RUN.md` Steps 1–3, three
T1/T2/T3 Apify passes via the `call-actor` MCP tool, append to `seen_jobs.csv`, keep a 6–12
row survivor screen, and write only `fetched.md`. None of that matches `fetch_jobs.py`.
`/fetch` and `/apply-run` delegate to that file. `/rank` likewise references track
classification and the retired Referral ≥80 lane. The ranker got a proper skill on
2026-09-09; the fetcher did not. Write `.agents/skills/fetcher/SKILL.md` the same way
(run the script, audit the output, STOP conditions) and rewrite the three commands.

**F5 · MEDIUM · Pass 1 Apify rows are labelled Pass 2.** `normalize_job(..., source_type=
"linkedin_apify_p2", pass_num=2)` inside the Pass 1 branch. Breaks the per-pass breakdown.
One-line fix.

**F6 · MEDIUM · Silent zero on Apify failure.** `run_apify_linkedin_search` is one
`run-sync-get-dataset-items` request per pass with a 120 s timeout; any exception returns
`[]` and the run continues. `fetched.md` records no per-pass count and no spend, so a pass
that timed out looks like a pass that found nothing. Print per-pass raw counts and a
"returned 0" warning into `fetched.md`.

**F7 · MEDIUM · Personal employer heuristics in `load_local_jds`.** Hard-coded Mayville,
Goodman/Daikin, Curtiss-Wright, Magna, KLA, Crane, S&B, Camfil detection in a public
bring-your-own repo. Parse a `**Company:**` line from the JD file and fall back to the
filename.

**F8 · LOW · Summary counts overstate discovery.** "Total Raw Discovered" includes
carried-forward rows. Print new-this-run separately.

**F9 · LOW · `None` fields crash `normalize_job`.** `item.get("title", "").strip()` raises
if Apify returns `null`. Use `(item.get("title") or "").strip()`.

**F10 · LOW · Supabase project URL is a hard-coded default** in both tools. Not a secret,
but it is your project in a public repo. Require it from `.env`.

## Recommended order before the next run

1. F1 geo (word-boundary), F5 label, R4 `taken`: three small edits, all silent-drop bugs.
2. R6: remove GM / Bosch / Caterpillar from `portals.json`.
3. Run with v1 routing (the default) and read the v2 shadow columns. Do not flip to `--v2`
   until R2 (ATS descriptions) and R3 (THIN/EMPTY handling) are done; otherwise the free
   anchor channel disappears from the shortlist.
4. Feed today's gap lists into the taxonomy. That is the designed learning loop and the
   fastest way to reduce THIN.
5. Then R2, F2, F3, F4.

## Keeping it consistent for two or three people

Full CI/CD is not worth it: no deploy target, no test matrix, and the expensive path
(Apify, node, network) cannot run in CI anyway. What is worth it costs about an hour:

- **One check command.** `tools/check.sh` that runs the five self-tests plus
  `python3 -m py_compile tools/*.py`. Ten seconds, offline.
- **Run it in the pre-commit hook** that already exists (`tools/hooks/pii_guard.sh`). A
  commit cannot land with a red self-test on any clone. That is your CI.
- **A 15-line GitHub Actions workflow** running the same script on push. Free; its only
  job is catching a friend who committed from a machine without the hook. Optional.
- **A fetcher dry-run.** `fetch_jobs.py --dry-run` that reads a fixture instead of node
  and Apify. Today's `pass_num` crash would have been caught by it.
- **Turn every false positive into a fixture.** RTP "taken", Indianapolis, the export
  boilerplate, "founded 10 years ago": each becomes one `check(...)` line in the existing
  self-test. Regression tests are the cheap CI.
- **One source of truth for the sequence.** `DAILY_RUN.md` is authoritative; the agent
  and command files must point at it or at a SKILL.md, never restate it. Delete
  `.claude/agents/fetcher.md` once the fetcher skill exists.
- **Branch + PR to main, self-test green, tag when friends should pull.** Keep a short
  `CHANGELOG.md`; the commit messages are already good enough to paste.
- **Model comparison as a tool, not a session.** A `tools/compare_models.py` that prints
  v1 vs v2 shortlist diff from `ranked.json` is how the flip decision gets made, and
  re-made after every taxonomy change.
