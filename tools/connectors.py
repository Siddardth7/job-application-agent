#!/usr/bin/env python3
"""
connectors.py - Pass 6 input: Indeed / ZipRecruiter / Dice results gathered by the agent through the claude.ai
connectors (MCP tools exist only inside a Claude session, so Python cannot call them).

  During /run the agent saves each raw tool response, unedited, under .pipeline/connectors/:
      indeed_<query>.txt         Indeed search_jobs result (markdown)
      indeed_detail_<id>.txt     Indeed get_job_details result (markdown, full JD)
      zip_<query>.json           ZipRecruiter search_jobs result (JSON)
      dice_<query>.json          Dice search_jobs result (JSON)
      dice_detail_<guid>.json    Dice get_job_details result (JSON, full JD)
  python3 tools/connectors.py build [--max-age=7]   -> .pipeline/connectors_raw.json (fetch_jobs.py Pass 6 reads it)
  python3 tools/connectors.py --self-test

Rows come out in the shape fetch_jobs.normalize_job expects. Rows older than --max-age days are dropped (Indeed has
no date filter). Indeed links and ids change between calls, so dedup relies on the ledger's company|title fingerprint.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / ".pipeline" / "connectors"
OUT = ROOT / ".pipeline" / "connectors_raw.json"


def _field(block: str, name: str) -> str:
    m = re.search(rf"\*\*{re.escape(name)}:\*\*\s*(.+)", block)
    return m.group(1).strip() if m else ""


def _iso(date_text: str) -> str:
    for fmt in ("%B %d, %Y", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _unwrap(text: str):
    """Tool results arrive as JSON; Indeed wraps its markdown in {"result": "..."}."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return data.get("result", data) if isinstance(data, dict) else data


def parse_indeed(text: str) -> list[dict]:
    md = _unwrap(text)
    rows = []
    for block in re.split(r"\n\s*\n(?=\*\*Job Title:\*\*)", md if isinstance(md, str) else ""):
        title = _field(block, "Job Title")
        if title:
            url = _field(block, "View Job URL")
            rows.append({"title": title, "companyName": _field(block, "Company"), "location": _field(block, "Location"),
                         "link": url, "applyUrl": url, "postedAt": _iso(_field(block, "Posted on")),
                         "indeed_id": _field(block, "Job Id"), "source_name": "indeed"})
    return rows


def parse_indeed_detail(text: str) -> tuple[str, str, str]:
    """(company, title, description) from a get_job_details result."""
    md = _unwrap(text)
    md = md if isinstance(md, str) else ""
    title = (re.search(r"^###\s*(.+)$", md, re.M) or [None, ""])[1].strip()
    parts = re.split(r"\*\*Compensation:\*\*.*\n", md, maxsplit=1)
    return _field(md, "Company"), title, (parts[1] if len(parts) > 1 else "").strip()


def parse_zip(text: str, today: datetime) -> list[dict]:
    data = _unwrap(text)
    rows = []
    for r in (data.get("results") or []) if isinstance(data, dict) else []:
        days = r.get("days_ago")
        rows.append({"title": r.get("title", ""), "companyName": r.get("company", ""), "location": r.get("location", ""),
                     "link": r.get("job_redirect_url", ""), "applyUrl": r.get("job_redirect_url", ""),
                     "postedAt": (today - timedelta(days=days)).strftime("%Y-%m-%d") if isinstance(days, int) else "",
                     "reqId": r.get("listing_key", ""), "source_name": "ziprecruiter"})
    return rows


def parse_dice(text: str) -> list[dict]:
    data = _unwrap(text)
    rows = []
    for r in (data.get("data") or []) if isinstance(data, dict) else []:
        rows.append({"title": r.get("title", ""), "companyName": r.get("companyName", ""),
                     "location": (r.get("jobLocation") or {}).get("displayName", ""),
                     "link": (r.get("detailsPageUrl") or "").split("?")[0], "applyUrl": (r.get("detailsPageUrl") or "").split("?")[0],
                     "postedAt": _iso(r.get("postedDate") or ""), "reqId": r.get("guid", ""),
                     "staffing": r.get("employerType") == "Recruiter", "source_name": "dice"})
    return rows


