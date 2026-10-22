#!/usr/bin/env python3
"""
log_apps.py - end of the daily run: record what you applied to, write the daily file, track outcomes.

  add      python3 tools/log_apps.py add [.pipeline/applied.json]
             applied.json = [{"n": 3, "resume": "resume_Acme_ProcessEng.pdf", "track": "niche", "note": "why it fits"}, ...]
             "n" is the row number in .pipeline/triage.json. Optional "dropped": [{"n": 5, "reason": "..."}].
             Inserts into Supabase `applications` (status applied), marks seen_jobs.csv, and writes
             outputs/<date>/applications_<date>.md  <- the one file with everything from today.
  queue    python3 tools/log_apps.py queue [.pipeline/keeps_queue.json]
             End of the run: the day's tailored Keeps go into Supabase as status `pending` (written by tools/tailor.py).
             Sid applies from the tracker, flips each row to applied or dropped and picks a Review reason.
  review   python3 tools/log_apps.py review [YYYY-MM-DD]     (default: yesterday) start of the next run:
             expires `pending` rows older than 3 days, summarises statuses + Review reasons, flags rows with no
             Review, rewrites that day's file and appends a dated entry to learning_log.md.
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
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ledger  # noqa: E402
from lib.profile_config import classify_domain  # noqa: E402

STATUSES = {"pending", "interviewing", "offer", "rejected", "dropped", "applied", "expired"}
# Tracker Review dropdown (job_tracker.html REVIEWS must match). Required on every row once Sid acts on it.
REVIEWS = ["good: strong skill match", "good: right level", "good: target company / domain", "good: resume fit as-is",
           "stretch: level", "stretch: domain", "skip: too senior", "skip: citizenship / ITAR", "skip: off-domain",
           "skip: location / shift / pay", "skip: closed / duplicate", "other (see note)"]
EXPIRE_DAYS = 3
CURRENT_SPRINT = "2026-10-19 to 2026-12-03"   # schema default; queue dedupe + expiry never touch older sprints
CORE4 = ("tesla", "micron", "joby", "ast spacemobile", "ast & science")


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


def mark_ledger(recs: list[dict], day: datetime, status: str = "applied") -> None:
    with open(ledger.SEEN_JOBS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in recs:
            fp = f"{ledger.normalize_company(r['company'])}|{ledger.normalize_title(r['role'])}"
            w.writerow([day.strftime("%Y-%m-%d"), "US", r["company"], ledger.normalize_title(r["role"]), "",
                        ledger.clean_url(r["job_url"] or ""), fp, status, r["req_id"] or ""])


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
    applied = sum(r.get("status") not in ("pending", "dropped", "expired") for r in rows)
    L = [f"# Applications - {day}\n", f"**{len(rows)} rows, {applied} applied.** Networking is yours; the contact columns are blank for your notes.\n",
         "| # | Job ID | Company | Role | Location | Status | Review | Track | Resume | Apply link | Req ID | Notes | Contact / networking |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(sorted(rows, key=lambda x: x["job_id"]), 1):
        L.append(f"| {i} | {r['job_id']} | {r['company']} | {r['role']} | {r.get('location') or ''} | {r.get('status') or ''} | {r.get('review') or ''} | "
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


def queue_records(keeps: list[dict], day: datetime, start_no: int) -> list[dict]:
    """Tailored Keeps -> pending tracker rows. Resume lane goes in notes (the `lane` column is the old enum)."""
    return [{"job_id": f"ja-{day:%m%d}-{start_no + i:02d}", "company": k["company"], "role": k["title"],
             "location": k.get("location"), "lane": "direct-apply", "score": k.get("score"),
             "track": "core-4" if k["company"].lower().startswith(CORE4) else "niche",
             "domain": classify_domain(k["company"], k["title"]), "resume": k.get("resume"),
             "job_url": k.get("apply_url") or k.get("link"), "req_id": k.get("req_id") or None,
             "found_date": day.strftime("%Y-%m-%d"), "status": "pending",
             "notes": f"Lane {k['lane']} resume" if k.get("lane") else None} for i, k in enumerate(keeps)]


def cmd_queue(path: str | None) -> int:
    keeps = json.loads((Path(path) if path else PIPELINE_DIR / "keeps_queue.json").read_text(encoding="utf-8"))
    day = datetime.now()
    have = {r["job_url"] for r in _call("GET", f"applications?select=job_url&status=eq.pending&sprint=eq.{urllib.parse.quote(CURRENT_SPRINT)}") or []}
    keeps = [k for k in keeps if (k.get("apply_url") or k.get("link")) not in have]   # re-running never duplicates
    _, start = next_job_numbers(day)
    recs = queue_records(keeps, day, start)
    if recs:
        _call("POST", "applications", recs)
        mark_ledger(recs, day, "queued")
    print(f"Queued {len(recs)} rows as pending ({recs[0]['job_id'] if recs else '-'} .. {recs[-1]['job_id'] if recs else '-'}). "
          f"Apply from job_tracker.html; set Status + Review on every row.")
    return 0


def summarize(rows: list[dict]) -> dict:
    acted = [r for r in rows if r["status"] != "pending"]
    return {"total": len(rows), "status": Counter(r["status"] for r in rows),
            "review": Counter(r.get("review") for r in rows if r.get("review")),
            "missing_review": [r for r in acted if not r.get("review")],
            "notes": [r for r in rows if r.get("review") or sid_note(r)]}


def sid_note(r: dict) -> str:
    """Sid's own note text, without the 'Lane X resume' tag queue writes."""
    return re.sub(r"^Lane [A-D] resume\s*", "", r.get("notes") or "").strip()


