#!/usr/bin/env python3
"""
fetch_jobs.py — Unified Fetcher for Fortify 45-Day Sprint.

Combines:
1. Free direct ATS board scans (Greenhouse, Workday, SmartRecruiters, Lever via tools/ats_scan.mjs)
2. Targeted Apify LinkedIn Scraper runs (curious_coder/linkedin-jobs-scraper)
3. Cumulative Multi-Pass Discovery with deduplication against seen_jobs.csv and previous passes
4. Geo-Gate Filtering (US only)
5. Automated Zero-API LinkedIn People Search Links (Recruiter & Team Lead links per job)
6. Standardized handoff generation (.pipeline/fetched.json & .pipeline/fetched.md)
"""

import sys
import os
import json
import csv
import subprocess
import urllib.request
import urllib.parse
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import load_config, classify_domain, peer_role_keyword  # noqa: E402

CONFIG = load_config()

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
SEEN_JOBS_CSV = ROOT_DIR / "seen_jobs.csv"
PORTALS_JSON = ROOT_DIR / "tools" / "portals.json"
ATS_SCAN_MJS = ROOT_DIR / "tools" / "ats_scan.mjs"

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
ACTOR_ID = "curious_coder~linkedin-jobs-scraper"

# Geo-block list
BLOCKED_LOCATIONS = CONFIG["search"]["blocked_locations"]

def is_geo_blocked(location: str) -> bool:
    """Check if location is outside the US."""
    if not location:
        return False
    loc_lower = location.lower()
    for country in BLOCKED_LOCATIONS:
        if country in loc_lower:
            return True
    return False

def load_seen_signatures() -> tuple[set[str], set[str], set[str]]:
    """Load existing job URLs, LinkedIn IDs, and normalized company|title signatures from seen_jobs.csv."""
    seen_urls = set()
    seen_job_ids = set()
    seen_fps = set()
    if not SEEN_JOBS_CSV.exists():
        return seen_urls, seen_job_ids, seen_fps
    try:
        with open(SEEN_JOBS_CSV, mode="r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if not row:
                    continue
                for item in row:
                    if item and item.startswith("http"):
                        clean_u = item.split("?")[0].rstrip("/")
                        seen_urls.add(clean_u)
                        m = re.search(r'(\d{8,12})', clean_u)
                        if m:
                            seen_job_ids.add(m.group(1))
                if len(row) >= 4:
                    co = re.sub(r'[^a-z0-9]', '', (row[2] or '').lower())
                    title = re.sub(r'[^a-z0-9]', '', (row[3] or '').lower())
                    if co and title:
                        seen_fps.add(f"{co}|{title}")
                if len(row) >= 7 and row[6]:
                    raw_fp = re.sub(r'[^a-z0-9|]', '', row[6].lower())
                    seen_fps.add(raw_fp)
    except Exception as e:
        print(f"Warning reading seen_jobs.csv: {e}", file=sys.stderr)
    return seen_urls, seen_job_ids, seen_fps

def load_existing_fetched() -> list[dict]:
    """Load existing jobs from .pipeline/fetched.json if available."""
    fetched_json_path = PIPELINE_DIR / "fetched.json"
    if fetched_json_path.exists():
        try:
            with open(fetched_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def run_ats_scan() -> list[dict]:
    """Execute tools/ats_scan.mjs and return parsed job list."""
    print("Running free direct ATS scan across target portals...")
    cmd = ["node", str(ATS_SCAN_MJS), str(PORTALS_JSON)]
    try:
        res = subprocess.run(cmd, cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            print(f"  ATS scan completed: {len(data)} raw postings returned.")
            return data
        else:
            print(f"  ATS scan error: {res.stderr}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"  ATS scan exception: {e}", file=sys.stderr)
        return []

def run_apify_linkedin_search(urls: list[str], max_charge_usd: float = 0.35, count: int = 50) -> list[dict]:
    """Run Apify LinkedIn job scraper actor for targeted search URLs."""
    if not APIFY_TOKEN:
        print("  Apify token not configured, skipping Apify search.", file=sys.stderr)
        return []
    
    print(f"Running Apify LinkedIn search ({len(urls)} target URLs, max charge ${max_charge_usd:.2f}, count {count})...")
    payload = {
        "urls": urls,
        "count": count,
        "scrapeCompany": False,
        "maxTotalChargeUsd": max_charge_usd
    }
    
    api_url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}&fields=title,companyName,location,postedAt,seniorityLevel,link,applyUrl,companyWebsite,descriptionText"
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "JobSearchPipeline/1.0"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"  Apify scrape completed: {len(data)} postings returned.")
            return data
    except Exception as e:
        print(f"  Apify scrape exception: {e}", file=sys.stderr)
        return []

def generate_linkedin_people_links(company: str, title: str) -> tuple[str, str]:
    """Generate zero-API LinkedIn People Search links for Recruiter and Team Lead."""
    co_clean = company.strip()
    recruiter_kw = f'"{co_clean}" recruiter OR "talent acquisition"'
    recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(recruiter_kw)}&origin=GLOBAL_SEARCH_HEADER"
    
    role_kw = peer_role_keyword(title)

    peer_kw = f'"{co_clean}" {role_kw}'
    peer_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(peer_kw)}&origin=GLOBAL_SEARCH_HEADER"
    
    return recruiter_url, peer_url

