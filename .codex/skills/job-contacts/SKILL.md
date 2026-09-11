---
name: job-contacts
description: Research or persist recruiter and team-lead contacts for selected Fortify roles while enforcing Supabase contacts as the only store and leaving all outreach for Sid to send.
---

# Job Contacts

Read `AGENTS.md` and `DAILY_RUN.md` Source Contacts Place. Verify current employment and invent no
contact details. The only store is `public.contacts` in Supabase project `chsrkysjongzgdbwqhlu`.
Normal persistence belongs to `tools/log_and_refresh.py`; ad-hoc persistence uses
`networking_sheet.py add` with a valid job ID, followed by `./refresh.sh --fetch`. Do not create
Markdown, spreadsheet, or SQLite contact ledgers. Never send outreach. Draft only when explicitly asked.
