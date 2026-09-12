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
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates"
    }
    
    current_idx = max_idx
    contact_sources = []  # inserted rows, stamped with job_id, for contacts upsert
    for rec in records:
        sig = f"{rec.get('company', '').lower()}|{rec.get('title', '').lower()}"
        if sig in existing_sigs:
            print(f"  Skipping already existing in Supabase: {rec.get('company')} — {rec.get('title')}")
            continue

        current_idx += 1
        job_id = f"ja-{month_day}-{current_idx:02d}"
        contact_sources.append({**rec, "job_id": job_id})

        # Two-track model (matches tools/gate_and_score.py): T2 = Curated Target
        # lane (anchor companies + top-domain fit), T1 = Broad-Fit Direct Apply.
        # T3 is retired — it was the old three-track era and is what left ~150
        # historical rows mis-tagged. Drive the tag off the scorer's lane, not the
        # fetch-time domain label.
        lane_val = "direct-apply"
        track_val = "T1"   # tracks retired 2026-09-09; one lane, one score
        tag = "[Direct Apply]"
        
        payload = [{
            "job_id": job_id,
            "company": rec["company"],
            "role": rec["title"],
            "location": rec.get("location", "United States"),
            "lane": lane_val,
            "score": rec.get("score", 50),
            "track": track_val,
            "resume": rec.get("resume_file", "resume_default"),
            "job_url": rec.get("link", rec.get("apply_url", "")),
            "found_date": today_str,
            "referral_state": "direct-apply",
            "status": "pending",
            "notes": f"{tag} 45-Day Sprint — Resume {rec.get('resume_file', '')} compiled."
        }]
        
        if dry_run:
            print(f"  [DRY-RUN] Would insert into Supabase: {job_id} | {rec['company']} | {rec['title']}")
            inserted_count += 1
            continue
            
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status in (200, 201):
                    inserted_count += 1
                    print(f"  Inserted into Supabase: {job_id} | {rec['company']} | {rec['title']}")
        except urllib.error.HTTPError as e:
            print(f"  HTTP error inserting {rec['company']}: {e.code} - {e.read().decode('utf-8')}", file=sys.stderr)
        except Exception as e:
            print(f"  Error inserting {rec['company']}: {e}", file=sys.stderr)

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
                    
    with open(SEEN_JOBS_CSV, mode="a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for rec in records:
            url = rec.get("link") or rec.get("apply_url") or ""
            if url and url not in existing_urls:
                writer.writerow([rec["company"], rec["title"], rec.get("location", ""), url, today_str, "applied_pending"])

def rebuild_tracker(dry_run: bool = False):
    """Run ./refresh.sh --fetch to rebuild the HTML tracker artifact."""
    if dry_run:
        print("  [DRY-RUN] Skipping ./refresh.sh --fetch.")
        return
        
    print("\nRebuilding Tracker via ./refresh.sh --fetch...")
    cmd = ["./refresh.sh", "--fetch"]
    res = subprocess.run(cmd, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        print("  Tracker rebuild successful.")
        for line in res.stdout.splitlines()[-5:]:
            print(f"    {line}")
    else:
        print(f"  Tracker rebuild warning: {res.stderr}", file=sys.stderr)

def main():
    load_env()
    dry_run = "--dry-run" in sys.argv
    
    tailored_json_path = PIPELINE_DIR / "tailored.json"
    if not tailored_json_path.exists():
        print(f"Error: {tailored_json_path} not found. Stage 3 (customiser) must run first.", file=sys.stderr)
        sys.exit(1)
        
    with open(tailored_json_path, "r", encoding="utf-8") as f:
        records = json.load(f)
        
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
    main()