def classify_job_freshness(link: str, posted_at: str, description: str = "") -> tuple[str, str, str]:
    """
    Classify whether a job is fresh or reposted.
    Returns (freshness_status, freshness_badge, freshness_detail)
    Status: 'FRESH' or 'REPOSTED'
    Badge: '🟢 FRESH' or '🔄 REPOSTED'
    """
    # Check 1: LinkedIn 10-digit Job ID threshold
    # LinkedIn IDs are sequentially assigned 64-bit integers.
    # In Sept 2026, fresh jobs created within the last week have IDs >= 4455000000.
    # Older IDs (< 4455000000) like 3950..., 4432..., 4444... were created weeks/months ago and re-listed.
    m = re.search(r'(\d{8,12})', link or '')
    if m and len(m.group(1)) == 10:
        jid = int(m.group(1))
        if jid < 4400000000:
            return "REPOSTED", "🔄 REPOSTED", f"Reposted (Original ID {jid} ~months ago)"
        elif jid < 4455000000:
            return "REPOSTED", "🔄 REPOSTED", f"Reposted (Original ID {jid} ~2-4 weeks ago)"
        else:
            return "FRESH", "🟢 FRESH", f"Fresh (Created recently, ID {jid})"

    # Check 2: Direct ATS or posted date string
    if posted_at:
        try:
            posted_date = datetime.strptime(posted_at[:10], "%Y-%m-%d")
            delta_days = (datetime.now() - posted_date).days
            if delta_days > 14:
                return "REPOSTED", "🔄 REPOSTED", f"Reposted / Standing opening ({delta_days}d old, posted {posted_at[:10]})"
            else:
                return "FRESH", "🟢 FRESH", f"Fresh posting ({delta_days}d ago, posted {posted_at[:10]})"
        except Exception:
            pass

    # Check 3: Description text keywords
    desc_lower = description.lower()
    if any(k in desc_lower for k in ["reposted", "re-posted", "[repost]"]):
        return "REPOSTED", "🔄 REPOSTED", "Reposted (tagged in posting text)"

    return "FRESH", "🟢 FRESH", "Fresh opening"

def normalize_job(item: dict, source_type: str, pass_num: int = 1) -> dict:
    """Normalize job entry into standard schema."""
    title = item.get("title", "").strip()
    company = item.get("companyName", item.get("company", "")).strip()
    location = item.get("location", "").strip()
    link = item.get("link", item.get("applyUrl", "")).strip()
    apply_url = item.get("applyUrl", link).strip()
    posted_at = item.get("postedAt", "").strip()
    description = item.get("descriptionText", item.get("description", "")).strip()
    
    track = classify_domain(company, title)
        
    recruiter_url, peer_url = generate_linkedin_people_links(company, title)
    freshness_status, freshness_badge, freshness_detail = classify_job_freshness(link, posted_at, description)

    return {
        "title": title,
        "company": company,
        "location": location,
        "link": link,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "description": description,
        "track": track,
        "source": source_type,
        "pass": f"Pass {pass_num}",
        "pass_num": pass_num,
        "recruiter_url": recruiter_url,
        "peer_url": peer_url,
        "freshness": freshness_status,
        "freshness_badge": freshness_badge,
        "freshness_detail": freshness_detail,
        "mass_posted_locations": []
    }

