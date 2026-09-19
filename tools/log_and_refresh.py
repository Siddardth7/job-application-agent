#!/usr/bin/env python3
"""
log_and_refresh.py — Logs approved applications to Supabase and rebuilds tracker artifacts.
MANDATORY: Rebuilds using ./refresh.sh --fetch to keep the database and tracker fully in sync.
"""

import sys
import os
import json
import csv
import subprocess
import urllib.request
import re
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
SEEN_JOBS_CSV = ROOT_DIR / "seen_jobs.csv"
ENV_FILE = ROOT_DIR / ".env"

# Reuse the single contacts upsert (Supabase `contacts` table) instead of a
# second copy. networking_sheet lives at the repo root.
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tools"))
from lib import ledger  # noqa: E402

def load_env():
    """Load key-value pairs from .env into os.environ."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

def get_existing_job_ids(url: str, key: str, month_day: str) -> tuple[int, set[str]]:
    """Get max existing index for today and set of existing company|title signatures."""
    endpoint = f"{url}/rest/v1/applications?select=job_id,company,role&job_id=like.ja-{month_day}-*"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    req = urllib.request.Request(endpoint, headers=headers)
    max_idx = 0
    existing_sigs = set()
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data:
                jid = item.get("job_id", "")
                sig = f"{item.get('company', '').lower()}|{item.get('role', '').lower()}"
                existing_sigs.add(sig)
                m = re.search(rf'ja-{month_day}-(\d+)', jid)
                if m:
                    max_idx = max(max_idx, int(m.group(1)))
    except Exception as e:
        print(f"  Warning querying existing job IDs: {e}", file=sys.stderr)
    return max_idx, existing_sigs

def insert_to_supabase(records: list[dict], dry_run: bool = False) -> int:
    """Insert application records into Supabase via REST API."""
    url = os.getenv("SUPABASE_URL", "https://chsrkysjongzgdbwqhlu.supabase.co")
    key = os.getenv("SUPABASE_KEY")
    
    if not key:
        print("Error: SUPABASE_KEY is missing from environment / .env", file=sys.stderr)
        return 0
        
    endpoint = f"{url}/rest/v1/applications"
    today_str = datetime.now().strftime("%Y-%m-%d")
    month_day = datetime.now().strftime("%m%d")
    
    max_idx, existing_sigs = get_existing_job_ids(url, key, month_day)
    print(f"Current highest job_id index for today: ja-{month_day}-{max_idx:02d} ({len(existing_sigs)} existing roles).")
    
    inserted_count = 0
    # No `resolution=ignore-duplicates`: a job_id collision must be LOUD. Two runs (two
    # tools, two machines) can read the same max index; the loser used to have its row
    # silently discarded. Now a duplicate key just moves on to the next index.
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "return=minimal"}

    current_idx = max_idx
    contact_sources = []  # inserted rows, stamped with job_id, for contacts upsert
    for rec in records:
        sig = f"{rec.get('company', '').lower()}|{rec.get('title', '').lower()}"
        if sig in existing_sigs:
            print(f"  Skipping already existing in Supabase: {rec.get('company')} — {rec.get('title')}")
            continue

        def payload_for(job_id: str) -> list[dict]:
            return [{
                "job_id": job_id,
                "company": rec["company"],
                "role": rec["title"],
                "location": rec.get("location", "United States"),
                "lane": "direct-apply",
                "score": rec.get("score", 50),
                "track": "T1",   # tracks retired 2026-09-09; one lane, one score
                "domain": rec.get("domain", ""),
                "req_id": rec.get("req_id") or None,
                "resume": rec.get("resume_file", "resume_default"),
                "job_url": rec.get("link", rec.get("apply_url", "")),
                "found_date": today_str,
                "referral_state": "direct-apply",
                "status": "pending",
                "notes": f"[Direct Apply] Resume {rec.get('resume_file', '')} compiled.",
            }]

        if dry_run:
            current_idx += 1
            job_id = f"ja-{month_day}-{current_idx:02d}"
            contact_sources.append({**rec, "job_id": job_id})
            print(f"  [DRY-RUN] Would insert into Supabase: {job_id} | {rec['company']} | {rec['title']}")
            inserted_count += 1
            continue

        for _attempt in range(50):
            current_idx += 1
            job_id = f"ja-{month_day}-{current_idx:02d}"
            req = urllib.request.Request(endpoint, data=json.dumps(payload_for(job_id)).encode("utf-8"),
                                         headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req) as resp:
                    if resp.status in (200, 201):
                        inserted_count += 1
                        contact_sources.append({**rec, "job_id": job_id})
                        print(f"  Inserted into Supabase: {job_id} | {rec['company']} | {rec['title']}")
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="ignore")
                if e.code == 409 or "23505" in body:      # another run took this id — try the next one
                    print(f"  {job_id} already taken by a concurrent run, retrying with the next id")
                    continue
                print(f"  HTTP error inserting {rec['company']}: {e.code} - {body}", file=sys.stderr)
                break
            except Exception as e:
                print(f"  Error inserting {rec['company']}: {e}", file=sys.stderr)
                break
        else:
            print(f"  Gave up allocating a job_id for {rec['company']} after 50 collisions", file=sys.stderr)

    # Persist the 1-click recruiter + team-lead people-search links into the
    # source-of-truth contacts table (Supabase `contacts`), keyed to each new
    # job_id. This is the step that was missing — the links only ever reached the
    # markdown handoffs before, never the contacts table.
    try:
        import networking_sheet
        contact_rows = networking_sheet.contacts_from_records(contact_sources)
        if not contact_rows:
            print("  No recruiter/team-lead links to persist to contacts.")
        elif dry_run:
            print(f"  [DRY-RUN] Would upsert {len(contact_rows)} contact(s) "
                  f"(recruiter + team-lead links) to Supabase.")
        else:
            n = len(networking_sheet._post(contact_rows))
            print(f"  Upserted {n} contact(s) (recruiter + team-lead links) to Supabase.")
    except Exception as e:
        print(f"  Warning: contacts upsert failed: {e}", file=sys.stderr)

    return inserted_count

def update_seen_jobs(records: list[dict]):
    """Append new records to seen_jobs.csv."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    existing_urls = set()
    
    if SEEN_JOBS_CSV.exists():
        with open(SEEN_JOBS_CSV, mode="r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "http" in line:
                    existing_urls.add(line.strip())
                    
    pushed = []
    with open(SEEN_JOBS_CSV, mode="a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for rec in records:
            url = rec.get("link") or rec.get("apply_url") or ""
            if url and url not in existing_urls:
                writer.writerow([rec["company"], rec["title"], rec.get("location", ""), url, today_str, "applied_pending"])
                pushed.append({"first_seen_date": today_str, "market": "US", "company": rec["company"], "title": rec["title"],
                               "city": rec.get("location", ""), "job_url": url,
                               "fingerprint": ledger.fingerprints(rec["company"], rec["title"])[0],
                               "status": "applied_pending", "req_id": rec.get("req_id", "")})
    ledger.push_rows(pushed)   # shared ledger: other machines / tools see these as applied

def rebuild_tracker(dry_run: bool = False):
    """Sync the tracker's drop-notes into learning_log.md (./refresh.sh --fetch).
    The tracker page itself reads Supabase live on every open, so the rows written
    above are already visible — nothing to deploy."""
    if dry_run:
        print("  [DRY-RUN] Skipping ./refresh.sh --fetch (learning_log sync).")
        return

    print("\nSyncing drop reviews into learning_log.md via ./refresh.sh --fetch...")
    res = subprocess.run(["./refresh.sh", "--fetch"], cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        for line in res.stdout.splitlines()[-3:]:
            print(f"    {line}")
        print("  Done. Open (or reload) job_tracker.html — it reads Supabase live, nothing to upload.")
    else:
        print(f"  learning_log sync warning: {res.stderr}", file=sys.stderr)

def records_from_handoff(tailored_md: str, ranked: list[dict]) -> list[dict]:
    """
    Stage-4 records from the customiser's handoff. The customiser writes only
    `.pipeline/tailored.md` (a subagent, not a script — see docs/audits item 1);
    its table header is `| # | Company | Title | Track | .tex | .pdf |`. Each row
    is joined to its `ranked.json` row on (company, title), which carries the
    location, score, links and the recruiter/team-lead search URLs Stage 4 needs.
    """
    by_key = {((r.get("company") or "").strip().lower(), (r.get("title") or "").strip().lower()): r
              for r in ranked}
    out, missing = [], []
    for line in tailored_md.splitlines():
        # a literal "|" inside a cell (e.g. a company name) must be escaped "\|"
        # by the customiser so it isn't mistaken for a column separator here.
        escaped = line.strip().strip("|").replace("\\|", "\x00")
        cells = [c.strip().strip("`*").strip().replace("\x00", "|") for c in escaped.split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        _, company, title, _track, tex, pdf = cells[:6]
        row = by_key.get((company.lower(), title.lower()))
        if row is None:  # the customiser trimmed a long title: accept a unique prefix match
            cands = [r for (co, ti), r in by_key.items() if co == company.lower() and ti.startswith(title.lower())]
            row = cands[0] if len(cands) == 1 else None
        if row is None:
            missing.append(f"{company} — {title}")
            continue
        rec = {k: v for k, v in row.items() if k != "description"}
        rec.update(tex_path=tex, resume_file=pdf)
        out.append(rec)
    if missing:
        raise SystemExit("tailored.md rows with no matching ranked.json row (company/title must match exactly): "
                         + "; ".join(missing))
    return out


def self_test() -> None:
    md = ("| # | Company | Title | Track | .tex | .pdf |\n|---|---|---|---|---|---|\n"
          "| 1 | **Acme** | Quality Engineer | 0 | `x/src/resume_Acme_QE.tex` | `x/resume_Acme_QE.pdf` |\n"
          "| 2 | Beta | Process Engineer | 1 | b.tex | b.pdf |\n")
    ranked = [{"company": "Acme", "title": "Quality Engineer", "score": 80, "link": "u", "description": "long"},
              {"company": "Beta", "title": "process engineer - Ottawa (Spring)", "score": 70, "link": "v", "description": "long"}]
    recs = records_from_handoff(md, ranked)
    assert [r["company"] for r in recs] == ["Acme", "Beta"]          # Beta joined by unique title prefix
    try:
        records_from_handoff(md, ranked + [{"company": "Beta", "title": "Process Engineer II"}])
        raise AssertionError("ambiguous prefix must fail loudly")
    except SystemExit:
        pass
    assert recs[0]["resume_file"] == "x/resume_Acme_QE.pdf" and recs[0]["score"] == 80
    assert "description" not in recs[0]
    try:
        records_from_handoff(md, ranked[:1]); raise AssertionError("unmatched row must fail loudly")
    except SystemExit as e:
        assert "Beta" in str(e)
    print("OK  log_and_refresh self-check passed")


def main():
    load_env()
    dry_run = "--dry-run" in sys.argv

    tailored_json_path = PIPELINE_DIR / "tailored.json"
    if tailored_json_path.exists():
        records = json.loads(tailored_json_path.read_text(encoding="utf-8"))
    else:
        md, ranked = PIPELINE_DIR / "tailored.md", PIPELINE_DIR / "ranked.json"
        if not (md.exists() and ranked.exists()):
            print(f"Error: need {md} and {ranked}. Stages 2 and 3 must run first.", file=sys.stderr)
            sys.exit(1)
        records = records_from_handoff(md.read_text(encoding="utf-8"),
                                       json.loads(ranked.read_text(encoding="utf-8")))
        tailored_json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"Built {tailored_json_path} from tailored.md + ranked.json ({len(records)} rows).")
        
    if not records:
        print("No tailored records found to log.")
        sys.exit(0)
        
    print(f"Logging {len(records)} application records...")
    inserted = insert_to_supabase(records, dry_run=dry_run)
    print(f"Supabase sync complete: {inserted} records logged.")
    
    if not dry_run:
        update_seen_jobs(records)
        
    rebuild_tracker(dry_run=dry_run)

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    main()
