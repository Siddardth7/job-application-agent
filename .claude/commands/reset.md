# /reset — Clear personal data

Return this clone to its shipped state so it can be handed to someone else, or so you can
re-onboard from scratch. Destructive: it deletes real work.

## Step 0: Scope

`$ARGUMENTS` may name a scope. Default is `profile`.

- **`profile`** — the setup output: `profile.md`, `config/search_profile.json`,
  `data/candidate_resume_database.json`, `playbook/P1_03_*.md`, `playbook/P1_06_*.md`,
  `company_intel.md`, and the personalized header in
  `Resume/Final_Resumes/Resume_NewStrategy_Master.tex`.
- **`history`** — runtime state: `seen_jobs.csv`, `tracker_data.json`, `.pipeline/*`,
  `daily_run/`, `JDs/`, `learning_log.md`.
- **`documents`** — everything under `documents/` except the `.gitkeep` files and README.
- **`all`** — all three.

## Step 1: Show exactly what will go

List the affected files **that actually exist**, with size and last-modified date. Never
show a file that isn't there — it makes the list impossible to audit.

Call out irreplaceable losses explicitly:
- `seen_jobs.csv` is the dedup ledger. Clearing it means every previously-evaluated posting
  comes back as new on the next run.
- `data/candidate_resume_database.json` may hold facts the user typed in during setup that
  exist nowhere else.
- `Job_Applications_Resumes/` is **never** touched by reset — submitted resumes are records.
  Say so, so the user knows their applications survive.

## Step 2: Confirm

Require the user to type the scope word back (`profile`, `history`, `documents`, or `all`).
A "yes" is not enough for a destructive action. If they hesitate or ask questions, answer
and re-ask — do not proceed on ambiguity.

## Step 3: Execute

Delete the scoped files. For `profile`, restore the templates so the tree stays valid:
`profile.template.md` and the two `playbook/*.template.md` files stay in place, and
`config/search_profile.example.json` becomes the active fallback again.

## Step 4: Report

State what was cleared, what was left alone, and that `/setup` is the way back.
