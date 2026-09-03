# /setup — Onboarding

You are onboarding a new user onto this job-search pipeline. Your goal: turn an empty
clone into a working, *personalized* cockpit — so that `/apply-run` searches for their
roles, scores against their profile, and tailors from their real experience.

Nothing in this repo works until setup runs. The shipped `config/search_profile.example.json`
carries the template author's targets; running the pipeline on it scores every posting
against the wrong candidate.

Three paths into setup. **Step 0** picks one; all three converge on **Step 2** (generation)
and **Step 3** (confirmation).

---

## Step 0: Privacy pre-flight, then choose a path

### 0a. Check where this clone publishes — before writing anything

Run `git remote get-url origin`. If it fails (no remote, not a checkout), skip silently.

If there is a GitHub origin, run `gh repo view <owner/repo> --json visibility,isFork` when
`gh` is available. If the origin is **public** — or visibility can't be determined — stop
and warn:

> **Before we start:** your `origin` is `<owner/repo>`, which is public. Setup writes your
> name, contact details, work authorization, and employment history to disk. Most of those
> files are gitignored, but a public remote is one `git add -f` away from exposing them.
>
> Two safe options: keep this clone local and never push, or point `origin` at a **private**
> repo (`gh repo create <name> --private --source=. --remote=origin`). See SETUP.md §6.
>
> Continue?

Wait for confirmation. A private origin, or no origin, needs no warning.

### 0b. Detect prior setup

Check for `profile.md` and `config/search_profile.json`. If either exists, this is a re-run:
say what's already configured and ask whether to **update specific sections** (jump to the
matching Path C section) or **start over** (confirm explicitly, then continue).

If `$ARGUMENTS` contains `--section <name>`, skip path selection entirely and run only that
section. Valid names: `profile`, `search`, `resume`, `gates`, `env`, `portals`.

### 0c. Offer the paths

Scan `documents/` with Glob (`documents/**/*`) and count files per subfolder. Then:

> **Welcome.** I'll build your search profile so the pipeline sources, scores, and tailors
> for *you* rather than for the template author.
>
> [If documents/ has files: "I see files in `documents/`: <list per subfolder>."]
>
> **Path A — Read my documents folder** [recommended when files were found]. Drop your
> resume, LinkedIn export, and transcripts in `documents/`; I read them, cross-check for
> inconsistencies, and build everything from real source material. Safe to re-run as you
> add more.
>
> **Path B — Single resume import.** Paste or @-mention one resume. I extract it and ask
> follow-ups for the gaps.
>
> **Path C — Interview me.** Structured questions, section by section. Best if you're
> starting from scratch.
>
> Which one?

If they pick A and `documents/` is empty, point at `documents/README.md` and stop.

---

## Path A: Documents folder

### A1. Inventory
Glob `documents/**/*`. Print what was found per subfolder (`resume/`, `linkedin/`,
`transcripts/`, `references/`). If all empty, stop and point at `documents/README.md`.

### A2. Parse
Read every file. Extract, in this order:

- **`resume/`** — name, contact, education (degree, institution, dates, thesis), each role
  (title, company, dates, location, bullets), skills, tools, projects, certifications.
  **Capture metrics verbatim.** "Reduced scrap 18%" is a fact you may later use; "reduced
  scrap significantly" is not, and must not become a number.
- **`linkedin/`** — headline, About text (this is the best source for the candidate's own
  voice — the contact-finder reuses it), roles, skills, certifications, recommendations.
- **`transcripts/`** — official degree title and institution spelling, graduation date, GPA
  if present.
- **`references/`** — referee name/title/org, and direct quotes about competencies.

### A3. Cross-reference
Before writing anything, check for: date mismatches across resume/LinkedIn, title
mismatches for the same role, degree-name or graduation-date mismatches, employer name
variants. Present any conflicts as a numbered list and **resolve each with the user** —
the resume database is a truth source and a wrong date there propagates into every
tailored PDF.

### A4. Fill the gaps
Documents rarely cover: work authorization, sponsorship need, seniority band, target
domains, anchor companies, deal-breakers, daily caps. Ask for these using the Path C
sections 4–7 questions. Then go to Step 2.

---

## Path B: Single resume import

Read the resume, extract everything in A2's `resume/` list, present a summary of what you
got, then ask the Path C sections 1–7 questions for whatever is missing. Go to Step 2.

---

## Path C: Interview mode

Conversational, not a form. Let them answer in prose; you do the structuring. Optional
sections can be skipped.

**1. Identity & contact.** Name, city/state, email, phone, LinkedIn, portfolio. Schools
attended — the contact-finder uses these to find alumni for warm intros.

**2. Education.** Each degree: level, field, institution, dates, thesis. Certifications.

**3. Experience.** Each role, most recent first: title, company, dates, location, 3–5
responsibilities, key achievements, tools used. Also internships, co-ops, research, and
independent projects — for early-career candidates these often carry the strongest metrics.

**Push for numbers.** "What changed because you were there?" produces better material than
"what were your responsibilities?". Record only what they actually state. If they say they
don't remember the number, record the achievement without one — never estimate on their behalf.

