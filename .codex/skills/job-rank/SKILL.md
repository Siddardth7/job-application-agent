---
name: job-rank
description: Run or audit Stage 2 Gate 0 eligibility screening and fit scoring for the Fortify workspace, producing the ranked shortlist for Sid's approval.
---

# Job Rank

Read `AGENTS.md`, `DAILY_RUN.md`, `profile.md`, `company_intel.md`, `learning_log.md`, and current
`tools/gate_and_score.py`. Score `.pipeline/fetched.json`; ignore stale hand-picked-only and referral
rules. ITAR, export-control, citizenship-only, clearance, or explicit no-sponsor failures are
`VISA RISK (SKIP)` with posting evidence. Preserve T1/T2 routing and at most two roles per employer per
day. Write `.pipeline/ranked.{json,md}`, present the audit, and stop at Gate A. Never tailor, log,
apply, or send.
