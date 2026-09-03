# Templates

Starting points, not finished documents. `/setup` copies what you choose into place and
fills it in. Everything here is generic — replace every `[BRACKET]` with your own material.

## `resume_master.tex`

An ATS-safe one-page LaTeX resume: no tables for layout, no text in graphics, a clean
extractable text layer, and `\pdfgentounicode=1` so copy-paste out of the PDF returns real
characters. Those properties are why the pipeline can verify its own output.

**You do not have to use it.** At setup you'll be asked whether you're bringing your own
template — your existing `.tex`, an Overleaf project, or a Word/Docs resume — or starting
from this one. Bringing your own is a first-class path; the pipeline tailors whatever
master you point it at.

### Using it

```bash
cp templates/resume_master.tex Resume/Final_Resumes/Resume_Master.tex
# replace every [BRACKET], then:
cd Resume/Final_Resumes && pdflatex Resume_Master.tex
```

**On Overleaf:** New Project → Upload Project → drop in `resume_master.tex`. Set the
compiler to pdfLaTeX (Menu → Compiler). Download the `.tex` back into
`Resume/Final_Resumes/` when you're happy with it — the pipeline needs the source, not
just the PDF.

### One resume, or several?

Most people need **one**. The template works as-is with no extra files, and the pipeline
still tailors it per posting by reordering skills and rephrasing bullets to match the
posting's language.

If you apply across genuinely different role families and want structurally different
resumes, add a one-line stub per variant next to the master:

```latex
% Resume_Aerospace.tex
\def\ResumeType{1}\input{Resume_Master.tex}
```

Then wrap variant-specific content in the master with `\ifnum\ResumeType=1 ... \fi`.
`\ResumeType=6` switches to the two-page layout. Setup asks which you want and writes the
stubs for you.

### Rules the pipeline enforces on whatever master you use

1. Everything in it must be **true** and must also exist in
   `data/candidate_resume_database.json`. Tailoring reorders and rephrases; it never invents.
2. It must compile with `pdflatex` and fit the page limit — `tools/verify_pdf.py` fails the
   build otherwise, rather than shipping an overflowing resume.
3. Metrics are copied, never estimated. A bullet with no number stays without one.
