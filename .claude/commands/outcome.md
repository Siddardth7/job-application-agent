---
description: Log an interview, offer, rejection or drop for an application
---
Update the tracker for: $ARGUMENTS. Find the job_id (Supabase applications, or ask), then run
`python3 tools/log_apps.py status JOB_ID interviewing|offer|rejected|dropped --note "stage or reason"`.
For a rejection, capture the reason or the email wording in the note. If a pattern shows up across several outcomes, say so and propose a rule change; do not change rules silently.