def build(raw_dir: Path, max_age: int, today: datetime) -> list[dict]:
    rows, details = [], {}
    for f in sorted(raw_dir.glob("*")):
        text = f.read_text(encoding="utf-8")
        if f.name.startswith("indeed_detail_"):
            co, title, desc = parse_indeed_detail(text)
            details[(co.lower(), title.lower())] = desc
        elif f.name.startswith("dice_detail_"):
            d = _unwrap(text)
            details[("dice", f.stem.removeprefix("dice_detail_"))] = (d.get("description") if isinstance(d, dict) else "") or ""
        elif f.name.startswith("indeed_"):
            rows += parse_indeed(text)
        elif f.name.startswith("zip_"):
            rows += parse_zip(text, today)
        elif f.name.startswith("dice_"):
            rows += parse_dice(text)
    cutoff = (today - timedelta(days=max_age)).strftime("%Y-%m-%d")
    out, seen = [], set()
    for r in rows:
        key = (r["companyName"].lower(), r["title"].lower())
        if key in seen or (r["postedAt"] and r["postedAt"] < cutoff):
            continue
        seen.add(key)
        r["description"] = details.get(key) or details.get(("dice", r.get("reqId", ""))) or ""
        out.append(r)
    return out


def main(argv: list[str]) -> int:
    max_age = next((int(a.split("=")[1]) for a in argv if a.startswith("--max-age=")), 7)
    rows = build(RAW_DIR, max_age, datetime.now())
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    by = {}
    for r in rows:
        by[r["source_name"]] = by.get(r["source_name"], 0) + 1
    print(f"Pass 6 input: {len(rows)} rows ({by}); {sum(not r['description'] for r in rows)} without a JD -> {OUT}")
    return 0


def self_test() -> int:
    import tempfile
    today = datetime(2026, 10, 20)
    d = Path(tempfile.mkdtemp())
    indeed = ("**Job Title:** Process Engineer I\n **Job Id:** JOBSEARCH_1\n **Company:** Toray Advanced Composites\n"
              " **Location:** Morgan Hill, CA\n **Posted on:** October 18, 2026\n **View Job URL:** https://to.indeed.com/a\n\n"
              "**Job Title:** Old Role\n **Job Id:** JOBSEARCH_2\n **Company:** X\n **Location:** Y\n **Posted on:** March 13, 2026\n"
              " **View Job URL:** https://to.indeed.com/b\n")
    (d / "indeed_pe.txt").write_text(json.dumps({"result": indeed}))
    (d / "indeed_detail_1.txt").write_text(json.dumps({"result": "### Process Engineer I\n **Company:** Toray Advanced Composites\n"
                                                                  " **Compensation:** $90k\n\nLess than three years of experience."}))
    (d / "zip_pe.json").write_text(json.dumps({"results": [{"title": "Materials Engineer", "company": "Continuous Composites Inc",
                                                             "location": "Kent, Washington", "job_redirect_url": "https://z/1",
                                                             "listing_key": "k1", "days_ago": 2}]}))
    (d / "dice_c.json").write_text(json.dumps({"data": [{"title": "Composites Engineer I", "companyName": "ROUSH", "guid": "g1",
                                                          "jobLocation": {"displayName": "Livonia, Michigan, USA"},
                                                          "detailsPageUrl": "https://www.dice.com/job-detail/g1?utm=x",
                                                          "postedDate": "2026-10-18T09:56:41Z", "employerType": "Direct Hire"}]}))
    rows = build(d, 7, today)
    t = {r["title"]: r for r in rows}
    ok = [len(rows) == 3, "Old Role" not in t,                                   # >7 days dropped
          t["Process Engineer I"]["description"].startswith("Less than three"),  # Indeed JD attached by company|title
          t["Materials Engineer"]["postedAt"] == "2026-10-18",                   # days_ago -> date
          t["Composites Engineer I"]["link"] == "https://www.dice.com/job-detail/g1",
          t["Composites Engineer I"]["description"] == ""]                       # no detail -> needs JD
    print("ALL PASS" if all(ok) else f"FAIL {ok}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(self_test() if "--self-test" in a else main(a) if a and a[0] == "build" else (print(__doc__) or 2))
