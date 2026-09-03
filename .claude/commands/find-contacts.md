---
description: Find + rank referral contacts for one company/role (standalone — no full apply-run, no drafts unless asked). Delegates to the contact-finder subagent.
---
Find referral contacts for ONE role: $ARGUMENTS

Standalone entry to the `contact-finder` subagent — use when you want referral contacts sourced and
ranked for a single posting he already has, outside `/apply-run`. **Drafting is off by default** — this
finds and ranks contacts only, unless `$ARGUMENTS` explicitly asks for drafts.

1. Get the role facts from `$ARGUMENTS` (company, company_slug, role title, location, job_url,
   target keywords). If `job_url` or company is missing, ask.
2. Delegate to the **contact-finder** subagent for this single posting, telling it to use these facts
   **instead of `.pipeline/ranked.md`** and to drive the networking runner per `DAILY_RUN.md` Step 8
   (discover location + alumni passes → classify → ingest → link). **Stop after linking (8·2) — do not
   draft (8·3) unless `$ARGUMENTS` explicitly asked for drafts.**
3. Relay the ranked contacts and the ≥5-at-location count/shortfall. If drafts were requested and
   produced, relay those too — ready for you to review. **Never send** — you do every send.
