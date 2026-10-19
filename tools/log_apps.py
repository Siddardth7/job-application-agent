#!/usr/bin/env python3
"""
log_apps.py - end of the daily run: record what you applied to, write the daily file, track outcomes.

  add      python3 tools/log_apps.py add [.pipeline/applied.json]
             applied.json = [{"n": 3, "resume": "resume_Acme_ProcessEng.pdf", "track": "niche", "note": "why it fits"}, ...]
             "n" is the row number in .pipeline/triage.json. Optional "dropped": [{"n": 5, "reason": "..."}].
             Inserts into Supabase `applications` (status applied), marks seen_jobs.csv, and writes
             outputs/<date>/applications_<date>.md  <- the one file with everything from today.
  file     python3 tools/log_apps.py file [YYYY-MM-DD]      rewrite that day's file from Supabase
  status   python3 tools/log_apps.py status JOB_ID interviewing|offer|rejected|dropped [--note "..."]
             Rejections: put the reason in --note. Interview stage goes in the note too.
  --self-test

Nothing here applies to a job or messages anyone.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ledger  # noqa: E402
from lib.profile_config import classify_domain  # noqa: E402

STATUSES = {"interviewing", "offer", "rejected", "dropped", "applied", "expired"}


def _supa() -> tuple[str, str]:
    ledger.load_env()
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_KEY missing from .env")
    return url, key


def _call(method: str, path: str, body=None, prefer: str = "return=minimal"):
    url, key = _supa()
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json", "Prefer": prefer})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def next_job_numbers(day: datetime) -> tuple[str, int]:
    prefix = f"ja-{day:%m%d}-"
    rows = _call("GET", f"applications?select=job_id&job_id=like.{prefix}*") or []
    used = [int(r["job_id"].rsplit("-", 1)[1]) for r in rows if r["job_id"].rsplit("-", 1)[1].isdigit()]
    return prefix, (max(used) if used else 0) + 1


def build_records(picks: list[dict], triage: dict, day: datetime, start_no: int) -> list[dict]:
    by_n = {r["n"]: r for r in triage["candidates"]}
    recs = []
    for i, p in enumerate(picks):
        r = by_n[p["n"]]
        recs.append({
            "job_id": f"ja-{day:%m%d}-{start_no + i:02d}", "company": r["company"], "role": r["title"],
            "location": r.get("location"), "lane": "direct-apply", "score": r.get("score"),
            "track": p.get("track", "niche"), "domain": classify_domain(r["company"], r["title"]),
            "resume": p.get("resume"), "job_url": r.get("apply_url") or r.get("link"), "req_id": r.get("req_id") or None,
            "found_date": day.strftime("%Y-%m-%d"), "applied_date": day.strftime("%Y-%m-%d"),
            "status": "applied", "notes": p.get("note") or None})
    return recs


def mark_ledger(recs: list[dict], day: datetime) -> None:
    with open(ledger.SEEN_JOBS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in recs:
            fp = f"{ledger.normalize_company(r['company'])}|{ledger.normalize_title(r['role'])}"
            w.writerow([day.strftime("%Y-%m-%d"), "US", r["company"], ledger.normalize_title(r["role"]), "",
                        ledger.clean_url(r["job_url"] or ""), fp, "applied", r["req_id"] or ""])


def mark_dropped(drops: list[dict], triage: dict, day: datetime) -> None:
    by_n = {r["n"]: r for r in triage["candidates"]}
    with open(ledger.SEEN_JOBS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for d in drops:
            r = by_n.get(d["n"])
            if r:
                fp = f"{ledger.normalize_company(r['company'])}|{ledger.normalize_title(r['title'])}"
                w.writerow([day.strftime("%Y-%m-%d"), "US", r["company"], ledger.normalize_title(r["title"]), "",
                            ledger.clean_url(r.get("link") or ""), fp, "dropped-by-sid", r.get("req_id") or ""])


def write_daily_file(rows: list[dict], day: str, drops: list[dict] | None = None) -> Path:
    out = ROOT_DIR / "outputs" / day
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"applications_{day}.md"
    L = [f"# Applications - {day}\n", f"**{len(rows)} applied.** Networking is yours; the contact columns are blank for your notes.\n",
         "| # | Job ID | Company | Role | Location | Score | Track | Resume | Apply link | Req ID | Why it fits | Contact / networking |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(sorted(rows, key=lambda x: x["job_id"]), 1):
        L.append(f"| {i} | {r['job_id']} | {r['company']} | {r['role']} | {r.get('location') or ''} | {r.get('score') or ''} | "
                 f"{r.get('track') or ''} | {r.get('resume') or ''} | [link]({r.get('job_url') or ''}) | {r.get('req_id') or ''} | "
                 f"{(r.get('notes') or '').replace('|', '/')} | |")
    if drops:
        L += ["\n## Dropped at review\n"] + [f"- {d.get('company', '')} - {d.get('title', '')}: {d.get('reason', '')}" for d in drops]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


def cmd_add(path: str | None) -> int:
    src = Path(path) if path else PIPELINE_DIR / "applied.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    picks, drops = (data, []) if isinstance(data, list) else (data.get("applied", []), data.get("dropped", []))
    triage = json.loads((PIPELINE_DIR / "triage.json").read_text(encoding="utf-8"))
    day = datetime.now()
    _, start = next_job_numbers(day)
    recs = build_records(picks, triage, day, start)
    if recs:
        _call("POST", "applications", recs)
        mark_ledger(recs, day)
    by_n = {r["n"]: r for r in triage["candidates"]}
    drop_rows = [{"n": d["n"], "company": by_n[d["n"]]["company"], "title": by_n[d["n"]]["title"], "reason": d.get("reason", "")}
                 for d in drops if d["n"] in by_n]
    mark_dropped(drops, triage, day)
    today = day.strftime("%Y-%m-%d")
    rows = _call("GET", f"applications?select=*&applied_date=eq.{today}&order=job_id") or []
    f = write_daily_file(rows, today, drop_rows)
    print(f"Logged {len(recs)} applications ({recs[0]['job_id'] if recs else '-'} .. {recs[-1]['job_id'] if recs else '-'}); "
          f"{len(drop_rows)} drops noted. Daily file: {f}")
    return 0


def cmd_file(day: str | None) -> int:
    day = day or datetime.now().strftime("%Y-%m-%d")
    rows = _call("GET", f"applications?select=*&applied_date=eq.{day}&order=job_id") or []
    print(f"Wrote {write_daily_file(rows, day)} ({len(rows)} rows)")
    return 0


def cmd_status(job_id: str, status: str, note: str | None) -> int:
    if status not in STATUSES:
        raise SystemExit(f"status must be one of {sorted(STATUSES)}")
    body = {"status": status, "updated_at": datetime.now().isoformat(timespec="seconds")}
    if note:
        cur = _call("GET", f"applications?select=notes&job_id=eq.{urllib.parse.quote(job_id)}") or []
        old = (cur[0].get("notes") if cur else "") or ""
        body["notes"] = (old + " | " if old else "") + f"{datetime.now():%Y-%m-%d} {status}: {note}"
    _call("PATCH", f"applications?job_id=eq.{urllib.parse.quote(job_id)}", body)
    print(f"{job_id} -> {status}")
    return 0


def self_test() -> int:
    day = datetime(2026, 11, 2)
    triage = {"candidates": [{"n": 1, "company": "Acme Composites", "title": "Composites Process Engineer I",
                              "location": "Dayton, OH", "link": "https://x/1", "apply_url": "https://x/apply/1",
                              "score": 88, "req_id": "R-1"},
                             {"n": 2, "company": "Widgets", "title": "Process Engineer", "link": "https://x/2", "score": 40}]}
    recs = build_records([{"n": 1, "resume": "resume_Acme_ProcessEng.pdf", "track": "niche", "note": "cure + layup"}], triage, day, 3)
    ok = [recs[0]["job_id"] == "ja-1102-03", recs[0]["status"] == "applied", recs[0]["job_url"] == "https://x/apply/1",
          recs[0]["applied_date"] == "2026-11-02", recs[0]["track"] == "niche"]
    import tempfile
    global ROOT_DIR
    real, ROOT_DIR = ROOT_DIR, Path(tempfile.mkdtemp())
    try:
        p = write_daily_file(recs, "2026-11-02", [{"company": "Widgets", "title": "Process Engineer", "reason": "metal stamping"}])
        txt = p.read_text(encoding="utf-8")
        ok += [p.name == "applications_2026-11-02.md", "Acme Composites" in txt, "metal stamping" in txt, "| 1 | ja-1102-03 |" in txt]
    finally:
        ROOT_DIR = real
    for i, o in enumerate(ok):
        print(f"  {'PASS' if o else 'FAIL'}  check {i + 1}")
    print("ALL PASS" if all(ok) else "FAILED")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if a[0] == "--self-test":
        sys.exit(self_test())
    if a[0] == "add":
        sys.exit(cmd_add(a[1] if len(a) > 1 else None))
    if a[0] == "file":
        sys.exit(cmd_file(a[1] if len(a) > 1 else None))
    if a[0] == "status" and len(a) >= 3:
        note = a[a.index("--note") + 1] if "--note" in a else None
        sys.exit(cmd_status(a[1], a[2], note))
    print(__doc__)
    sys.exit(2)
