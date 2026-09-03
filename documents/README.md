# Documents Folder

Drop your real career documents here, then run `/setup` and choose **Path A**. Setup reads
everything in this folder, cross-checks it for consistency, and builds your profile and
resume truth-source from actual source material rather than from memory.

**This entire folder is gitignored.** Nothing you put here will ever be committed.

```
documents/
├── resume/        # Your master resume (.pdf or .tex) — the most complete version you have
├── linkedin/      # LinkedIn profile export (Settings → Get a copy of your data → PDF)
├── transcripts/   # Degree certificates and transcripts
└── references/    # Reference letters and recommendations
```

## What setup takes from each

**`resume/`** — contact details, education, every role (title, company, dates, bullets),
skills, tools, projects, certifications. Metrics are captured **verbatim**: a number that
isn't in your resume won't appear in a tailored one.

**`linkedin/`** — your headline and About text, which is the best available sample of how
you describe your own work. The contact-finder reuses that voice when it drafts outreach,
so an export here makes outreach sound like you instead of like a template.

**`transcripts/`** — the official spelling of your degree and institution, and your
graduation date. Resumes and LinkedIn profiles disagree about these more often than you'd
think; setup will surface the conflict rather than guess.

**`references/`** — referee details and the specific competency language they used. Useful
when a posting asks for references, and as evidence for claims you'd otherwise hesitate to make.

## Tips

- More is better. Setup cross-references documents against each other, so two sources
  catch errors that one source can't.
- If you only have a resume, that's fine — Path B handles a single file.
- Re-run `/setup` whenever you add something. It merges rather than overwrites, and asks
  before changing anything you've already confirmed.
