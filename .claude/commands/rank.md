---
description: Score one hand-found role with the same formula the daily run uses (standalone — no full apply-run). Delegates to the ranker subagent.
---
Score ONE role: $ARGUMENTS

Standalone entry to the `ranker` subagent (`.agents/skills/ranker/SKILL.md`), for a role you found
yourself. The score is the same one `/apply-run` produces; nothing is written to the seen ledger.

1. Get the role from `$ARGUMENTS`: a LinkedIn job URL, or company + title + the JD text. Without
   a JD the coverage axis cannot run, so ask for the text or the URL.
2. Put it through Pass 0 and the scorer without touching today's batch:
   `python3 tools/fetch_jobs.py --pass=0 --url=<url>` (or `--jds=<folder>` for a Markdown JD),
   then `python3 tools/gate_and_score.py --no-ledger --no-carry`.
3. Relay the bucket, the score, the five sub-scores with their reasons, the claimable / adjacent /
   gap keyword lists, and any Gate 0 or caution note. Stop there.
