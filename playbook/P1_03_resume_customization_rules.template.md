# Resume Customization Rules (template)

> `/setup` fills the `[BRACKETED]` values and writes
> `playbook/P1_03_resume_customization_rules.md`. The `customiser` agent and
> `tools/customise_resume.py` both read it. The truth rules below are not optional and
> `/setup` will not offer to weaken them.

---

## 1. The truth rule

**Every claim in a tailored resume must already exist in `data/candidate_resume_database.json`.**

Tailoring means *selecting, reordering, and rephrasing* what is already true. It never means:
- inventing an employer, title, date range, degree, or certification
- inventing a metric, or sharpening a real one ("reduced scrap" → "reduced scrap 40%")
- claiming a tool you have not used because the JD asks for it
- moving a project from coursework to professional experience

If the JD demands something you do not have, the answer is a lower score — not a better story.
A fabricated line survives the ATS and dies in the interview.

## 2. What gets tailored

| Section | Tailoring allowed |
|---|---|
| Contact / Education | None. Fixed. |
| **Skills** | Reorder and subset. Surface the JD's vocabulary *where you genuinely have it*. Never append a skill that isn't in the database. |
| **Experience bullets** | Reorder within a role, and rephrase to use the JD's terminology for the same underlying work. Never reorder roles chronologically out of order. |
| **Projects** | Select the [N_PROJECTS] most relevant from the database and order by relevance. |
| Summary | [OMITTED / INCLUDED — set during `/setup`] |

## 3. Vocabulary matching

The JD says "process capability studies", your database says "Cpk analysis". Those are the
same work — use the JD's phrase. The JD says "Design of Experiments", your database says
"DOE" — spell it out. This is legitimate and it is most of the value.

The line: **rephrase the label, never upgrade the substance.** "Supported PFMEA sessions"
may become "Contributed to PFMEA development". It may not become "Led PFMEA development".

## 4. Layout constraints

- **[PAGE_LIMIT] page(s) hard limit**, enforced by `tools/verify_pdf.py`. A resume that
  overflows is a failed build, not a warning.
- ASCII dates, no ligature glyphs, no unescaped LaTeX characters — the PDF text layer is
  extracted and checked so the ATS parses it cleanly.
- Master template: `Resume/Final_Resumes/Resume_NewStrategy_Master.tex`. One template for
  every track; the track label steers emphasis and section order, not which file is opened.

## 5. Output

- Final PDF → `Job_Applications_Resumes/<Month>/<YYYY-MM-DD>/Apply/`
- LaTeX source + build log → `.../Archive/`
- Filename: `resume_<Company><Role>.pdf`, non-alphanumerics stripped.

## 6. Self-check before handoff

The customiser reports nothing as done until all four pass:
1. The PDF exists and `verify_pdf.py` returned clean.
2. Page count is within the limit.
3. The company name appears in the compiled text layer.
4. The file differs from the base template — an unmodified copy means tailoring silently failed.