**4. Work authorization & gates.** This is the highest-leverage answer in the whole setup:

> Are you a US citizen or permanent resident, or will you need visa sponsorship?

- **Needs sponsorship** → keep all visa/ITAR gates ON, keep the 30-point sponsorship axis,
  keep `data/uscis_h1b_lookup.json` in play.
- **Citizen / PR** → turn the four visa gates OFF and redistribute the 30 sponsorship points
  across skills fit and seniority fit. Say plainly that leaving them on would discard most
  of their real market.
- Also ask: clearance-eligible? Any geography they will not accept?

**5. Target roles.** Ask the function first — "what do you actually want to be doing
day-to-day?" — then translate into 3–8 searchable titles. The same work is called different
things at different employers; catch the variants. Then: which 3–5 skills are most likely to
literally appear in postings? Which domains, in priority order? Any anchor companies to watch?

**Suggest titles they haven't considered**, based on their skill mix. This is where people
discover half their market.

**6. Logistics.** Seniority band. Cities/regions in scope, and commute limit. Countries to
block. Deal-breakers (shift work, travel %, industries to avoid).

**7. Run parameters.** Daily application cap (default 10), max per company per day (default
2), score to shortlist (default 50), score to flag for networking (default 60), Apify daily
spend cap (default $0 — free ATS sourcing only).

---

## Step 2: Generate

Write these. For Path A, skip any file the earlier steps already populated.

1. **`config/search_profile.json`** — copy `config/search_profile.example.json` and replace
   *every* profile-specific field: `candidate`, `search.role_titles`,
   `search.peer_role_keywords`, `search.blocked_locations`, `target_anchors`,
   `master_toolkit`, `domains`, `default_domain`.
   **Clear `known_non_sponsors` and `staffing_agencies` back to the generic entries** — the
   example's non-sponsor list is one candidate's hard-won research, and inheriting it blind
   would silently skip employers who would in fact sponsor this user.
   This is the file the pipeline actually executes on; getting it right matters more than
   any prose file below.

2. **`profile.md`** — from `profile.template.md`, every `[BRACKET]` replaced. Read by the
   fetcher, ranker, and contact-finder on every run.

3. **`data/candidate_resume_database.json`** — from
   `data/candidate_resume_database.template.json`, filled with their real experience.
   **This is the truth source**: the customiser may only make claims that appear here. Every
   metric must be one the user actually stated. Where a bullet has no metric, leave it
   without one.

4. **`playbook/P1_06_scoring_rubric.md`** and **`playbook/P1_03_resume_customization_rules.md`**
   — from the two `.template.md` files, brackets filled from sections 4–7. Set the gate
   YES/NO column from the work-authorization answer.

5. **`Resume/Final_Resumes/Resume_NewStrategy_Master.tex`** — replace the placeholder header
   (name, contact, links) and seed education plus the most recent role. Tell the user this is
   their master template to refine by hand; the customiser tailors *from* it and never rewrites it.

6. **`.env`** — copy `.env.example` if `.env` is absent. Do not ask for secret values in
   chat; tell them which keys to paste in themselves. Supabase and Apify are both optional —
   the pipeline runs free and local without either.

7. **`tools/portals.json`** — add career-page URLs for their anchor companies. Keep the
   shipped generic ATS boards; those cost nothing.

8. **`company_intel.md`** — start it with any sponsorship or hiring policy the user already
   knows first-hand. Empty is fine; it grows as they learn.

**Never write to** `seen_jobs.csv`, `tracker_data.json`, or anything under
`Job_Applications_Resumes/` — those are runtime state, not setup output.

---

## Step 3: Confirm

Summarize what was written, then:

> **Setup complete.** Configured:
> - `config/search_profile.json` — your search targets and scoring inputs
> - `profile.md` — the profile every agent reads
> - `data/candidate_resume_database.json` — your truth source for resume tailoring
> - `playbook/` — your scoring rubric and customization rules
> - `Resume/Final_Resumes/Resume_NewStrategy_Master.tex` — your master template
>
> **All of these are gitignored.** They hold your personal data; keep them that way.
>
> **Next:**
> 1. Refine the master `.tex` by hand and compile it once (`python3 tools/verify_pdf.py`)
>    so you know the build works before a real application depends on it.
> 2. Run `/fetch` to see what sourcing finds for your titles.
> 3. Run `/apply-run` for the full daily pipeline.
> 4. Run `/setup --section search` any time your targets shift.

Flag anything left incomplete — especially resume-database entries with missing dates or
un-numbered achievements the user wanted to quantify later.

---

## Rules

1. **Never invent candidate facts.** Every entry in the resume database traces to a document
   the user supplied or a sentence they typed. A metric you smoothed in here becomes a
   fabrication in every resume the pipeline builds.
2. **Gates follow authorization, not optimism.** Do not turn visa gates off to widen results
   for someone who needs sponsorship; do not leave them on for a citizen.
3. **Read before write.** On a re-run, load existing files first and merge — never clobber
   work the user has hand-edited since the last setup.
4. **Secrets stay out of chat.** Point at `.env`; never ask the user to paste a key to you.
5. **Personal files stay gitignored.** If you ever find one tracked, say so immediately.
