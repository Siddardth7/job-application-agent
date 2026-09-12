---
name: resume-customise
description: Tailor and verify one-page ATS resumes only for shortlist rows Sid approved at Gate A, from the single master template, with the customiser's hard self-check gate.
---

# Resume Customise

Read `AGENTS.md`, `DAILY_RUN.md` Stage 3, `playbook/P1_03_resume_customization_rules.md`, the
approved rows in `.pipeline/ranked.json` (JD text is the `description` field — there are no per-job
JD files), and `Resume/Final_Resumes/Resume_Master.tex`. Follow `.codex/agents/customiser.toml`
exactly: it is the same spec as `.claude/agents/customiser.md`. Require explicit Gate-A selection.
Tailor sequentially and truthfully: reorder and reword, never rename an entry, never name a method
absent from the base bullet or the P1_03 inventory — the master template wins over the playbook.
Diff every output against `python3 tools/resolve_track.py <N>`; reject any that does not touch
Skills, any with a company name, any that is not exactly one page with zero bad boxes. Write PDFs to
`Job_Applications_Resumes/<YYYY-MM-DD>/` and sources to `src/` beside them; write
`.pipeline/tailored.md`. Never modify masters, apply, sync, or send.