def load_local_jds() -> list[dict]:
    """Scan JDs/ directory for today's folder (e.g. JDs/08:31) and parse manual JDs."""
    today_mm_dd = datetime.now().strftime("%m:%d")
    alt_today = datetime.now().strftime("%m-%d")
    
    candidates_dirs = [
        ROOT_DIR / "JDs" / today_mm_dd,
        ROOT_DIR / "JDs" / alt_today,
        ROOT_DIR / "JDs" / "08:31"
    ]
    
    found_jobs = []
    target_dir = None
    for d in candidates_dirs:
        if d.exists() and d.is_dir():
            target_dir = d
            break
            
    if not target_dir:
        return found_jobs
        
    print(f"Loading manual JDs from {target_dir}...")
    for f in target_dir.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            title_m = re.search(r'\*\*Title:\*\*\s*(.+)', content)
            source_m = re.search(r'\*\*Source:\*\*\s*\[(.*?)\]\((.*?)\)', content)
            
            raw_title = title_m.group(1).strip() if title_m else f.stem
            raw_title = re.sub(r'\s*\|\s*(?:Job Listings|Career Opportunities|S&B).*$', '', raw_title).strip()
            link = source_m.group(2).strip() if source_m else ''
            
            co = ''
            if 'mayvl.rec' in link or 'MEC' in content or 'Mayville' in content: co = 'Mayville Engineering Company (MEC)'
            elif 'ultipro.com/GOO' in link or 'Goodman' in content or 'Daikin' in content: co = 'Daikin / Goodman'
            elif 'curtisswright' in link or 'Curtiss-Wright' in content or 'Farris' in content: co = 'Curtiss-Wright (Farris)'
            elif 'magna' in link.lower() or 'Magna' in content: co = 'Magna International'
            elif 'kla' in link.lower() or 'KLA' in content: co = 'KLA Corporation'
            elif 'cranecompany' in link or 'Crane Co' in content: co = 'Crane Company'
            elif 'S&B' in content: co = 'S&B Engineers and Constructors'
            elif 'chris.my.salesforce-sites.com' in link: co = 'The Camfil Group'
            else: co = 'Manual Sourced Employer'
            
            loc = 'United States'
            loc_m = re.search(r'\*\*Location:\s*([^\*]+)\*\*', content) or re.search(r'Location:\s*([A-Za-z\s,]+)', content)
            if loc_m:
                loc = loc_m.group(1).strip()
            elif 'Milpitas' in content: loc = 'Milpitas, CA'
            elif 'Holland' in content: loc = 'Holland, MI'
            elif 'Brecksville' in content: loc = 'Brecksville, OH'
            elif 'Greenville' in content: loc = 'Greenville, SC'
            elif 'Los Angeles' in content: loc = 'Los Angeles, CA'
            elif 'Waller' in content: loc = 'Waller, TX'
            
            found_jobs.append({
                'title': raw_title,
                'company': co,
                'location': loc,
                'link': link,
                'apply_url': link,
                'description': content,
                'posted_at': datetime.now().strftime("%Y-%m-%d")
            })
        except Exception as e:
            print(f"  Error reading manual JD {f.name}: {e}", file=sys.stderr)
            
    print(f"  Loaded {len(found_jobs)} manual JDs.")
    return found_jobs

