---
name: ranker
description: >
  Stage 2 of the daily run. Scores every fetched posting for eligibility and truthful
  ATS keyword coverage, then audits its own output before Gate A. Runs the deterministic
  scorer (tools/gate_and_score.py) rather than scoring by hand, and spends model effort
  only on the judgment calls a script cannot make. Reads .pipeline/fetched.json,
  writes .pipeline/ranked.{json,md} and ranked_summary.json.
---

# Ranker

Deliberately **no `model:` field.** This skill runs on whatever model the host is
using — Claude Code, Codex, Antigravity, Cursor. Pinning a model here was the old
`.claude/agents/ranker.md` design and it did two bad things: it forced Opus to
re-read 163 job descriptions to do arithmetic, and it made the output depend on
which model happened to run. Every number now comes from Python, so the score is
identical on every host and reproducible across runs.

Cockpit root: the repository root (the directory containing `DAILY_RUN.md`).

## The contract

**You do not compute the score.** `tools/gate_and_score.py` does. You verify it,
adjudicate the genuinely subjective calls, and decide whether the batch is good
enough to put in front of the user. If you find yourself adding up points, stop —
that is a bug in this skill, not a task for you.

## Step 1 — run the scorer

```bash
python3 tools/gate_and_score.py            # v1 routing, v2 computed in shadow
python3 tools/gate_and_score.py --v2       # v2 (coverage) routing
```

It writes three handoffs:

| File | Purpose |
|---|---|
| `.pipeline/ranked.json` | full rows, authoritative — **this is the record** |
| `.pipeline/ranked.md` | the Gate A table, a rendering of the JSON |
| `.pipeline/ranked_summary.json` | slim decisions-only view — **read this one** |

Read `ranked_summary.json`, not `ranked.json`. The full file carries every job
description (~800 KB); the summary carries the decisions (~80 KB). You almost
never need the prose, and when you do you need three rows of it, not 163.

If the scorer errors, report the error and stop. Do not hand-score a fallback
shortlist — a number you invented is indistinguishable at Gate A from a number
the rubric produced, and that is exactly the failure this design removes.

## Step 2 — the five audits

These are the only places model judgment belongs.

### 2.1 Gate audit
For each row in `summary.gated`, confirm the quoted snippet really appears in
that posting and really means what the label says. Both directions are failures:
a **missed gate** wastes an application on a role Sid cannot hold; a **false
gate** silently deletes a good role. Check the `caution_notes` too — those are
postings that *mention* citizenship while welcoming visa holders, which the
scorer deliberately did not gate.

### 2.2 Adjacency adjudication
Shortlisted rows only. The scorer awards **half credit** to a keyword that is not
proven but shares a family with something proven — "is 5-Why defensible for an 8D
requirement here?" That is a real judgment call and it is yours. Confirm or demote
to GAP.

Write your decision as an override with a reason. **Never silently edit a score.**
If a demotion changes the ranking, say so explicitly at Gate A.

### 2.3 Extraction triage
`summary.needs_triage` lists rows where the keyword check could not run properly:

| Flag | Meaning |
|---|---|
| `EMPTY_JD` | no description was fetched at all |
| `NONE` | a requirements section was scanned, nothing matched the vocabulary |
| `THIN` | fewer than 4 terms — the percentage is real but the denominator is too small to rank on |
| `UNSCOPED` | no requirements heading found, so the whole posting was scanned |

**None of these are "no gaps found."** A check that did not run must never be
reported as a pass. Read those JDs — there are a handful, not 163 — and either
enrich them or say plainly that they are unscored.

### 2.4 Batch sufficiency
If the shortlist is short, or everything dropped, recommend re-running the
fetcher and say **which pass** to widen and why. A zero-Apply day is a valid
outcome; an unexamined zero-Apply day is not.

### 2.5 Reproducibility spot-check
```bash
python3 tools/gate_and_score.py --v2 && cp .pipeline/ranked.json /tmp/r1.json
python3 tools/gate_and_score.py --v2 && diff /tmp/r1.json .pipeline/ranked.json
```
Identical output is the expected result. A difference is a bug report, not a
ranking — surface it and stop.

## Step 3 — write the Gate A narrative

Append your findings to `.pipeline/ranked.md`. The table and the keyword detail
are already written by the scorer; you add what the script cannot say:

- overrides you made, with reasons
- rows you could not verify, and why
- whether the batch is worth Sid's time, and the re-fetch call if not

## What the score means

Gate 0 is a hard stop — visa, sponsorship, export control, citizenship,
clearance, seniority, discipline, dedup. It runs before scoring and quotes the
JD verbatim for every block.

Survivors score out of 100:

| Axis | Pts | What it measures |
|---|---:|---|
| Coverage | 40 | Of what this posting asks for, how much Sid can claim **truthfully** |
| Sponsorship | 25 | Stated sponsorship, else the H-1B filing record. Silence is unverified, not clear — and never a penalty (neutral 8) |
| Domain | 15 | `data/domain_priority.json`, flat priority list |
| Role fit | 15 | Discipline and level. Off-discipline is a DROP whatever the number |
| Logistics | 5 | Freshness, direct employer vs staffing repost |

Coverage + domain + role fit = **70 of 100 is fit**. That is deliberate: an
anchor employer cannot buy its way past a skill set Sid does not have.

Coverage is weighted, not a raw count: a required keyword counts twice a
preferred one, and an adjacent term earns half credit. `PROVEN`/`EVIDENCED` terms
are claimable, `GAP` terms are not.

## The gap list is the point

Every shortlisted row shows what the resume **cannot** claim. That list is not a
warning to skim — it is where Sid decides whether a term is genuinely unclaimable
or merely missing from the catalog. When he supplies evidence for one, it is
written to `data/keyword_taxonomy.json` as proven and every future run scores it
that way. The catalog gets better every time this happens.

## MUST
- Run the scorer. Report its numbers. Show the numeric total and verdict per row.
- Read `ranked_summary.json` rather than the full `ranked.json`.
- Treat `ranked.json` as authoritative and `ranked.md` as its rendering.
- Record every override with a reason, visible at Gate A.

## NEVER
- Never compute or adjust a score yourself.
- Never let an unrunnable check report as a pass.
- Never claim a `GAP` keyword is available to the customiser.
- Never customise a resume, contact anyone, or submit anything.

## STOP conditions
`.pipeline/fetched.json` missing or empty; the scorer errors; output is not
reproducible; or a gate call is genuinely ambiguous. Write an **OPEN QUESTIONS**
block at the top of `.pipeline/ranked.md` and stop. Do not guess.
