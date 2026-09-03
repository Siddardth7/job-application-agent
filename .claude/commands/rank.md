---
description: Score one hand-found role against the rubric (standalone — no full apply-run). Delegates to the ranker subagent.
---
Score ONE role: $ARGUMENTS

Standalone entry to the `ranker` subagent — use when Sid finds a role himself and wants to know its
score, lane, and whether it's referral-worthy, outside `/apply-run`.

1. Get the role facts from `$ARGUMENTS` (company, title, JD text or URL). If the JD isn't provided,
   ask for it or the URL — the gates and skills score read the JD, not the title.
2. Delegate to the **ranker** subagent for this single role, telling it to use these facts as its
   input **instead of `.pipeline/fetched.md`**, and to apply `playbook/P1_06_scoring_rubric.md`
   (track classify → hard gates → per-track score → lane routing).
3. Relay the sub-scores, TOTAL, lane (Referral ≥80 / Direct-apply 45-79 / Drop), and referral-needed.
   Nothing is written to live stores in standalone mode unless Sid asks.
