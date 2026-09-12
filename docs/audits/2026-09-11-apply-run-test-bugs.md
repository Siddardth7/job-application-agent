# Apply-Run Test Bug Analysis — 2026-09-11

Test run after the fetcher (six-pass) and ranker (one-formula) rebuilds merged to main.
This doc tracks anything that goes wrong or sideways during the run: crashes, silent
data loss, schema mismatches, gate misfires, integration seams between the new fetcher/
ranker and the rest of the pipeline. Updated live as stages complete.

## Run context
- Date: 2026-09-11
- Trigger: `/apply-run` test run, explicitly to shake out the fetcher-rebuild (PR #1)
  and ranker-one-formula (PR #2) merges to main.
- Both PRs merged 2026-09-11 ~7:54pm CDT per CHANGELOG/git log; this is the first live
  integration run since merge.

## Issues found

### Stage 1 — Fetcher (six-pass rebuild)

**Result: clean run, no crashes, no errors.** `python3 tools/fetch_jobs.py` exited 0 with no
tracebacks. All 6 passes (Pass 0 hand-found, 1 career sites, 2 LinkedIn target cos, 3 LinkedIn
all-domains, 4 LinkedIn contract/technician/intern, 5 LinkedIn international) reported
`status: ok` (Pass 0 skipped — no hand-found postings supplied for this unattended test run).
227 raw → 175 survivors, arithmetic checks out exactly (raw = kept + drops, no silent loss).
Zero rows arrived with a blank job description (`needs_jd: []`). `fetched.md`, `fetched.json`,
`fetch_report.json` all well-formed and non-empty.

- **[Minor / gap] Apify spend is never surfaced.** `fetch_report.json` only records the
  configured per-pass spend *cap* (`cap_usd`, e.g. 0.12/0.12/0.10/0.12 = $0.46 ceiling), not
  actual dollars charged by the Apify actor. Profile's Run Parameters promise "<= $0.50 per
  daily run" but nothing in the pipeline currently verifies this was honored — only that it
  *could not* have been exceeded. Not a bug in this run, but a monitoring gap.
  **Action:** decide whether `fetch_jobs.py` should read back actual usage from the Apify run
  response and log it in `fetch_report.json`.

- **[Note, likely by design] Non-sponsor skip is Pass-1-only.** `portals_skipped_non_sponsor`
  correctly skipped General Motors / Caterpillar / Robert Bosch on the direct ATS career-site
  pass (Pass 1), but General Motors still surfaced as a kept row via Pass 3 (LinkedIn
  all-domains, row 38, Entry-Level Paint Process Engineer, Wentzville MO). The non-sponsor
  filter doesn't propagate to the LinkedIn passes. Flagging for confirmation — if intentional
  (LinkedIn passes rely on Gate 0 at rank time to catch these), no action needed; if not,
  this is a gate consistency bug to fix in the ranker or fetcher.

### Stage 2 — Ranker (one-formula rebuild)

**Result: clean run, no crashes.** `python3 tools/gate_and_score.py` exited 0, no
tracebacks/warnings. `Ranked 175 (0 carried): Apply 15, Reserve 33, Unverified 34, Drop 93`.
All 175 input rows accounted for (Drop 93 = 59 gated + 34 below-threshold). `ranked.json`,
`ranked.md`, `ranked_summary.json` all well-formed and match SKILL.md's documented schema.

- **Gate 0 confirmed working on the GM re-surface case:** the General Motors row that slipped
  past the fetcher's Pass-1-only non-sponsor filter (see Stage 1 finding above) **was correctly
  caught and gated by the ranker's Gate 0** ("GM company-wide policy: no OPT/H-1B sponsorship").
  Same for Progress Rail/Caterpillar (substring match on parent company name). **This resolves
  the Stage 1 concern** — the two-stage design (fetcher doesn't need to be the only gate;
  ranker's Gate 0 is the actual backstop) is working as intended. Robert Bosch didn't appear in
  today's fetch, so that specific path is unvalidated but the config key exists.
- Sub-scores sum to totals in 100/82 scored rows, no NaN/out-of-range, weights match the
  documented 40/25/15/15/5 formula exactly. Apply bucket capped correctly (max 2/company).
- Ledger (`seen_jobs.csv`): 175 new rows dated 2026-09-11, status counts tie exactly to bucket
  totals (48 shortlisted, 34 unscored, 93 dropped). Carry-over correctly empty (fresh test day,
  `totals.carried = 0`).
- **[Cosmetic bug] Duplicate caution note.** The Stratasys "Associate Quality Engineer" Apply
  row renders the identical ITAR/export-control caution line twice in `ranked.md` (lines
  102-103, verbatim duplicate). Doesn't affect score or bucket, but SKILL.md implies one
  caution per matched snippet. **Action:** dedupe caution-note rendering in the ranker's
  markdown writer (likely appending the same match twice from two overlapping regex passes).
- **[Judgment flag, not a bug]** Micron Technology has 2 rows in today's Apply bucket (RAM RDA
  Process Engineer, score 90; RAM Quality Engineer, score 87). Per `micron-referral-6mo.md`
  memory, a ~6-month-old referral is already on file at Micron with guidance not to over-apply.
  The ranker has no visibility into off-system referral history — this is correctly a Gate A
  human call, not a scoring defect. **Candidate reviewed and chose to proceed with both rows.**

### Stage 3 — Customiser (integration test against new ranker output)

**Result: all 15 resumes tailored and compiled successfully (exit 0, all 1-page PDFs), no
fabrication.** This stage surfaced the most substantive findings of the run — real schema
mismatches between the rebuilt ranker's output and what the customiser expects, none of them
fatal (the subagent worked around them by reading `ranked.json` directly and using judgment),
but all worth fixing so the next run doesn't depend on a subagent noticing and improvising.

- **[Bug — missing fields] `ranked.md` has no `Resume` (track) column and no `JD file` column.**
  The customiser's brief describes these as its primary per-row inputs; neither exists in the
  new ranked.md schema. It fell back to reading `ranked.json` directly. **Action:** either add
  these columns back to `ranked.md`, or update the customiser's SKILL.md to point at
  `ranked.json` as the source of truth going forward.

- **[Bug — broken field] `ranked.json.recommended_resume` is the literal string `"Resume_Master"`
  for all 15 rows, identical across wildly different domains (semiconductor, aerospace, pharma,
  consumer mfg), and no file named `Resume_Master.tex` exists anywhere in the repo.** The
  closest matches are a template at `templates/resume_master.tex` (never instantiated as
  `Resume_Master.tex`) and the actual live file `Resume/Final_Resumes/Resume_NewStrategy_Master.tex`
  (input by six one-line `\ResumeType` stub files). This field is currently useless for track
  selection — the ranker rebuild appears to have dropped real per-row track recommendation logic
  and left a placeholder constant. The customiser worked around it by picking ResumeType 0-5
  itself from each JD's title/discipline. **Action:** either implement real track selection in
  the ranker (per `profile.md`'s Base Resume Mapping table) and populate `recommended_resume`
  correctly, or remove the field entirely so downstream stages don't rely on it.

- **[Bug — mislabeled data] `ranked.json.domain` mislabeled row 6 (United Pharma Technologies,
  a Florida pharma/medical-device NPI contract role) as `"Aerospace, eVTOL & Composites"`.**
  The customiser caught this by reading the actual JD text and used Generic_Quality/pharma
  content instead of tailoring toward aerospace. **Action:** check the ranker's domain
  classifier for a false-positive trigger on this posting (possibly a keyword collision, e.g.
  "composite" materials in a pharma context, or a decision-taxonomy gap).

- **[No fetcher/ranker gap after all — architecture confirmed] No `JDs/<today>/` directory
  exists; the rebuilt fetcher/ranker no longer writes per-job JD `.md` files** — JD text now
  lives only inline in `ranked.json`'s `description` field. This is a deliberate architecture
  change from the old per-file JD model, not a bug, but flagging because any stage or script
  still expecting `JDs/<date>/*.md` to exist will silently find nothing. Confirm no such
  dependency remains anywhere in the pipeline.

- **[Pre-existing content bug, not fetcher/ranker] Master resume template
  (`Resume/Final_Resumes/Resume_NewStrategy_Master.tex`) is stale against P1_03**: it still
  names the flagship project "Quality Engineering Skills" (old repo `quality-engineering-skills`)
  instead of the renamed/merged "Ouroboros" (`quality-platform`) per the 2026-08-18 resume
  restructure decision. The customiser corrected this uniformly across all 15 outputs and
  flagged it for the template owner. **Action:** fix the master template once, upstream, so
  future tailoring doesn't need to repeat this correction.

- **[Doc inconsistency, not a code bug] Conflicting Projects-section count across docs**: P1_03
  prose says "exactly six, do not add a seventh," the customiser's brief said "5 project
  entries," and the actual 1-page template (`ResumeType` 0-5) renders only **3** Projects
  entries (the other 3 gated behind the 2-page `ResumeType=6` variant). **Action:** reconcile
  P1_03 / the customiser skill doc / the template to agree on one number.

- Self-check gate worked as designed and caught a real defect mid-run: first draft pushed 7 of
  15 resumes to 2 pages (reworded lead bullets + padded Skills lines); the page-count check
  forced a rework (revert to reorder-only edits) before final output. This is the gate working
  correctly, not a bug — noting it because it's a good sign the hard self-check practice from
  `customise-hard-selfcheck-gate.md` memory is still effective post-rebuild.

### Stage 4/6 — Supabase Sync & Tracker Rebuild (`tools/log_and_refresh.py`) — **BLOCKING BUGS, FIXED**

Two bugs here fully blocked the mandatory Stage 6 write and had to be fixed to complete the
test run. Both are pre-existing pipeline-glue bugs surfaced by actually running the full chain
end-to-end for the first time since the fetcher/ranker rebuild — not bugs in the fetcher or
ranker themselves.

- **[Bug — FIXED, missing handoff file] `.pipeline/tailored.json` never gets created.**
  `log_and_refresh.py` hard-requires it (`tailored_json_path.exists()` check, line ~192) and
  exits 1 if absent. But the customiser subagent's own definition
  (`.claude/agents/customiser.md`, "Write (only this handoff)") says it writes **only**
  `.pipeline/tailored.md` — there is no code path anywhere in the current customiser that
  produces the `.json`. This means **Stage 6 has been broken for every run since the customiser
  moved to the subagent/markdown-only handoff model**, not just today. **Fix applied this run:**
  hand-built `.pipeline/tailored.json` by joining `tailored.md`'s company/title/resume-path rows
  against `ranked.json`'s per-row data (location, score, link, apply_url, recruiter_url,
  peer_url). **Action needed:** either (a) update the customiser agent spec to also emit
  `tailored.json` in the schema `log_and_refresh.py` expects, or (b) update
  `log_and_refresh.py` to read `tailored.md` + `ranked.json` directly instead of a `.json` that
  no longer gets written. Until one of these lands, every future run will hit this same wall.

- **[Bug — FIXED, `NameError` dead code] `is_curated` referenced but never defined in
  `insert_to_supabase()`** (`tools/log_and_refresh.py` line 99, `tag = "[Curated Target Lane]"
  if is_curated else "[Broad-Fit Direct Apply]"`). This is leftover from the September 9
  tracks-retirement refactor — `lane_val` and `track_val` on the two lines directly above it
  were already hardcoded to the single-lane model (per their own comments), but this one line
  was missed and would raise `NameError` on the very first record of any live (non-dry-run)
  insert. **This means Stage 6 could never have completed live since 2026-09-09**, regardless
  of the `tailored.json` issue above. **Fix applied this run:** replaced with a single hardcoded
  `tag = "[Direct Apply]"`, consistent with the already-single-lane `lane_val`/`track_val`
  right above it. Verified via `--dry-run` before the live write.

**Result after both fixes:** `python3 tools/log_and_refresh.py --dry-run` ran clean, then the
live run inserted all 15 applications (`ja-0911-01`..`ja-0911-15`) into Supabase
`applications`, upserted 30 recruiter/team-lead contact rows into `contacts`, appended
`seen_jobs.csv`, and rebuilt the tracker successfully (423 applications + 577 contacts
rendered, `learning_log.md` synced with 82 drop reviews).

- **[Note — not fixable from here] Tracker no longer lives where `refresh.sh` deploys it.**
  The candidate has moved the live tracker to a ChatGPT Sites–hosted page
  (`sid-job-search.sid20027.chatgpt.site`), but `refresh.sh`/`refresh.py` still only write to
  the old Cowork/Claude-Artifacts auto-deploy path
  (`~/Documents/Claude/Artifacts/job-search-tracker/index.html`) and local
  `job_tracker.html`/`job_tracker.artifact.html`. There is no tool access from this session to
  push to a ChatGPT Sites page, and no deploy path to it exists anywhere in the repo. Per the
  candidate's instruction, left as-is (Supabase is the source of truth; tracker regeneration
  target is now stale and needs a real decision — either wire a new deploy step for the
  ChatGPT Sites page, or point people back at a Claude Artifact).

- **[Minor — doc/output mismatch] Output directory structure diverges from DAILY_RUN.md's
  Stage 3 spec.** DAILY_RUN.md describes `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/Apply/`
  (approved PDFs only) and `Archive/` (`.tex`/`.log`/`.aux`/`.out`). The actual customiser
  subagent wrote flat into `Job_Applications_Resumes/2026-09-11/*.pdf` (no `Apply/` subfolder,
  no `<Month>/` parent) with only `src/*.tex` split out (no `.log`/`.aux`/`.out` archived).
  Not a functional problem for this run, but another doc/implementation drift from the same
  subagent-handoff rework that caused the `tailored.json` issue above. **Action:** reconcile
  DAILY_RUN.md's directory spec with what the customiser agent actually does, or update the
  agent to match the documented structure.

## Summary / final verdict

**The rebuilt fetcher and ranker themselves are solid.** Both ran end-to-end with zero crashes,
zero tracebacks, zero silently-dropped rows, and internally consistent arithmetic (raw = kept +
drops at every stage). Gate 0 correctly caught the one non-sponsor company (General Motors)
that slipped past the fetcher's narrower Pass-1-only filter — the two-stage gate design works
as intended. Score math, bucket caps, and ledger writes all checked out exactly against the
documented 40/25/15/15/5 formula. This validates the core goal of today's test: the fetcher
rebuild (PR #1) and ranker rebuild (PR #2) are functioning correctly in isolation.

**The real damage was in the glue between stages, not the rebuilt stages themselves** — and it
was severe enough that the pipeline could not have completed a live run at all without today's
fixes:

1. **Stage 6 (Supabase sync) has been completely broken since two separate points in time**,
   independent of today's rebuild: `is_curated` NameError since the 2026-09-09 tracks-retirement
   refactor, and missing `tailored.json` since the customiser moved to its subagent/markdown-only
   handoff model (timing unclear, but predates today). Neither is caused by the fetcher/ranker
   rebuild — they were latent, and today's test run is what surfaced them, because it may be the
   first time the full chain was actually run live end-to-end since those two changes landed.
2. **The ranker's `recommended_resume` field is dead/broken** (constant `"Resume_Master"` string)
   and its `domain` classifier produced at least one clear false-positive (pharma role tagged
   aerospace). Both were caught and worked around by the customiser, not by the ranker itself.
3. Several doc/implementation drifts (directory structure, Projects-entry count, JD-file
   architecture change) reflect that DAILY_RUN.md / P1_03 / agent specs haven't been kept in
   sync with the last two rounds of rebuilds.

**Net assessment:** ship the fetcher/ranker rebuilds — they're correct. But treat this run as
proof that **the pipeline as a whole was not actually runnable end-to-end before today's fixes**,
and prioritize: (a) reconciling the customiser↔`log_and_refresh.py` handoff contract so
`tailored.json` gets produced by someone, (b) fixing or removing `recommended_resume` in the
ranker, (c) a documentation pass reconciling DAILY_RUN.md/P1_03 against what the current
subagents actually do.

**Action items, prioritized:**
1. **[High]** Decide who produces `.pipeline/tailored.json` (customiser agent, or have
   `log_and_refresh.py` read `tailored.md`+`ranked.json` instead) — today's hand-built version
   was a one-off workaround, not a durable fix.
2. **[High]** Fix or remove `ranked.json.recommended_resume` (currently a dead constant).
3. **[Medium]** Investigate the domain-classifier false positive on United Pharma Technologies.
4. **[Medium]** Decide on a real tracker deploy target (ChatGPT Sites vs. Claude Artifacts vs.
   both) and wire `refresh.py`/`refresh.sh` to actually reach it.
5. **[Low]** Dedupe the ranker's caution-note rendering (Stratasys double-line).
6. **[Low]** Reconcile DAILY_RUN.md/P1_03 directory and Projects-count documentation against
   actual subagent behavior.
7. **[Low]** Decide whether Apify actual spend should be captured (currently only the cap is
   recorded).

---

## Stage 3 — Customise audit (2026-09-12, independent re-verification)

Re-ran every self-check gate from `.claude/agents/customiser.md` against the 15 shipped outputs
from a clean session (not trusting the subagent's self-report, per `customise-hard-selfcheck-gate`).

### What was re-verified and PASSES
- **md5 uniqueness**: 15/15 unique (`md5 -q src/*.tex | sort -u | wc -l` = 15).
- **Diff vs resolved track base**: rebuilt the six one-page bases by resolving `\ifcase\ResumeType`
  0–5 from the master and diffed each output against its declared track. 13–27 changed lines per
  row; **every row's diff touches `\textbf{...}:` Skills lines (2–6 per row)**. DEPTH gate holds.
- **Company-name grep**: 0 hits in 14/15 outputs. The 2 hits in `MSA_QualityCoop` are
  `MSA/Gage R&R` (the measurement-system acronym), not the employer — false positive, no leak.
- **Compile / page count / bad boxes**: recompiled all 15 with `pdflatex -halt-on-error`: rc=0,
  1 page, **0 Overfull/Underfull boxes** on every file (FORMAT_SETTINGS' `badboxes=0` rule was not
  in the agent's gate list; it holds anyway).
- **Em dashes (U+2014)**: 0 in all outputs. **Buzzwords**: 0. **Employer `\textbf` headers**: unchanged.
- **Ouroboros rename** applied uniformly (0 files still say `quality-engineering-skills`, 15 say Ouroboros).
- Visual check of `resume_UnitedPharma_QE.pdf`: top third reads Education → Skills tailored to the
  JD (drawing interpretation, GD&T, MSA, PFMEA, CAPA). Layout clean.

### CORRECTION (2026-09-12, after candidate review) — the "Ouroboros rename" was a regression, not a fix
The Stage 3 note above ("master template is stale against P1_03 … customiser corrected this
uniformly") and the first draft of this audit had the direction **backwards**. The master template
(`Resume_NewStrategy_Master.tex`, edited Aug 31) is correct: the project is **Quality Engineering
Skills** / `quality-engineering-skills`. The **playbook** `P1_03` (edited Aug 18, gitignored, no
history) was the stale file — it still carried the retired "Ouroboros / quality-platform" name and
an explicit "never list both" instruction, and the customiser obeyed the playbook over the template,
renaming the entry (and its date, 2026→2024) in **all 15 shipped resumes**. Root cause: P1_03's
inventory is a hand-maintained copy of the template and had drifted; the agent had no rule for
which wins.
**Fixed 2026-09-12:** all 15 `.tex`/`.pdf` reverted to the master's entry and recompiled (1 page,
0 bad boxes, 15 unique md5); the two drifted Sentinel-8D bullets (Nordson_ProcessIntern, Whirlpool)
reverted to master wording; P1_03 §Projects corrected and given a "template wins on names/links/
dates" rule. Any of the 15 that were already submitted before this fix went out with the old name.
Action item 11 (reconcile master ↔ P1_03 ↔ FORMAT_SETTINGS ↔ candidate DB) stands — the
experience/project *count* drift in P1_03 is the same class of bug and is still open.

### Findings

- **[Bug — content] Stale cross-reference in the Ouroboros bullet, 12/15 outputs.** The base's
  second Ouroboros bullet ends "…the analysis backbone for the two case studies **below**." Tailoring
  promoted a case study *above* Ouroboros in 12 rows, so the sentence now points the wrong way
  (only GKN, Micron_RDAProcess, Stratasys kept Ouroboros in lead). A human reader notices; ATS
  doesn't. **Action:** either reword the master bullet to be position-independent ("…backbone for
  the two case studies in this section") or add a gate check that a promoted entry doesn't break a
  neighbour's wording.

- **[Truth-boundary drift — 2 rows] Reworded project bullets claim adjacent methods.**
  - `Nordson_ProcessIntern` Sentinel-8D bullet now says "…a **fishbone/pareto-style** root-cause
    investigation built and analyzed in Python and Excel." The same handoff row lists Fishbone as
    "adjacent only, not proven" in its *left-out* line — the summary and the resume contradict each
    other. Sentinel-8D used Welch's t-tests/FDR/logistic regression, not fishbone/Pareto.
  - `Whirlpool_MfgEngAnalyst` Sentinel-8D bullet now ends "…a scrap-reduction and **supplier**
    root-cause-analysis case study." The dataset is an upstream *in-house* saw-cut station, not a
    supplier. Also the reword dropped the OR/p-value and now states "cuts PFMEA RPN 91.7% (336→28)"
    in **both** bullets of the same entry (redundant).
  Not fabrication of experience, but both are exactly the "angle the bullet to the JD" instruction
  in P1_03 §5 sliding into claiming a method not used. **Action:** tighten P1_03 §5 / agent Do-step
  1(c): rewording may re-emphasise, never name a method/tool/party absent from the inventory; and
  add a gate check that no keyword from the row's `adjacent_keywords`/`gap_keywords` appears in a
  *reworded* bullet.

- **[Gate weakness] DEPTH check (#7) cannot fail under the current workflow.** The subagent flattens
  `\ifcase\ResumeType … \fi` into one Skills block, so a naive `diff output master` always shows
  Skills-section churn even for an untouched track. The 2026-09-11 run *did* make real edits (verified
  above against resolved bases), but the gate as written measures the wrong thing. **Action:** the
  agent spec should say to diff against the *resolved* track base (resolve `\ifcase` first), or the
  master should stop using `\ifcase` and ship six real base files.

- **[Spec drift] Two customise implementations, three contradicting specs.**
  1. `tools/customise_resume.py` — DAILY_RUN.md Stage 3, `tools/daily_run.sh customize`, README and
     AGENTS.md all point here. It **cannot run**: hard-coded to `Resume/Final_Resumes/Resume_Master.tex`
     (doesn't exist → `FileNotFoundError`, confirmed); reads `data/candidate_resume_database.json`
     which is itself stale (project still `Quality Engineering Skills`/`quality-engineering-skills`,
     4 experience entries, only 4 projects, no Nexus/Sentinel dates aligned to P1_03). Its
     `reviewer_agent` check #3 ("no employer not in the DB") is a loop of `continue`s that never
     appends a failure — dead code. `--demo` self-test passes but only exercises the pure helpers.
     Not in `check.sh`.
  2. `.claude/agents/customiser.md` — what actually ran. Also points at `Resume_Master.tex` and
     `JDs/<today>/`; neither exists. Writes only `tailored.md` (the `tailored.json` gap already logged).
  3. `.codex/agents/customiser.toml` says it writes `tailored.json` *and* `.md`. `.codex/skills/
     resume-customise` is the only doc naming the real file `Resume_NewStrategy_Master.tex`.
  **Action:** pick one. Recommendation: keep the subagent (it produced verified output; the script
  never has), delete or quarantine `customise_resume.py` + its `daily_run.sh` hook, and fix the two
  paths in `customiser.md` (`Resume_NewStrategy_Master.tex`; JD text from `ranked.json.description`).

- **[Content drift] Master template ≠ P1_03 inventory ≠ FORMAT_SETTINGS.** P1_03 says Experience =
  exactly 3 (Tata, UIUC AML GRA, EQIC) and Projects = exactly 6 (incl. SAMPE, Solarians, Borosilicate).
  The live master has **4 Experience entries** (Tata, SAMPE, EQIC, Solarians — no UIUC AML) and
  **3 one-page Projects** (Ouroboros-as-QE-Skills, Nexus, Sentinel; Borosilicate/Virtual-Laminate/SAE
  only in the 2-page variant). FORMAT_SETTINGS says 3 exp + 5 projects and names files
  (`Track1_Semiconductor_QE` etc.) that no longer exist. The customiser correctly treated the master
  as truth and tailored what's there; the docs describe a resume that isn't the one being sent.
  **Action:** one reconciliation pass — decide the canonical shape, then make master, P1_03
  inventory, FORMAT_SETTINGS and `candidate_resume_database.json` agree.

- **[Ranker, resolved] United Pharma `domain` false positive — root cause found.** `score_domain`
  takes the *first* domain in `config` order whose cue word-matches anywhere in title+company+JD;
  Aerospace is first and the JD contains the bare word "aerospace" (boilerplate industry list),
  while Precision/Regulated matched `automotive` + `medical`. First-match-wins on an ordered list
  with generic cues is the defect, not a taxonomy gap. Note it only cost the row 15-pt sub-score
  headroom (it still scored 77, Apply) — the customiser ignored the label. **Action:** score by
  cue-hit count (or title-cue priority) instead of list order; or require ≥2 cues / a title hit
  for the top-priority domains.

- **[Minor] `verify_pdf.py` syntax scan** claims to check `& % # _ $` but only checks `&` (inside
  `\textbf/\resumeItem/\small` lines) and `_`. It was not used by the subagent path anyway.

### Stage 3 verdict
**Output quality: good.** All nine agent gates genuinely hold on re-verification, plus bad-box and
em-dash checks the gate list omits. The two truth-boundary rewords are the only content defects
worth fixing before these resumes are reused as bases; the "below" cross-ref is cosmetic.
**Infrastructure: one working path (the subagent) and one dead path (the script) that every
operator-facing doc points to.** The pipeline works because the subagent reads around broken
paths; the docs describe a system that does not exist.

**Customise action items — ALL CLOSED 2026-09-12** (branch `customiser-audit-fixes`):
8. ✅ Subagent kept; `tools/customise_resume.py` deleted; `daily_run.sh customize` now points at the
   subagent; DAILY_RUN / README / AGENTS / `.codex` docs rewritten to describe the real flow and the
   real output layout (`Job_Applications_Resumes/<date>/{*.pdf,src/}`). Master renamed
   `Resume_NewStrategy_Master.tex` → **`Resume_Master.tex`** (the name every doc and `/setup` already
   used); all 7 stubs repointed and recompiled (6×1 page, 1×2 page, 0 bad boxes). `customiser.md`
   now reads JD text from `ranked.json.description`, maps title/discipline → `\ResumeType` 0–5, and
   carries the "master wins over playbook" rule. `.codex/agents/customiser.toml` regenerated from it.
9. ✅ P1_03 §5 and `customiser.md` Do-step 1(c): reword only to re-emphasise; never introduce a
   method/tool/standard/party/metric; never use an adjacent/gap/required-gap word. New gate check 7
   (REWORD TRUTH) greps every changed bullet for those words. Both drifted bullets reverted.
10. ✅ `score_domain` now picks the domain with the most cue hits (ties → profile order); two
    self-test assertions added. Yesterday's 175 rows re-labelled offline to measure impact (see run log).
11. ✅ P1_03 inventory now mirrors the master exactly: 4 experience entries (Tata, SAMPE, EQIC,
    Solarians), 3 one-page projects, two-page-only entries listed as "never on a one-pager", and a
    "master wins" rule at the top. FORMAT_SETTINGS file table / verification loop / content rules
    updated to the seven-stub layout. Candidate DB was already aligned on names.
12. ✅ Master (and DB) bullet now reads "…the two case studies in this section" (position-independent).
    `tools/resolve_track.py <N>` added (self-test in `check.sh`); gate checks 1 and 6 diff against it,
    plus new check 10 (0 bad boxes before the log is deleted).

**Still open from the top list:** 1 (`tailored.json` contract), 4 (tracker deploy target), 5
(caution-note dedupe), 7 (Apify spend) — the fetcher/tracker pass.
