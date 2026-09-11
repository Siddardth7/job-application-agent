---
name: resume-customise
description: Tailor and verify one-page ATS resumes only for Fortify shortlist rows Sid approved at Gate A, using the grounded candidate inventory and required Apply/Archive layout.
---

# Resume Customise

Read `AGENTS.md`, `DAILY_RUN.md`, `playbook/P1_03_resume_customization_rules.md`,
`data/candidate_resume_database.json`, relevant JDs, and
`Resume/Final_Resumes/Resume_NewStrategy_Master.tex`. Use current `tools/customise_resume.py` and
`tools/verify_pdf.py`. Require explicit Gate-A selection. Tailor sequentially and truthfully. Put final
PDFs only in `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/Apply/`; put TeX under `Archive/src/` and
build assets under `Archive/`. Reject PDFs that are not exactly one page, lack a clean ATS layer,
contain replacement glyphs, or violate ASCII-hyphen dates. Write `.pipeline/tailored.{json,md}`.
Never modify masters, apply, sync, or send.