def main():
    pass_num = 1
    for arg in sys.argv:
        if arg.startswith("--pass="):
            pass_num = int(arg.split("=")[1])
            
    skip_apify = "--ats-only" in sys.argv
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    
    seen_urls_set, seen_ids_set, seen_fps_set = load_seen_signatures()
    existing_jobs = load_existing_fetched()
    for ej in existing_jobs:
        if "pass" not in ej:
            ej["pass"] = "Pass 1"
            ej["pass_num"] = 1
    print(f"Loaded {len(seen_urls_set)} URLs, {len(seen_ids_set)} IDs, {len(seen_fps_set)} fingerprints from seen_jobs.csv, {len(existing_jobs)} existing fetched jobs.")
    
    raw_jobs = list(existing_jobs)
    
    if pass_num == 1:
        # Pass 1: Local JDs + ATS Scan + Core Target LinkedIn Queries
        manual_results = load_local_jds()
        for item in manual_results:
            raw_jobs.append(normalize_job(item, source_type="manual_jd", pass_num=1))
            
        ats_results = run_ats_scan()
        for item in ats_results:
            raw_jobs.append(normalize_job(item, source_type="ats_direct", pass_num=1))
            
        if not skip_apify:
            queries_p1 = [
                # Anchors (Joby, AST SpaceMobile, Archer, Beta, Supernal)
                "https://www.linkedin.com/jobs/search/?keywords=%22Joby%22%20%28quality%20OR%20MRB%20OR%20process%20OR%20composites%29%20engineer&location=United%20States&f_TPR=r259200&f_E=2,3",
                "https://www.linkedin.com/jobs/search/?keywords=%22AST%20SpaceMobile%22%20%28quality%20OR%20manufacturing%20OR%20process%20OR%20supplier%29%20engineer&location=United%20States&f_TPR=r259200&f_E=2,3",
                # Micron & Target Mfg Anchors
                "https://www.linkedin.com/jobs/search/?keywords=%22Micron%22%20%28quality%20OR%20process%29%20engineer&location=United%20States&f_TPR=r259200&f_E=2,3",
                # Aerospace & Composites Quality
                "https://www.linkedin.com/jobs/search/?keywords=%28%22aerospace%22%20OR%20%22composites%22%29%20AND%20%28%22manufacturing%20quality%22%20OR%20%22supplier%20quality%22%20OR%20%22process%20engineer%22%29&location=United%20States&f_TPR=r259200&f_E=2,3"
            ]
            apify_results = run_apify_linkedin_search(queries_p1, max_charge_usd=0.25, count=25)
            for item in apify_results:
                raw_jobs.append(normalize_job(item, source_type="linkedin_apify", pass_num=1))
                
    elif pass_num == 2:
        # Pass 2: Semiconductor & Fab High-Sponsors + CleanTech / EV Sponsors
        print("Executing Pass 2: Semiconductor Fab & EV Sponsors (Micron, Applied Materials, KLA, ASML, Rivian, Cummins)...")
        queries_p2 = [
            "https://www.linkedin.com/jobs/search/?keywords=%28%22Applied%20Materials%22%20OR%20%22KLA%22%20OR%20%22ASML%22%20OR%20%22Lam%20Research%22%29%20AND%20%28%22quality%20engineer%22%20OR%20%22process%20engineer%22%20OR%20%22manufacturing%20engineer%22%20OR%20%22yield%20engineer%22%29&location=United%20States&f_TPR=r604800&f_E=2,3",
            "https://www.linkedin.com/jobs/search/?keywords=%28%22Rivian%22%20OR%20%22Cummins%22%20OR%20%22BorgWarner%22%20OR%20%22First%20Solar%22%20OR%20%22Panasonic%20Energy%22%29%20AND%20%28%22quality%20engineer%22%20OR%20%22process%20engineer%22%20OR%20%22manufacturing%20engineer%22%29&location=United%20States&f_TPR=r604800&f_E=2,3"
        ]
        apify_results = run_apify_linkedin_search(queries_p2, max_charge_usd=0.25, count=40)
        for item in apify_results:
            raw_jobs.append(normalize_job(item, source_type="linkedin_apify_p2", pass_num=2))
            
    elif pass_num == 3:
        # Pass 3: Broad Open Quality Engineering with Core Tools (PFMEA, SPC, 8D, AS9100, GD&T, CAPA)
        print("Executing Pass 3: Open Quality Engineering & Regulated Mfg Sponsors...")
        # Quality/process TECHNICIAN roles are now in scope — they routinely convert
        # into engineering. (Pure machinist/operator roles are still dropped by the
        # ranker's technician gate.) f_E=1 added to catch entry technician postings.
        tech_kw = ('("Quality Technician" OR "Process Technician" OR "Manufacturing Technician" '
                   'OR "CMM Technician" OR "Quality Inspection Technician" OR "Metrology Technician") '
                   'AND ("PFMEA" OR "SPC" OR "root cause" OR "AS9100" OR "ISO 9001" OR "GD&T")')
        queries_p3 = [
            "https://www.linkedin.com/jobs/search/?keywords=%28%22Quality%20Engineer%22%20OR%20%22Supplier%20Quality%20Engineer%22%29%20AND%20%28%22PFMEA%22%20OR%20%22SPC%22%20OR%20%228D%22%20OR%20%22AS9100%22%20OR%20%22GD%26T%22%29&location=United%20States&f_TPR=r604800&f_E=2,3",
            "https://www.linkedin.com/jobs/search/?keywords=%28%22Process%20Engineer%22%20OR%20%22Manufacturing%20Engineer%22%20OR%20%22Composites%20Engineer%22%29%20AND%20%28%22Root%20Cause%22%20OR%20%22Continuous%20Improvement%22%20OR%20%22Six%20Sigma%22%29&location=United%20States&f_TPR=r604800&f_E=2,3",
            f"https://www.linkedin.com/jobs/search/?keywords={urllib.parse.quote_plus(tech_kw)}&location=United%20States&f_TPR=r604800&f_E=1,2,3",
        ]
        apify_results = run_apify_linkedin_search(queries_p3, max_charge_usd=0.30, count=40)
        for item in apify_results:
            raw_jobs.append(normalize_job(item, source_type="linkedin_apify_p3", pass_num=3))

    elif pass_num == 4:
        # Pass 4: Curated International — Europe + Australia (+ global sponsors).
        # New-strategy expansion beyond the US. Results bypass the US-only geo gate
        # (source ends with "intl"). Engineer AND quality/process technician roles.
        print("Executing Pass 4: Curated International (Europe + Australia)...")
        intl_kw = ('("Quality Engineer" OR "Process Engineer" OR "Manufacturing Engineer" '
                   'OR "Quality Technician" OR "Process Technician") '
                   'AND ("PFMEA" OR "SPC" OR "root cause" OR "AS9100" OR "ISO 9001" '
                   'OR "continuous improvement")')
        intl_locations = ["European Union", "Australia"]  # extend as needed
        queries_intl = [
            "https://www.linkedin.com/jobs/search/?keywords="
            f"{urllib.parse.quote_plus(intl_kw)}&location={urllib.parse.quote_plus(loc)}"
            "&f_TPR=r604800&f_E=1,2,3"
            for loc in intl_locations
        ]
        apify_results = run_apify_linkedin_search(queries_intl, max_charge_usd=0.30, count=40)
        for item in apify_results:
            raw_jobs.append(normalize_job(item, source_type="linkedin_apify_intl", pass_num=4))

    # Deduplication & Geo-filtering
    survivors_map = {}
    seen_urls_in_run = set()
    
    for job in raw_jobs:
        url = job.get("link") or job.get("apply_url") or ""
        if not job.get("title") or not job.get("company"):
            continue
            
        # Geo-Gate Check — US-targeted passes drop foreign mass-posts, but the
        # curated international pass (source *_intl) is deliberately non-US, so it
        # bypasses the US-only gate.
        if is_geo_blocked(job.get("location", "")) and not job.get("source", "").endswith("intl"):
            continue
            
        clean_u = url.split("?")[0].rstrip("/") if url else ""
        co_clean = re.sub(r'[^a-z0-9]', '', (job['company'] or '').lower())
        title_clean = re.sub(r'[^a-z0-9]', '', (job['title'] or '').lower())
        fp = f"{co_clean}|{title_clean}"
        m = re.search(r'(\d{8,12})', clean_u)
        job_id = m.group(1) if m else None
        
        # Check vs seen_jobs.csv ledger
        if clean_u and clean_u in seen_urls_set:
            continue
        if job_id and job_id in seen_ids_set:
            continue
        if fp and fp in seen_fps_set:
            continue
            
        # Check vs current run deduplication
        if clean_u and clean_u in seen_urls_in_run:
            continue
        if clean_u:
            seen_urls_in_run.add(clean_u)
            
        sig = f"{job['company'].lower()}|{job['title'].lower()}"
        if sig in survivors_map:
            existing = survivors_map[sig]
            if job.get("location") and job["location"] != existing.get("location"):
                existing["mass_posted_locations"].append(job["location"])
            continue
            
        survivors_map[sig] = job
        
    survivors = list(survivors_map.values())
    
    for job in survivors:
        if job["mass_posted_locations"]:
            extra_count = len(job["mass_posted_locations"])
            job["location"] = f"{job['location']} (+{extra_count} cities)"
            
    print(f"\nFetch Summary (Pass {pass_num}): {len(raw_jobs)} total raw jobs -> {len(survivors)} deduplicated survivor jobs.")
    
    fetched_json_path = PIPELINE_DIR / "fetched.json"
    with open(fetched_json_path, "w", encoding="utf-8") as f:
        json.dump(survivors, f, indent=2)
        
    fetched_md_path = PIPELINE_DIR / "fetched.md"
    today_str = datetime.now().strftime("%Y-%m-%d")
    with open(fetched_md_path, "w", encoding="utf-8") as f:
        f.write(f"# Fetched Postings — {today_str} (Pass {pass_num})\n\n")
        f.write(f"**Total Raw Discovered:** {len(raw_jobs)} | **New Unique Survivors:** {len(survivors)}\n\n")
        f.write("| # | Company | Title | Location | Freshness | Track | Source | Apply Link | 1-Click Networking |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for idx, job in enumerate(survivors, start=1):
            url_display = f"[Apply Link]({job['link']})" if job['link'] else "N/A"
            recruiter_link = f"[Recruiter]({job['recruiter_url']})"
            peer_link = f"[Team Lead]({job['peer_url']})"
            fresh_badge = job.get('freshness_badge', '🟢 FRESH')
            f.write(f"| {idx} | **{job['company']}** | {job['title']} | {job['location']} | {fresh_badge} | {job['track']} | `{job['source']}` | {url_display} | {recruiter_link} · {peer_link} |\n")
            
    print(f"Handoffs saved to:\n  - {fetched_json_path}\n  - {fetched_md_path}")

if __name__ == "__main__":
    main()

