# Shortlist Scoring Rubric (template)

> `/setup` fills the `[BRACKETED]` values from your answers and writes
> `playbook/P1_06_scoring_rubric.md`. The *mechanics* below are fixed — they mirror what
> `tools/gate_and_score.py` actually executes. Only the **profile-specific** values change.
> The lists referenced here live in `config/search_profile.json`; this document is the
> human-readable contract the `ranker` agent reads.

---

## 1. Pipeline order

Gates run before scoring. A gate failure ends the evaluation — a skipped role never
gets a score, and no score can rescue it.

```
dedup (seen_jobs.csv) → geo gate → hard gates (visa/ITAR) → domain classification → score → verdict
```

## 2. Domain classification

Each posting is labelled by `classify_domain()` using `config/search_profile.json`:
company keywords are checked first, then title keywords, then the default bucket.

| Priority | Domain | Why it matters to you |
|---|---|---|
| 1 | [DOMAIN_1] | [ONE_LINE_REASON] |
| 2 | [DOMAIN_2] | [ONE_LINE_REASON] |
| 3 | [DOMAIN_3] | [ONE_LINE_REASON] |
| — | [DEFAULT_DOMAIN] | Everything else that clears the gates |

## 3. Hard gates (auto-skip; score is irrelevant)

Enforced by verbatim regex in `gate_and_score.py`. Each skip records the exact quoted
snippet so you can audit the decision.

| Gate | Trips on | Applies to you? |
|---|---|---|
| Citizenship | "U.S. citizens only", "citizenship required" | [YES/NO — set from work authorization] |
| Security clearance | "active secret", "TS/SCI", "DoD clearance" | [YES/NO] |
| ITAR / export control | "ITAR", "export control", "US person status" | [YES/NO] |
| No sponsorship | "will not sponsor", "unable to sponsor" | [YES/NO] |
| PR / green card only | "permanent resident only" | [YES/NO] |
| Geography | any entry in `search.blocked_locations` | Always |
| Known non-sponsor | any key in `known_non_sponsors` | [YES/NO] |

**If you do not need sponsorship, set the four visa gates to NO during `/setup`** — leaving
them on will silently discard most of your real market.

### Overrides

The only sanctioned ways past a gate:
1. The posting explicitly contradicts the gate elsewhere (quote both).
2. You have a verified referral who confirms the policy does not apply.

Nothing else. "Probably fine" is not an override.

## 4. Scoring model (0–100)

| Axis | Points | What earns them |
|---|---|---|
| **A. Sponsorship odds** | 30 | Cross-referenced against `data/uscis_h1b_lookup.json`. Employers with recent approvals score high; no history scores low. [If you need no sponsorship, `/setup` redistributes these 30 points across B and C.] |
| **B. Skills / role fit** | 30 | Density of `master_toolkit` terms in the JD, weighted by how central they are to the posting's requirements rather than raw count. |
| **C. Seniority fit** | 20 | Title and stated experience range against your band: **[SENIORITY_BAND]**. A posting two levels above you scores near zero even with perfect skill overlap. |
| **D. Domain priority** | 10 | Full marks for [DOMAIN_1], scaling down to the default bucket. |
| **E. Logistics & integrity** | 10 | Location fit, posting recency, verified employer (not a staffing agency reposting a phantom role). |

## 5. Verdict + routing

| Score | Verdict | Action |
|---|---|---|
| ≥ [NETWORK_THRESHOLD] | **Apply + network** | Tailor a resume *and* flag for contact discovery |
| [APPLY_THRESHOLD] – [NETWORK_THRESHOLD] | **Apply** | Tailor a resume, direct apply |
| < [APPLY_THRESHOLD] | **Drop** | Logged to `seen_jobs.csv`, no resume built |

Caps that override the score:
- Max **[MAX_PER_COMPANY]** roles per company per day.
- Max **[DAILY_CAP]** applications per day.

## 6. Employer-quality handling

Companies in `staffing_agencies` are not auto-skipped, but they lose the integrity points
in axis E and never earn the anchor bonus. A staffing agency posting still worth applying
to is one where the end client is named in the JD.

## 7. Confidence

Report **low** confidence whenever the JD text was truncated, the posting is older than
[STALE_DAYS] days, or the employer could not be resolved. A low-confidence high score is a
prompt to read the JD yourself, not to apply on autopilot.

## 8. Output contract

The shortlist table shows, per row: rank, company, role, location, score, verdict, track,
confidence, the one-line reason, and any gate flags. `.pipeline/ranked.json` carries the
same rows in machine form for the customiser.
