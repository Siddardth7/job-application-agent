---
description: Tailor one track resume for a single hand-found role (standalone — no full apply-run). Delegates to the customiser subagent.
---
Tailor a resume for ONE role: $ARGUMENTS

Standalone entry to the `customiser` subagent — use when Sid finds a role himself and just wants
the resume, outside `/apply-run`.

1. Get the role facts from `$ARGUMENTS` (company, title, JD text or URL, and track if known). If any
   are missing, ask Sid — do not guess a JD.
2. If the track isn't given, infer it per `playbook/P1_06_scoring_rubric.md` §2.5
   (T1 Track1_Semiconductor_QE / T2 Track2_Aerospace / T3 Track3_Quality_Systems).
3. Delegate to the **customiser** subagent for this single role, telling it to use these facts as its
   input **instead of `.pipeline/ranked.md`**, and to write the tailored resume to
   `Job_Applications_Resumes/<today>/` per `playbook/P1_03_resume_customization_rules.md`.
4. Relay the `.tex`/`.pdf` path and the P1_03 3-line change summary. Do not apply or send — Sid applies.
