#!/usr/bin/env python3
"""
tailor.py - per-job resume pass from a lane base (playbook/P3_resume_rules.md).

  python3 tools/tailor.py .pipeline/keeps_candidates.json [--date YYYY-MM-DD]
      input: [{"company", "title", "location", "description", "lane": "A".."D", ...}, ...]
      output: Job_Applications_Resumes/<date>/resume_<Company>_<Role>.tex/.pdf + tailor_notes.md,
              .pipeline/keeps_queue.json for `log_apps.py queue`,
              outputs/<date>/apply_list.md (apply table + per-job networking brief for Sid's ChatGPT networking)
  python3 tools/tailor.py --self-test

Light pass only, never new claims: reorder Skills items and the bullets inside each entry by JD overlap,
and swap a term for its vetted JD equivalent (EQUIV). Entries, entry count and wording stay as the lane has them.
Fits each page by spacing (Resume/lanes/build_lanes.fit). Never reads Resume_Master.tex.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
LANES = ROOT / "Resume" / "lanes"
sys.path.insert(0, str(LANES))

# Same thing, JD's word. Only pairs Sid has confirmed as equivalent (P3: use the JD's term for equivalent work).
EQUIV = [("fishbone diagrams", "Ishikawa diagrams", r"ishikawa"), ("fishbone", "Ishikawa", r"ishikawa")]
# Terms reported in the three-line note (mirrored = in JD and resume; gap = in JD, not in resume).
TERMS = ["PFMEA", "FMEA", "control plan", "SPC", "8D", "5 Why", "Ishikawa", "fishbone", "CAPA", "root cause",
         "GD&T", "MRB", "NCR", "nonconform", "non-conform", "DOE", "MSA", "Gage R&R", "capability", "Lean", "5S",
         "Six Sigma", "DMAIC", "APQP", "PPAP", "Python", "Excel", "MATLAB", "SolidWorks", "SEM", "microscop",
         "composite", "prepreg", "layup", "cure", "sinter", "metrology", "CMM", "calibration", "SQL", "Minitab",
         "JMP", "cleanroom", "semiconductor", "battery", "polymer", "resin", "extrusion", "weld", "inspection",
         "Xbar", "documentation", "work instructions", "audit"]
STOP = set("with from that this were into across using under over about their through each every team".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9&+-]{3,}", text.lower()) if w not in STOP}


def score(item: str, jd_words: set[str]) -> int:
    return len(words(re.sub(r"\\[a-zA-Z]+|[{}$]", " ", item)) & jd_words)


def tailor_tex(tex: str, jd: str) -> str:
    jw = words(jd)
    # Skills: reorder items in the two lane lines (not Tools), stable for ties.
    def skills(m):
        label, items = m.group(1), [i.strip() for i in m.group(2).split(",")]
        return label + ", ".join(sorted(items, key=lambda i: -score(i, jw)))
    tex = re.sub(r"(\\textbf\{(?!Tools)[^}]+\}: )([^\n\\]+?)(?= \\\\\n)", skills, tex)
    # Bullets: reorder inside each entry, stable for ties.
    def block(m):
        items = re.findall(r"    \\resumeItem\{.*\}\n", m.group(2))
        return m.group(1) + "".join(sorted(items, key=lambda i: -score(i, jw))) + m.group(3)
    tex = re.sub(r"(\\resumeItemListStart\n)((?:    \\resumeItem\{.*\}\n)+)(  \\resumeItemListEnd)", block, tex)
    for old, new, cue in EQUIV:
        if re.search(cue, jd, re.I) and not re.search(r"fishbone", jd, re.I):
            tex = tex.replace(old, new)
    return tex


def slug(s: str, n: int = 40) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", s))[:n]


def note(tex: str, jd: str, lane: str) -> tuple[str, str]:
    def has(term, text):  # whole word, hyphen/space-insensitive ("root cause" == "root-cause"), SEM never inside "assembly"
        pat = re.escape(term.lower()).replace(r"\ ", r"[\s-]")
        return re.search(rf"(?<![a-z]){pat}", text.lower().replace("\\&", "&")) is not None
    hits = [t for t in TERMS if has(t, jd)]
    mirrored = [t for t in hits if has(t, tex)]
    gaps = [t for t in hits if not has(t, tex)]
    return ", ".join(mirrored) or "-", ", ".join(gaps) or "-"


CORE4 = ("tesla", "micron", "joby", "ast spacemobile", "ast & science")
FUNCTION = {"A": "Materials / Process Engineering", "B": "Quality Engineering", "C": "Process Engineering",
            "D": "Manufacturing Engineering"}
# ponytail: regex clue finder, misses teams named only in the title; the title + site line covers those
TEAM_CUE = re.compile(r"member of|join (?:our|the) [^.]{0,60}\bteam\b|reports? (?:directly )?to|reporting to|team is part of", re.I)


def clean(item: str) -> str:
    t = re.sub(r"\\resumeItem\{(.*)\}\s*$", r"\1", item.strip())
    t = re.sub(r"\\textbf\{([^}]*)\}", r"\1", t).replace("\\%", "%").replace("\\&", "&").replace("$\\sim$", "~")
    return re.sub(r"\\[a-zA-Z]+\{?|[{}$]", "", t).strip()


def brief(j: dict, tex: str, name: str, n: int) -> str:
    """Networking brief for one kept job: who to find, team clues, the 3 strongest true points."""
    jd, co, title = j.get("description") or "", j["company"], j["title"]
    tech = "technician" in title.lower()
    area = title.split(",", 1)[1].strip() if "," in title else ""
    small = not any(c in co.lower() for c in CORE4)
    func = next((f for k, f in (("quality", "Quality Engineering"), ("process", "Process Engineering"),
                                 ("manufactur", "Manufacturing Engineering"), ("material", "Materials Engineering"))
                 if k in title.lower()), FUNCTION[j["lane"]])
    who = [f"Hiring manager: {(area + ' ') if area else ''}{'production / engineering supervisor or lead technician' if tech else func + ' Manager'}",
           f"Team: a {'technician or engineer' if tech else func.split(' / ')[0].replace(' Engineering', '') + ' engineer'} on that team"
           f"{' at ' + j['location'] if j.get('location') else ''}",
           "Recruiter: the recruiter named on the posting, else the site's technical / university recruiter"]
    if small:
        who.insert(0, "Small company: founder, Head of Engineering or VP Operations often hire directly")
    clues = [re.sub(r"\s+", " ", x).strip()[:200] for x in re.split(r"(?<=[.!?])\s+|\n+", jd) if TEAM_CUE.search(x)][:2]
    points = [clean(b) for b in sorted(re.findall(r"\\resumeItem\{.*\}", tex), key=lambda b: -score(b, words(jd)))[:3]]
    q = quote(f"{co.split(',')[0]} {area or title.split(',')[0]}")
    lines = [f"## {n}. {co} · {title}", f"- Location: {j.get('location', '')} · Lane {j['lane']} · Score {j.get('score', '-')}"
             f" · Req {j.get('req_id') or '-'}", f"- Apply: {j.get('apply_url') or j.get('link')}", f"- Resume: `{name}.pdf`",
             f"- LinkedIn people search: https://www.linkedin.com/search/results/people/?keywords={q}",
             "- Who to find:"] + [f"  - {w}" for w in who]
    lines += ["- Team clues from the JD:"] + ([f"  - \"{c}\"" for c in clues] or ["  - none stated; use the title and site"])
    lines += ["- My strongest matching points (from this resume):"] + [f"  - {p}" for p in points]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    from build_lanes import fit  # noqa: E402  (lane fitter: loosest spacing that fits one page)
    jobs = json.loads(Path(argv[0]).read_text())
    tri = ROOT / ".pipeline" / "triage.json"   # fill a missing triage score so the tracker row keeps it
    scores = {(c.get("apply_url") or c.get("link")): c.get("score") for c in json.loads(tri.read_text())["candidates"]} if tri.exists() else {}
    for j in jobs:
        j.setdefault("score", scores.get(j.get("apply_url") or j.get("link")))
    day = next((a.split("=")[1] for a in argv if a.startswith("--date=")), date.today().isoformat())
    out = ROOT / "Job_Applications_Resumes" / day
    out.mkdir(parents=True, exist_ok=True)
    lines, seen, hashes, queue = [f"# Tailoring notes {day}\n"], {}, set(), []
    table, briefs = [], []
    for j in jobs:
        base = (LANES / f"Resume_Lane{j['lane']}.tex").read_text()
        tex = tailor_tex(base, j.get("description") or "")
        name = f"resume_{slug(j['company'].split(',')[0], 20)}_{slug(j['title'])}"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1 or sum(slug(k['title']) == slug(j['title']) and k['company'] == j['company'] for k in jobs) > 1:
            name += "_" + slug(j.get("location", "").split(",")[0], 12) + ("_Night" if "night" in j["title"].lower() else "")
        path = out / f"{name}.tex"
        ls = fit(path, tex)
        final = path.read_text()
        # customise self-check: target company never in the body, file unique, page fits
        co = re.sub(r"\s+(inc|llc|corp|corporation|technology|technologies|company)\.?$", "", j["company"].split(",")[0], flags=re.I)
        assert not re.search(rf"\b{re.escape(co)}\b", final, re.I), f"company name in {name}"
        h = hashlib.md5(final.encode()).hexdigest()
        dup = " (same text as another resume in this batch)" if h in hashes else ""
        hashes.add(h)
        mirrored, gaps = note(final, j.get("description") or "", j["lane"])
        changed = "base order kept" if final.replace(re.search(r"\\linespread\{[\d.]+\}", final).group(0), "") == \
            base.replace(re.search(r"\\linespread\{[\d.]+\}", base).group(0), "") else "skills/bullets reordered"
        lines.append(f"## {j['company']} · {j['title']} ({j.get('location', '')})\n- Lane {j['lane']}; {changed}; "
                     f"linespread {ls:.2f}{dup}. File: `{name}.pdf`\n- JD terms mirrored: {mirrored}\n"
                     f"- In JD, not claimed (no matching experience): {gaps}\n")
        for ext in (".aux", ".log", ".out"):
            path.with_suffix(ext).unlink(missing_ok=True)
        queue.append({k: j.get(k) for k in ("company", "title", "location", "link", "apply_url", "req_id", "score", "lane")}
                     | {"resume": f"{day}/{name}.pdf"})
        n = len(queue)
        table.append(f"| {n} | {j['company']} | {j['title']} | {j.get('location', '')} | {j['lane']} | {j.get('score', '-')} | "
                     f"{name}.pdf | [link]({j.get('apply_url') or j.get('link')}) |")
        briefs.append(brief(j, final, name, n))
        print(f"{name}: lane {j['lane']}, {changed}, ls {ls:.2f}{dup}")
    (out / "tailor_notes.md").write_text("\n".join(lines))
    (ROOT / ".pipeline" / "keeps_queue.json").write_text(json.dumps(queue, indent=1))   # -> log_apps.py queue
    outd = ROOT / "outputs" / day
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "apply_list.md").write_text(
        f"# Apply list {day} ({len(jobs)})\n\nResumes: `Job_Applications_Resumes/{day}/` (notes in `tailor_notes.md`). "
        "Networking brief per job below: upload this file to the ChatGPT networking project.\n\n"
        "| # | Company | Role | Location | Lane | Score | Resume | Apply |\n|---|---|---|---|---|---|---|---|\n"
        + "\n".join(table) + "\n\n# Networking briefs\n\n" + "\n".join(briefs))
    print(f"\n{len(jobs)} resumes -> {out}\napply list + networking briefs -> {outd / 'apply_list.md'}")
    return 0


def self_test() -> int:
    tex = ("  \\textbf{Quality}: SPC, CAPA, 8D \\\\\n  \\textbf{Tools \\& Certifications}: Python, Excel \\\\\n"
           "\\resumeItemListStart\n    \\resumeItem{Ran SPC charts.}\n    \\resumeItem{Wrote CAPA records with fishbone.}\n"
           "  \\resumeItemListEnd")
    jd = "You will own CAPA records and Ishikawa analysis."
    t = tailor_tex(tex, jd)
    ok = [t.index("CAPA, ") < t.index("SPC"),                       # matching skill moves first
          t.index("Wrote CAPA") < t.index("Ran SPC"),                # matching bullet moves first
          "Ishikawa" in t and "fishbone" not in t,                   # vetted equivalent swapped in
          "Python, Excel" in t,                                      # Tools line untouched
          tailor_tex(tex, "SPC only") .index("Ran SPC") < tailor_tex(tex, "SPC only").index("Wrote CAPA")]
    b = brief({"company": "Acme Composites", "title": "Process Technician, Cure & Bond", "location": "Kent, WA", "lane": "C",
               "description": "You will be a member of the Cure team. We offer benefits.", "apply_url": "https://x"},
              tex, "resume_Acme", 1)
    ok += ["founder" in b,                                           # small company -> founder line
           "Cure & Bond production / engineering supervisor" in b,  # area from the title
           '"You will be a member of the Cure team."' in b and "benefits" not in b,
           "Cure%20%26%20Bond" in b,                                 # search URL encoded
           "- Wrote CAPA records with fishbone." in b]               # resume points, LaTeX stripped
    print("ALL PASS" if all(ok) else f"FAIL {ok}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main(sys.argv[1:]))
