# Setup Guide

From `git clone` to your first tailored resume. Budget 20 minutes, most of it waiting on
LaTeX to install.

---

## 1. Prerequisites

| Tool | Why | Install |
|---|---|---|
| **Python 3.10+** | Core pipeline | Preinstalled on macOS/Linux; [python.org](https://python.org) on Windows |
| **Node.js 18+** | ATS board scanners | [nodejs.org](https://nodejs.org) |
| **LaTeX** | Compiles resumes to PDF | macOS: `brew install --cask mactex-no-gui` (or `basictex`)<br>Ubuntu: `sudo apt install texlive-latex-base texlive-latex-extra texlive-fonts-recommended`<br>Windows: [MiKTeX](https://miktex.org/) |
| **Claude Code** *(or Antigravity / Codex)* | Runs the agents | [claude.com/code](https://claude.com/code) |

Check `pdflatex --version` resolves before continuing. Nothing downstream works without it.

## 2. Clone — privately

**Do not fork this repo publicly and then run setup in it.** Setup writes your name,
contact details, work authorization, and employment history to disk. Those files are
gitignored, but the safest arrangement is a private remote from the start:

```bash
git clone https://github.com/Siddardth7/job-application-agent.git my-job-search
cd my-job-search
rm -rf .git && git init            # drop the upstream history

gh repo create my-job-search --private --source=. --remote=origin
```

Keeping it fully local (no remote at all) is equally fine.

## 3. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Add your documents (optional, but do it)

Drop your resume, LinkedIn export, and transcripts into `documents/` — see
`documents/README.md` for the layout. Setup builds a far better profile from real documents
than from an interview, and it cross-checks them against each other to catch the date and
title mismatches that would otherwise end up in every resume you send.

## 5. Run setup

In Claude Code, from the repo root:

```
/setup
```

It picks a path based on what's in `documents/`, asks what it can't read, and writes:

| File | What it drives |
|---|---|
| `config/search_profile.json` | **The one that matters.** Search titles, scoring keywords, domains, blocked geographies, gate lists |
| `profile.md` | Read by the fetcher, ranker, and contact-finder every run |
| `data/candidate_resume_database.json` | Truth source — the customiser may only claim what's in here |
| `playbook/P1_06_scoring_rubric.md` | Your scoring rubric and thresholds |
| `playbook/P1_03_resume_customization_rules.md` | Your tailoring rules |
| `Resume/Final_Resumes/Resume_Master.tex` | Your master template — your own file, or `templates/resume_master.tex` filled in |
| `tools/portals.json` | Career boards for your anchor companies |
| `company_intel.md` | Your own employer notes (starts empty) |
| `.env` | Optional Supabase and Apify keys |

All are gitignored.

**Until `/setup` runs**, the pipeline falls back to `config/search_profile.example.json` —
the template author's profile. It will run, and it will score every posting against the
wrong candidate. Run setup first.

Re-run any section later with `/setup --section search` (or `profile`, `resume`, `gates`,
`env`, `portals`).

## 6. Optional: Supabase tracking

Only needed for a cloud-synced tracker across devices. `supabase/README.md` has the
three-minute version: create a free project, run `schema.sql`, put `SUPABASE_URL` and
`SUPABASE_KEY` in `.env`, then `python3 refresh.py` to write `job_tracker.html` — a standalone
page you bookmark. It reads your tables live on every open (paste the key into it once; it
stays in your browser), so every tool you run the pipeline from feeds the same tracker.

Without it, the pipeline still runs; applications are logged to `seen_jobs.csv` only.

## 7. Optional: Apify LinkedIn sourcing

Direct ATS scanning across 44+ boards is free and runs by default. Apify adds LinkedIn
coverage for a few cents a day. Set `APIFY_TOKEN` in `.env` and a spend cap in `profile.md`.

## 8. First run

```
/fetch          # see what sourcing finds for your titles
/apply-run      # the full daily pipeline, with human gates
```

Setup compiles your master once and reports the page count. To rebuild it yourself:

```bash
cd Resume/Final_Resumes && pdflatex Resume_Master.tex
```

### Bringing your own resume

Setup asks whether you're supplying your own LaTeX/Overleaf template or starting from
`templates/resume_master.tex`. If it's an Overleaf project, download the source first
(Menu → Download → Source) — the pipeline tailors `.tex`, not PDFs. Your file is used
verbatim; nothing is restyled. Details in [`templates/README.md`](templates/README.md).

## 9. Interview prep

Once something converts:

```
/interview ja-0901-01          # by tracked job ID
/interview <posting URL>       # by link
/interview                     # pick from your live applications
```

It pulls the resume you actually submitted plus the JD, asks which round and who's
interviewing, and writes a full prep manual to `Interview_Prep/`.

## 10. Handing the repo on

`/reset` clears personal data back to templates — `profile`, `history`, `documents`, or `all`.
It never touches `Job_Applications_Resumes/`; submitted resumes are records.

---

## Troubleshooting

**`No search profile found`** — `/setup` hasn't run, and `config/search_profile.example.json`
is missing. Restore it from the repo.

**Pipeline returns nothing relevant** — you're probably still on the example profile. Check
`config/search_profile.json` exists; if not, run `/setup`.

**Everything is skipped as a visa risk** — the visa gates are on. If you're a citizen or
permanent resident, run `/setup --section gates` and turn them off.

**`pdflatex: command not found`** — LaTeX isn't on `PATH`. On macOS add
`/Library/TeX/texbin`; restart your shell after installing.

**Resume overflows one page** — that's an intentional hard failure. Trim the master template
or raise the limit in `playbook/P1_03_resume_customization_rules.md`.
