#!/usr/bin/env python3
"""
triage.py - Stage 2 of the daily run. Gates, lightly scores and annotates; it never selects.

Reads  .pipeline/fetched.json   (tools/fetch_jobs.py, already deduped against seen_jobs.csv)
Writes .pipeline/triage.json    every candidate with score parts, cautions, company history
       .pipeline/triage.md      survivors by score, then gated rows with the quoted reason
       seen_jobs.csv            every row, status surfaced | dropped-hardgate

The score is an audit aid. The human picks Keep/Drop row by row after reading the JD.

Gate 0 (visa, ITAR, sponsorship, title level, language) is gates.check_eligibility_gate,
unchanged. On top of it: required years above triage.max_years_gate is gated.

Score /100 (weights in config triage.weights):
  niche      40  composites / polymer / cure terms in the JD (core terms count more than adjacent)
  title      20  niche word in the title, else a generic process/manufacturing/quality title
  level      20  entry cues or low stated years; senior titles are already gated
  sponsor    10  sponsorship stated in the JD; silence is neutral
  logistics  10  freshness, direct employer vs staffing agency, US location

Usage:
  python3 tools/triage.py                 # triage .pipeline/fetched.json
  python3 tools/triage.py --no-ledger     # do not touch seen_jobs.csv
  python3 tools/triage.py --self-test
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import load_config  # noqa: E402
from lib import ledger  # noqa: E402
import gates as gs  # noqa: E402

TRIAGE_DEFAULTS = {
    "max_years_gate": 3, "detail_limit": 45,
    "weights": {"niche": 40, "title": 20, "level": 20, "sponsor": 10, "logistics": 10},
    "niche_core": [], "niche_adjacent": [], "off_niche_cues": [], "entry_title_cues": [], "level2_title_cues": [],
}
GENERIC_TITLE_CUES = ["process engineer", "manufacturing engineer", "quality engineer", "materials", "research", "r&d"]
EVERIFY_RE = re.compile(r"e-?verify", re.I)


def build_tcfg(profile: dict) -> dict:
    t = json.loads(json.dumps(TRIAGE_DEFAULTS))
    t.update(profile.get("triage") or {})
    return t


# ── Company history ──────────────────────────────────────────────────────────

def load_history() -> dict:
    """{normalized company: {applied, rejected, interviewing, offer, last}} from Supabase, else the slim CSV."""
    rows: list[dict] = []
    ledger.load_env()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if url and key:
        try:
            req = urllib.request.Request(f"{url}/rest/v1/applications?select=company,status,applied_date&limit=5000",
                                         headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as e:   # offline or table unreachable: fall back, say so
            print(f"  [history] Supabase unavailable ({e}); using data/applied_dedup.csv")
    if not rows:
        p = ROOT_DIR / "data" / "applied_dedup.csv"
        if p.exists():
            rows = [{"company": r["company"], "status": r["status"], "applied_date": r["applied_date"]}
                    for r in csv.DictReader(open(p, encoding="utf-8"))]
    hist: dict = defaultdict(lambda: {"applied": 0, "rejected": 0, "interviewing": 0, "offer": 0, "last": ""})
    for r in rows:
        h = hist[ledger.normalize_company(r.get("company") or "")]
        st = r.get("status") or ""
        if st in ("applied", "rejected", "interviewing", "offer"):
            h["applied"] += 1                      # every one of these was an application sent
            if st != "applied":
                h[st] += 1
        h["last"] = max(h["last"], r.get("applied_date") or "")
    return hist


def history_text(company: str, hist: dict) -> str:
    h = hist.get(ledger.normalize_company(company))
    if not h or not h["applied"]:
        return "none"
    parts = [f"{h['applied']} applied"]
    for k in ("rejected", "interviewing", "offer"):
        if h[k]:
            parts.append(f"{h[k]} {k}")
    return ", ".join(parts) + (f" (last {h['last']})" if h["last"] else "")


# ── Scoring ──────────────────────────────────────────────────────────────────

def _wm(term: str, text: str) -> bool:
    """Word match that also accepts a plural: 'composite' finds 'composites'."""
    return gs.word_match(term, text) or gs.word_match(term + "s", text)


def _hits(terms: list[str], text: str) -> list[str]:
    return [t for t in terms if _wm(t, text)]


def score_row(job: dict, cfg: dict, tcfg: dict) -> dict:
    w = tcfg["weights"]
    title = (job.get("title") or "").lower()
    text = f"{job.get('title', '')} {job.get('description', '') or ''}".lower()
    core, adj = _hits(tcfg["niche_core"], text), _hits(tcfg["niche_adjacent"], text)
    niche = round(w["niche"] * (0.7 * min(len(core), 6) / 6 + 0.3 * min(len(adj), 6) / 6))

    niche_in_title = [t for t in tcfg["niche_core"] if _wm(t, title)]
    if niche_in_title:
        t_pts, t_why = w["title"], f"niche word in title ({niche_in_title[0]})"
    elif any(c in title for c in GENERIC_TITLE_CUES) and len(core) >= 2:
        t_pts, t_why = round(w["title"] * 0.6), "generic title, niche terms in the JD"
    elif any(c in title for c in GENERIC_TITLE_CUES):
        t_pts, t_why = round(w["title"] * 0.3), "generic title, little niche content"
    else:
        t_pts, t_why = 0, "title is outside the niche"
    if any(c in f" {title} " for c in cfg["scoring"]["off_discipline_cues"]):
        t_pts, t_why = 0, "off-discipline title"

    yrs = gs.required_years(text)
    padded = f" {title} "
    if any(c in padded for c in tcfg["level2_title_cues"]):
        lvl, l_why = round(w["level"] * 0.2), "level II title"
    elif yrs is not None and yrs <= 2:
        lvl, l_why = w["level"], f"{yrs} yrs stated"
    elif yrs == 3:
        lvl, l_why = round(w["level"] * 0.4), "3 yrs stated"
    elif any(c in padded for c in tcfg["entry_title_cues"]):
        lvl, l_why = w["level"], "entry cue in title"
    else:
        lvl, l_why = round(w["level"] * 0.6), "level unstated"

    stated = gs.stated_sponsorship(job.get("description") or "")
    sp = w["sponsor"] if stated else round(w["sponsor"] * 0.5)
    everify = bool(EVERIFY_RE.search(job.get("description") or ""))

    company_lower = (job.get("company") or "").lower()
    staffing = any(gs.word_match(a, company_lower) for a in cfg["staffing_agencies"])
    fresh = 5 if job.get("freshness", "FRESH") == "FRESH" else 2
    lg = min(w["logistics"], fresh + (0 if staffing else 3) + 2)

    total = niche + t_pts + lvl + sp + lg
    return {"score": total, "parts": {"niche": niche, "title": t_pts, "level": lvl, "sponsor": sp, "logistics": lg},
            "why": f"{len(core)} core / {len(adj)} adjacent niche terms; {t_why}; {l_why}",
            "core_terms": core[:8], "years": yrs, "sponsorship_stated": stated, "e_verify_mentioned": everify,
            "staffing": staffing}


def triage_batch(jobs: list[dict], cfg: dict, tcfg: dict, hist: dict) -> tuple[list[dict], list[dict]]:
    keep, gated = [], []
    for j in jobs:
        ok, verdict, reason, cautions = gs.check_eligibility_gate(j, cfg)
        yrs = gs.required_years(f"{j.get('title', '')} {j.get('description', '') or ''}".lower())
        if ok and yrs is not None and yrs > tcfg["max_years_gate"]:
            ok, verdict, reason = False, "DROP (SENIORITY)", f"Requires {yrs}+ years; gate is {tcfg['max_years_gate']}"
        if ok:
            text_l = f"{j.get('title', '')} {j.get('description', '') or ''}".lower()
            off = _hits(tcfg["off_niche_cues"], text_l)
            if len(off) >= 2 and not _hits(tcfg["niche_core"], text_l):
                ok, verdict, reason = False, "DROP (OFF-NICHE)", f"No composites / materials content, and it reads as {', '.join(off[:3])}"
        row = {k: j.get(k) for k in ("title", "company", "location", "link", "apply_url", "posted_at", "source",
                                     "pass_num", "req_id", "description", "needs_jd", "freshness")}
        row.update(cautions=cautions, history=history_text(j.get("company") or "", hist))
        if not ok:
            row.update(verdict=verdict, reason=reason)
            gated.append(row)
            continue
        if j.get("needs_jd") or not (j.get("description") or "").strip():
            row.update(verdict="NEEDS JD", score=None, parts={}, why="no job description; open the link and paste it")
            keep.append(row)
            continue
        row.update(verdict="ELIGIBLE", **score_row(j, cfg, tcfg))
        keep.append(row)
    keep.sort(key=lambda r: (r["verdict"] == "NEEDS JD", -(r.get("score") or 0)))
    return keep, gated


# ── Output ───────────────────────────────────────────────────────────────────

def write_outputs(keep: list[dict], gated: list[dict], today: str, detail_limit: int = 45) -> None:
    PIPELINE_DIR.mkdir(exist_ok=True)
    for i, r in enumerate(keep, 1):
        r["n"] = i
    (PIPELINE_DIR / "triage.json").write_text(json.dumps({"date": today, "candidates": keep, "gated": gated}, indent=2),
                                              encoding="utf-8")
    scored = [r for r in keep if r["verdict"] == "ELIGIBLE"]
    nojd = [r for r in keep if r["verdict"] == "NEEDS JD"]
    L = [f"# Triage - {today}\n",
         f"**{len(keep) + len(gated)} new postings: {len(scored)} to review, {len(nojd)} need a JD, {len(gated)} gated.** "
         "Scores are an audit aid; you choose Keep/Drop after reading the JD.\n",
         "## To review\n",
         "| # | Company | Title | Location | Posted | Score (niche/title/level/spons/logist) | Cautions | Company history |",
         "|---|---|---|---|---|---|---|---|"]
    for r in scored[:detail_limit]:
        p = r["parts"]
        flags = list(r["cautions"]) + (["E-Verify mentioned"] if r["e_verify_mentioned"] else []) + (["staffing agency"] if r["staffing"] else [])
        L.append(f"| {r['n']} | {r['company']} | [{r['title']}]({r['link']}) | {r['location']} | {r['posted_at'] or ''} | "
                 f"**{r['score']}** ({p['niche']}/{p['title']}/{p['level']}/{p['sponsor']}/{p['logistics']}) | "
                 f"{'; '.join(f[:120] for f in flags) or '-'} | {r['history']} |")
    if len(scored) > detail_limit:
        L += [f"\n## Below the line ({len(scored) - detail_limit} more, lower score; ask to see any)\n"] + \
             [f"- {r['n']}. {r['score']} - {r['company']}: {r['title']}" for r in scored[detail_limit:]]
    if nojd:
        L += ["\n## Needs a JD (cannot be scored)\n"] + [f"- {r['n']}. {r['company']} - [{r['title']}]({r['link']}) ({r['location']})" for r in nojd]
    L += ["\n## Gated\n", "| Company | Title | Verdict | Reason |", "|---|---|---|---|"]
    for r in gated:
        L.append(f"| {r['company']} | {r['title']} | {r['verdict']} | {r['reason'][:200]} |")
    (PIPELINE_DIR / "triage.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def append_ledger(keep: list[dict], gated: list[dict], today: str) -> int:
    path = ledger.SEEN_JOBS_CSV
    new = not path.exists()
    n = 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["first_seen_date", "market", "company", "title_normalized", "city", "job_url", "fingerprint", "status", "req_id"])
        for rows, status in ((keep, "surfaced"), (gated, "dropped-hardgate")):
            for r in rows:
                city = (r.get("location") or "").split(",")[0].strip()
                fp = f"{ledger.normalize_company(r['company'])}|{ledger.normalize_title(r['title'])}"
                w.writerow([today, "US", r["company"], ledger.normalize_title(r["title"]), city,
                            ledger.clean_url(r.get("link") or ""), fp, status, r.get("req_id") or ""])
                n += 1
    return n


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    cfg_raw = load_config()
    cfg, tcfg = gs.build_cfg(cfg_raw), build_tcfg(cfg_raw)
    jobs = json.loads((PIPELINE_DIR / "fetched.json").read_text(encoding="utf-8"))
    hist = load_history()
    keep, gated = triage_batch(jobs, cfg, tcfg, hist)
    today = datetime.now().strftime("%Y-%m-%d")
    write_outputs(keep, gated, today, tcfg["detail_limit"])
    wrote = 0 if "--no-ledger" in argv else append_ledger(keep, gated, today)
    print(f"Triage: {len(jobs)} postings -> {sum(r['verdict'] == 'ELIGIBLE' for r in keep)} to review, "
          f"{sum(r['verdict'] == 'NEEDS JD' for r in keep)} need a JD, {len(gated)} gated; {wrote} ledger rows.")
    print(f"Handoffs: {PIPELINE_DIR / 'triage.md'}, triage.json")
    return 0


# ── Self-test ────────────────────────────────────────────────────────────────

def self_test() -> int:
    prof = {"candidate": {"needs_sponsorship": True, "max_years": 3},
            "search": {"role_titles": ["Composites Process Engineer"], "adjacent_titles": []},
            "scoring": {"title_drop_cues": ["senior", "manager", "principal"]},
            "triage": {"niche_core": ["composite", "autoclave", "prepreg", "cure"], "niche_adjacent": ["fmea", "spc"], "off_niche_cues": ["pharmaceutical", "cell culture", "gmp"],
                       "entry_title_cues": ["associate", "engineer i "], "level2_title_cues": ["engineer ii"]}}
    cfg, tcfg = gs.build_cfg(prof), build_tcfg(prof)
    hist = {ledger.normalize_company("Acme Composites"): {"applied": 3, "rejected": 2, "interviewing": 0, "offer": 0, "last": "2026-09-01"}}
    jd = "We make composite parts: prepreg layup and autoclave cure. FMEA and SPC. 1-2 years experience. Visa sponsorship available."
    jobs = [
        {"title": "Composites Process Engineer I", "company": "Acme Composites", "description": jd, "link": "u1"},
        {"title": "Process Engineer", "company": "Widgets", "description": "Metal stamping line, SPC. 1 year.", "link": "u2"},
        {"title": "Composites Engineer", "company": "BigCo", "description": "Composite parts, autoclave cure. 5+ years of experience required.", "link": "u3"},
        {"title": "Materials Engineer", "company": "Secret Inc", "description": jd + " Must be a U.S. citizen.", "link": "u4"},
        {"title": "Senior Composites Engineer", "company": "X", "description": jd, "link": "u5"},
        {"title": "Process Development Engineer I", "company": "Bio", "description": "Pharmaceutical GMP cell culture process. 1 year.", "link": "u7"},
        {"title": "Composites Engineer", "company": "Blank", "description": "", "needs_jd": True, "link": "u6"},
    ]
    keep, gated = triage_batch(jobs, cfg, tcfg, hist)
    by = {r["link"]: r for r in keep + gated}
    checks = [
        ("niche entry role scores high", by["u1"]["score"] >= 80),
        ("generic role scores low", by["u2"]["score"] < 40),
        ("5+ yrs is gated on years", by["u3"]["verdict"] == "DROP (SENIORITY)"),
        ("citizen-only is gated by Gate 0", by["u4"]["verdict"].startswith("VISA RISK")),
        ("Senior title is gated", by["u5"]["verdict"] == "DROP (TITLE)"),
        ("biotech process role is gated off-niche", by["u7"]["verdict"] == "DROP (OFF-NICHE)"),
        ("blank JD is Needs JD, not scored", by["u6"]["verdict"] == "NEEDS JD" and by["u6"]["score"] is None),
        ("company history shows applied and rejected", by["u1"]["history"].startswith("3 applied, 2 rejected")),
        ("no history reads none", by["u2"]["history"] == "none"),
        ("review list sorted best first", [r["link"] for r in keep][:2] == ["u1", "u2"]),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print("ALL PASS" if not bad else f"FAILED: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