def log_entry(day: str, s: dict) -> str:
    st = ", ".join(f"{k} {v}" for k, v in s["status"].most_common())
    rv = "\n".join(f"  - {k}: {v}" for k, v in s["review"].most_common()) or "  - none yet"
    rows = "\n".join(f"  - {r['company']} / {r['role']}: {r.get('review') or 'NO REVIEW'}"
                      + (f" ({sid_note(r)})" if sid_note(r) else "") for r in s["notes"])
    miss = f"\n- Missing review on {len(s['missing_review'])} acted-on rows." if s["missing_review"] else ""
    return f"\n## {day} (tracker review)\n- {s['total']} queued: {st}.\n- Review reasons:\n{rv}\n- Rows:\n{rows}{miss}\n"


def cmd_review(day: str | None) -> int:
    today = datetime.now()
    day = day or (today - timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff = (today - timedelta(days=EXPIRE_DAYS)).strftime("%Y-%m-%d")
    sp = f"&sprint=eq.{urllib.parse.quote(CURRENT_SPRINT)}"
    stale = _call("GET", f"applications?select=job_id&status=eq.pending&found_date=lte.{cutoff}{sp}") or []
    if stale:
        _call("PATCH", f"applications?status=eq.pending&found_date=lte.{cutoff}{sp}",
              {"status": "expired", "updated_at": today.isoformat(timespec="seconds")})
    rows = _call("GET", f"applications?select=*&found_date=eq.{day}&order=job_id") or []
    s = summarize(rows)
    with open(ROOT_DIR / "learning_log.md", "a", encoding="utf-8") as f:
        f.write(log_entry(day, s))
    path = write_daily_file(rows, day)
    print(log_entry(day, s))
    print(f"Expired {len(stale)} pending rows older than {EXPIRE_DAYS} days. Daily file: {path}. learning_log.md updated.")
    return 0


def cmd_file(day: str | None) -> int:
    day = day or datetime.now().strftime("%Y-%m-%d")
    rows = _call("GET", f"applications?select=*&or=(found_date.eq.{day},applied_date.eq.{day})&order=job_id") or []
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
    q = queue_records([{"company": "Tesla", "title": "Quality Technician", "link": "https://t/1", "lane": "B",
                        "resume": "resume_Tesla_QT.pdf"},
                       {"company": "Acme Composites", "title": "M&P Engineer", "apply_url": "https://a/1", "lane": "A"}], day, 1)
    ok += [q[0]["status"] == "pending", q[0]["track"] == "core-4", q[1]["track"] == "niche", "applied_date" not in q[0],
           q[0]["notes"] == "Lane B resume", q[1]["job_url"] == "https://a/1"]
    rows = [{"company": "Tesla", "role": "QT", "status": "applied", "review": "good: right level", "notes": "Lane B resume"},
            {"company": "Acme", "role": "ME", "status": "dropped", "review": None, "notes": "Lane D resume"},
            {"company": "Beta", "role": "PE", "status": "pending", "review": None, "notes": None}]
    sm = summarize(rows)
    ok += [sm["status"]["applied"] == 1, len(sm["missing_review"]) == 1, sm["review"]["good: right level"] == 1,
           "NO REVIEW" not in log_entry("2026-11-02", summarize(rows[:1])), "Missing review on 1" in log_entry("2026-11-02", sm)]
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
    if a[0] == "queue":
        sys.exit(cmd_queue(a[1] if len(a) > 1 else None))
    if a[0] == "review":
        sys.exit(cmd_review(a[1] if len(a) > 1 else None))
    if a[0] == "file":
        sys.exit(cmd_file(a[1] if len(a) > 1 else None))
    if a[0] == "status" and len(a) >= 3:
        note = a[a.index("--note") + 1] if "--note" in a else None
        sys.exit(cmd_status(a[1], a[2], note))
    print(__doc__)
    sys.exit(2)
