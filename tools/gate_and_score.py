#!/usr/bin/env python3
"""
gate_and_score.py — Hard Gating (ITAR/Visa) and Dual-Track Fit Scoring.
Authoritative implementation matching playbook/P1_06_scoring_rubric.md and AGENTS.md.

1. Gate 0: Verbatim Eligibility Gate (ITAR, Citizenship, Clearance, Sponsorship, Company Intel).
2. Track Classification: T1 (Semiconductor/Adv Mfg), T2 (Aerospace/eVTOL/Composites), T3 (QMS).
3. 5-Axis Fit Scoring (0-100):
   - A. Sponsorship Odds (30 pts, data/uscis_h1b_lookup.json + positive visa cues)
   - B. Skills / Role Fit (30 pts, per-track bullseye keyword density)
   - C. Seniority Fit (20 pts, 0-2 yrs / Entry / Associate target)
   - D. Domain Priority (10 pts, per-track domain alignment)
   - E. Logistics (10 pts, salary, location, recency, direct employer)
4. Routing:
   - Track 2: Curated Target (an anchor company from config, or a top-domain fit >= 75)
   - Track 1: Broad-Fit Apply (Score >= 50, genuine QE / Process / Mfg role)
   - Drop (Score < 50, off-discipline, or Gate 0 failure)
"""

import sys
import os
import json
import csv
import re
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import load_config, classify_domain  # noqa: E402

CONFIG = load_config()

USCIS_LOOKUP_FILE = ROOT_DIR / "data" / "uscis_h1b_lookup.json"
COMPANY_INTEL_FILE = ROOT_DIR / "company_intel.md"
SEEN_JOBS_CSV = ROOT_DIR / "seen_jobs.csv"

# Hard Visa / ITAR regex patterns
VISA_ITAR_PATTERNS = [
    (r'(?i)\b(u\.?s\.?\s*citizen(?:ship)?(?:\s+only|\s+required)?)\b', "U.S. Citizenship Required"),
    (r'(?i)\b(security\s+clearance|active\s+secret|top\s+secret|ts/sci|dod\s+clearance)\b', "Security Clearance Required"),
    (r'(?i)\b(itar|export\s+control|ear99|us\s+person\s+status|defense\s+trade\s+controls)\b', "ITAR / Export Control Restriction"),
    (r'(?i)\b(no\s+(?:visa\s+)?sponsorship|will\s+not\s+(?:now\s+or\s+in\s+the\s+future\s+)?sponsor|not\s+offering\s+sponsorship|unable\s+to\s+sponsor|without\s+sponsorship\s+now\s+or\s+in\s+the\s+future)\b', "No Visa Sponsorship Policy"),
    (r'(?i)\b(permanent\s+resident\s+only|green\s+card\s+holder\s+only)\b', "Permanent Resident / Green Card Only")
]

# Explicit Company-level intel skips (company_intel.md)
KNOWN_NON_SPONSORS = CONFIG["known_non_sponsors"]

TARGET_ANCHORS = CONFIG["target_anchors"]

# Unified candidate master toolkit (grounded in data/candidate_resume_database.json)
CANDIDATE_MASTER_TOOLKIT = CONFIG["master_toolkit"]

# Staffing Agencies (Section 8)
STAFFING_AGENCIES = CONFIG["staffing_agencies"]

def load_seen_ledger() -> tuple[set[str], set[str], set[str]]:
    """Load seen URLs, LinkedIn IDs, and normalized company|title fingerprints from seen_jobs.csv."""
    seen_urls = set()
    seen_job_ids = set()
    seen_fingerprints = set()
    
    if not SEEN_JOBS_CSV.exists():
        return seen_urls, seen_job_ids, seen_fingerprints
        
    try:
        with open(SEEN_JOBS_CSV, "r", encoding="utf-8", errors="ignore") as f:
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
                        seen_fingerprints.add(f"{co}|{title}")
                if len(row) >= 7 and row[6]:
                    raw_fp = re.sub(r'[^a-z0-9|]', '', row[6].lower())
                    seen_fingerprints.add(raw_fp)
    except Exception as e:
        print(f"Warning loading seen_jobs.csv in ranker: {e}", file=sys.stderr)
        
    return seen_urls, seen_job_ids, seen_fingerprints

SEEN_URLS, SEEN_JOB_IDS, SEEN_FINGERPRINTS = load_seen_ledger()

def check_seen_ledger(job: dict) -> tuple[bool, str]:
    """Check if job has already been surfaced/applied in seen_jobs.csv."""
    url = (job.get("link") or job.get("apply_url") or "").strip()
    clean_u = url.split("?")[0].rstrip("/")
    co = re.sub(r'[^a-z0-9]', '', (job.get("company") or "").lower())
    title = re.sub(r'[^a-z0-9]', '', (job.get("title") or "").lower())
    fp = f"{co}|{title}"
    
    m = re.search(r'(\d{8,12})', clean_u)
    job_id = m.group(1) if m else None
    
    if clean_u and clean_u in SEEN_URLS:
        return True, f"Exact URL match in seen ledger ({clean_u})"
    if job_id and job_id in SEEN_JOB_IDS:
        return True, f"LinkedIn Job ID match in seen ledger ({job_id})"
    if fp and fp in SEEN_FINGERPRINTS:
        return True, f"Company & Title match in seen ledger ({job.get('company')} — {job.get('title')})"
        
    return False, ""

def load_uscis_lookup() -> dict:
    if not USCIS_LOOKUP_FILE.exists():
        return {}
    try:
        with open(USCIS_LOOKUP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning loading USCIS lookup: {e}", file=sys.stderr)
        return {}

USCIS_DATA = load_uscis_lookup()

def get_uscis_approvals(company: str) -> int:
    """Lookup approval count for company in USCIS database."""
    if not USCIS_DATA or not company:
        return 0
    co_norm = company.strip().upper()
    
    # Exact match first
    if co_norm in USCIS_DATA:
        return USCIS_DATA[co_norm].get("approvals", 0)
        
    # Substring match
    total_approvals = 0
    matches = 0
    for name, data in USCIS_DATA.items():
        if co_norm in name or (len(co_norm) > 4 and name in co_norm):
            total_approvals = max(total_approvals, data.get("approvals", 0))
            matches += 1
            if matches > 10:
                break
    return total_approvals

def check_eligibility_gate(job: dict) -> tuple[bool, str, str]:
    """
    Step 0: Eligibility Gate.
    Returns (passed: bool, verdict: str, quoted_reason: str).
    """
    company_lower = job.get("company", "").strip().lower()
    title_lower = job.get("title", "").strip().lower()
    desc = job.get("description", "")
    full_text = f"{title_lower} {company_lower} {desc}"
    
    # 1. Company-level known restrictions (company_intel.md)
    for co, reason in KNOWN_NON_SPONSORS.items():
        if co in company_lower:
            return False, "VISA RISK (SKIP)", f"Company Gate: {reason}"
            
    # 2. Text-level ITAR / Citizenship / Clearance / No-Sponsorship regex check
    for pattern, label in VISA_ITAR_PATTERNS:
        match = re.search(pattern, full_text)
        if match:
            start = max(0, match.start() - 20)
            end = min(len(full_text), match.end() + 20)
            snippet = full_text[start:end].replace("\n", " ").strip()
            return False, "VISA RISK (SKIP)", f"{label} (Matched snippet: \"...{snippet}...\")"
            
    # 3. Technician / Operator / Assembler Gate
    if any(k in title_lower for k in ["machinist", "operator", "assembler", "welder", "fabricator", "apprentice", "internship", "intern", "staż", "werkstudent", "praktik", "alternance", "abschlussarbeit"]) or title_lower.startswith("stage "):
        return False, "DROP (NON-ENG)", "Shop-floor / apprentice / student internship role"

    if "technician" in title_lower and not any(
            k in title_lower for k in ["quality", "process", "manufacturing",
                                       "inspection", "cmm", "metrology", "qa", "qc"]):
        return False, "DROP (NON-ENG)", "Technician role not quality/process-adjacent"
        
    # 4. Seniority Gate (Section 3.4)
    if any(k in title_lower for k in ["principal", "director", "staff engineer", "head of", "senior manager", "executive"]):
        return False, "DROP (SENIORITY)", "Seniority too high (Manager/Director/Principal/Staff)"
        
    return True, "ELIGIBLE", ""

def calculate_fit_score(job: dict) -> tuple[int, dict, list[str], str, str]:
    """
    Calculate 0-100 Fit Score per Sprint Two-Track rubric.
    Returns (total_score, sub_scores, reasons, sprint_track, recommended_resume).
    """
    title = job.get("title", "").lower()
    company = job.get("company", "").lower()
    desc = job.get("description", "").lower()
    combined = f"{title} {company} {desc}"
    
    is_target_anchor = any(anchor in company for anchor in TARGET_ANCHORS)
    is_aero = any(k in combined for k in ["as9100", "aerospace", "evtol", "space", "aviation", "composites", "cfrp", "prepreg", "mrb", "airframe", "structures"])
    
    # A. Sponsorship Odds (30 pts)
    approvals = get_uscis_approvals(job.get("company", ""))
    spon_pts = 8 # Default neutral
    if is_target_anchor:
        spon_pts = 26
    elif approvals >= 50:
        spon_pts = 30
    elif approvals >= 10:
        spon_pts = 22
    elif approvals >= 1:
        spon_pts = 14
    else:
        # Known sponsors from the user's own config (config/search_profile.json).
        for tier in ("tier1", "tier2"):
            spec = CONFIG.get("known_sponsors", {}).get(tier) or {}
            if any(k in company for k in spec.get("companies", []) if k):
                spon_pts = spec.get("points", spon_pts)
                break
            
    # International roles (Europe / Australia skilled worker visa baseline)
    is_intl = job.get("source", "").endswith("intl") or any(k in job.get("location", "").lower() for k in ["europe", "australia", "germany", "france", "uk", "united kingdom", "netherlands", "sweden", "switzerland", "ireland", "austria"])
    if is_intl:
        spon_pts = max(spon_pts, 20)

    # Positive visa mention bonus (+5)
    if any(k in combined for k in ["visa sponsorship available", "will sponsor", "sponsorship provided", "opt", "cpt", "relocation provided", "visa support"]):
        spon_pts = min(30, spon_pts + 5)
        
    # B. Skills / Role Fit (30 pts) — Evaluated against candidate master toolkit
    matched_tools = [term for term in CANDIDATE_MASTER_TOOLKIT if term in combined]
    unique_matches = len(set(matched_tools))
    
    is_core_qe = any(k in title for k in ["quality engineer", "supplier quality", "manufacturing quality", "mrb", "process quality", "qms", "quality technician", "quality inspection technician", "cmm technician", "metrology technician", "qa technician", "qc technician"])
    is_mfg_process = any(k in title for k in ["process engineer", "manufacturing engineer", "composites engineer", "materials engineer", "production engineer", "process technician", "manufacturing technician"])
    
    if is_core_qe:
        if unique_matches >= 6:
            skills_pts = 30
        elif unique_matches >= 3:
            skills_pts = 24
        elif unique_matches >= 1:
            skills_pts = 18
        else:
            skills_pts = 14
    elif is_mfg_process:
        if unique_matches >= 5:
            skills_pts = 26
        elif unique_matches >= 2:
            skills_pts = 20
        else:
            skills_pts = 14
    else:
        if unique_matches >= 3:
            skills_pts = 16
        else:
            skills_pts = 8
            
    # C. Seniority Fit (20 pts)
    sen_pts = 12 # Default untitled / standard
    if any(k in title for k in ["entry", "associate", "new grad", "university", " i ", " 1", "level 1", "level i"]) or "engineer i" in title or title.endswith(" i") or title.endswith(" 1"):
        sen_pts = 20
    elif any(k in title for k in [" ii", " 2", "level 2", "level ii", "experienced"]):
        sen_pts = 6
    elif any(k in title for k in ["senior", "sr.", "sr "]):
        sen_pts = 4
        
    # D. Domain Priority (10 pts) — ranked by the order of `domains` in the config.
    #    First domain listed scores highest; the default bucket scores lowest.
    domain_label = classify_domain(job.get("company", ""), job.get("title", ""))
    domain_names = [d["name"] for d in CONFIG.get("domains", [])]
    if domain_label in domain_names:
        dom_pts = max(10 - domain_names.index(domain_label), 7)
    else:
        dom_pts = 6

    # Freshness Check
    freshness = job.get("freshness")
    freshness_badge = job.get("freshness_badge")
    freshness_detail = job.get("freshness_detail")
    if not freshness or not freshness_badge:
        m = re.search(r'(\d{8,12})', job.get("link") or job.get("apply_url") or "")
        if m and len(m.group(1)) == 10:
            jid = int(m.group(1))
            if jid < 4400000000:
                freshness, freshness_badge, freshness_detail = "REPOSTED", "🔄 REPOSTED", f"Reposted (Original ID {jid} ~months ago)"
            elif jid < 4455000000:
                freshness, freshness_badge, freshness_detail = "REPOSTED", "🔄 REPOSTED", f"Reposted (Original ID {jid} ~2-4 weeks ago)"
            else:
                freshness, freshness_badge, freshness_detail = "FRESH", "🟢 FRESH", f"Fresh (Created recently, ID {jid})"
        elif job.get("posted_at"):
            try:
                posted_date = datetime.strptime(job["posted_at"][:10], "%Y-%m-%d")
                delta_days = (datetime.now() - posted_date).days
                if delta_days > 14:
                    freshness, freshness_badge, freshness_detail = "REPOSTED", "🔄 REPOSTED", f"Reposted / Standing opening ({delta_days}d old)"
                else:
                    freshness, freshness_badge, freshness_detail = "FRESH", "🟢 FRESH", f"Fresh posting ({delta_days}d ago)"
            except Exception:
                freshness, freshness_badge, freshness_detail = "FRESH", "🟢 FRESH", "Fresh opening"
        else:
            freshness, freshness_badge, freshness_detail = "FRESH", "🟢 FRESH", "Fresh opening"
        job["freshness"] = freshness
        job["freshness_badge"] = freshness_badge
        job["freshness_detail"] = freshness_detail

    # E. Logistics (10 pts)
    log_pts = 6 # Base US location (3) + direct employer (1) + baseline (2)
    if freshness == "FRESH":
        log_pts += 2 # Fresh posting preference (+2 pts)
    if is_target_anchor:
        log_pts += 2
    if any(k in company for k in STAFFING_AGENCIES):
        log_pts = max(1, log_pts - 2)
        
    total_score = min(100, spon_pts + skills_pts + sen_pts + dom_pts + log_pts)
    
    sub_scores = {
        "sponsorship": spon_pts,
        "skills": skills_pts,
        "seniority": sen_pts,
        "domain": dom_pts,
        "logistics": log_pts
    }
    
    # Two-Track Sprint Classification
    if is_target_anchor or (is_aero and total_score >= 75):
        sprint_track = "Track 2: Curated Target"
    elif total_score >= 50:
        sprint_track = "Track 1: Broad-Fit Apply"
    else:
        sprint_track = "Drop"
        
    rec_resume = "Resume_Master"
    
    reasons = [
        f"Sponsorship ({spon_pts}/30) — USCIS / Employer filing signal",
        f"Skills ({skills_pts}/30) — {unique_matches} matched master toolkit keywords ({', '.join(matched_tools[:4]) if matched_tools else 'title match'})",
        f"Seniority ({sen_pts}/20) — Level alignment",
        f"Domain ({dom_pts}/10) — {domain_label}",
        f"Freshness: {freshness_badge} — {freshness_detail}"
    ]
    
    return total_score, sub_scores, reasons, sprint_track, rec_resume

def main():
    fetched_json_path = PIPELINE_DIR / "fetched.json"
    if not fetched_json_path.exists():
        print(f"Error: {fetched_json_path} does not exist. Run tools/fetch_jobs.py first.", file=sys.stderr)
        sys.exit(1)
        
    with open(fetched_json_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)
        
    ranked_jobs = []
    
    for job in jobs:
        # Step 0A: Seen Ledger Deduplication Gate
        is_seen, seen_reason = check_seen_ledger(job)
        if is_seen:
            ranked_jobs.append({
                **job,
                "score": 0,
                "sub_scores": {"sponsorship": 0, "skills": 0, "seniority": 0, "domain": 0, "logistics": 0},
                "verdict": "ALREADY SEEN (DEDUP)",
                "lane": "Drop",
                "track": "Drop",
                "reasons": [seen_reason],
                "recommended_resume": "N/A",
                "gate0_passed": False
            })
            continue

        # Step 0B: Eligibility Gate (ITAR / Visa / Intel)
        passed_gate0, verdict, gate_reason = check_eligibility_gate(job)
        
        if not passed_gate0:
            ranked_jobs.append({
                **job,
                "score": 0,
                "sub_scores": {"sponsorship": 0, "skills": 0, "seniority": 0, "domain": 0, "logistics": 0},
                "verdict": verdict,
                "lane": "Drop",
                "track": "Drop",
                "reasons": [gate_reason],
                "recommended_resume": "N/A",
                "gate0_passed": False
            })
            continue
            
        # Step 1: Fit Scoring & Two-Track Routing
        score, sub_scores, reasons, sprint_track, rec_resume = calculate_fit_score(job)
        
        if sprint_track == "Track 2: Curated Target":
            lane = "Track 2: Curated Target"
            verdict = "Strong Fit (Target Lane)"
        elif sprint_track == "Track 1: Broad-Fit Apply":
            lane = "Track 1: Broad-Fit Apply"
            verdict = "Strong Fit (Direct Apply)"
        else:
            lane = "Drop"
            verdict = "Below Fit Threshold (<50)"
            
        ranked_jobs.append({
            **job,
            "score": score,
            "sub_scores": sub_scores,
            "verdict": verdict,
            "lane": lane,
            "track": sprint_track,
            "reasons": reasons,
            "recommended_resume": rec_resume,
            "gate0_passed": True
        })
        
    # Sort raw passing jobs by score descending
    shortlisted_raw = sorted(
        [j for j in ranked_jobs if j["lane"] in ["Track 2: Curated Target", "Track 1: Broad-Fit Apply"]],
        key=lambda x: x["score"],
        reverse=True
    )
    
    # Anti-Spraying Rule: Limit to MAX_PER_COMPANY (default 2) per company in the daily shortlist.
    # Prevents automated ATS spam flags and protects candidate reputation at target employers.
    MAX_PER_COMPANY = 2
    company_counts = {}
    shortlisted = []
    company_cap_overflow = []
    
    for j in shortlisted_raw:
        co = re.sub(r'[^a-z0-9]', '', j.get("company", "").lower())
        count = company_counts.get(co, 0)
        if count < MAX_PER_COMPANY:
            company_counts[co] = count + 1
            shortlisted.append(j)
        else:
            j_copy = dict(j)
            j_copy["lane"] = "Company Cap Reserve"
            j_copy["verdict"] = f"Eligible (Held: Max {MAX_PER_COMPANY} roles/day for {j.get('company')})"
            company_cap_overflow.append(j_copy)

    below_threshold = [j for j in ranked_jobs if j["gate0_passed"] and j["lane"] == "Drop"]
    gated_out = [j for j in ranked_jobs if not j["gate0_passed"]]
    
    ordered_ranked = shortlisted + company_cap_overflow + below_threshold + gated_out
    
    # Write .pipeline/ranked.json
    ranked_json_path = PIPELINE_DIR / "ranked.json"
    with open(ranked_json_path, "w", encoding="utf-8") as f:
        json.dump(ordered_ranked, f, indent=2)
        
    # Write .pipeline/ranked.md (Gate A Table)
    ranked_md_path = PIPELINE_DIR / "ranked.md"
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    with open(ranked_md_path, "w", encoding="utf-8") as f:
        f.write(f"# 🎯 Scored Shortlist & Fit Evaluation (Gate A) — {today_str}\n\n")
        f.write(f"**Run Summary:** Evaluated **{len(ranked_jobs)}** postings (**{len(shortlisted)}** shortlisted across {len(company_counts)} companies, **{len(company_cap_overflow)}** held in anti-spraying reserve, **{len(below_threshold)}** below fit threshold, **{len(gated_out)}** gated out on visa/ITAR/intel).\n\n")
        f.write(f"> 🛡️ **Anti-Spraying Policy:** Maximum of **{MAX_PER_COMPANY} roles per company** prioritized per daily batch to protect ATS candidate standing and avoid automated spam rejections.\n\n")
        
        f.write("### 🎯 Shortlist (Approved for Customization)\n\n")
        f.write("| # | Pass | Score | Freshness | Verdict | Title | Company | Location | Track | Recommended Resume | Apply URL | 1-Click Networking |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        
        for idx, job in enumerate(shortlisted, start=1):
            url_display = f"[Apply Link]({job['link']})" if job['link'] else "N/A"
            recruiter_link = f"[Recruiter]({job.get('recruiter_url', '#')})" if job.get('recruiter_url') else "—"
            peer_link = f"[Team Lead]({job.get('peer_url', '#')})" if job.get('peer_url') else "—"
            fresh_badge = job.get('freshness_badge', '🟢 FRESH')
            pass_label = job.get('pass', 'Pass 1')
            f.write(f"| {idx} | `{pass_label}` | **{job['score']}** | {fresh_badge} | {job['verdict']} | **{job['title']}** | {job['company']} | {job['location']} | `{job['track']}` | `{job['recommended_resume']}` | {url_display} | {recruiter_link} · {peer_link} |\n")
            
        f.write("\n\n### 📂 Shortlist Breakdown by Search Pass\n\n")
        pass_names = {
            "Pass 1": "Pass 1: Core Anchors & Aerospace/Composites Quality (US)",
            "Pass 2": "Pass 2: Semiconductor Fab & CleanTech/EV Sponsors (US)",
            "Pass 3": "Pass 3: Open Quality/Process Engineering & Technicians (US)",
            "Pass 4": "Pass 4: Curated International (Europe + Australia)"
        }
        for p_key in ["Pass 1", "Pass 2", "Pass 3", "Pass 4"]:
            p_jobs = [j for j in shortlisted if j.get("pass") == p_key]
            f.write(f"#### {pass_names.get(p_key, p_key)} ({len(p_jobs)} roles)\n\n")
            if not p_jobs:
                f.write("_No roles shortlisted from this pass._\n\n")
                continue
            f.write("| Score | Freshness | Title | Company | Location | Track | Apply Link |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for j in p_jobs:
                url_display = f"[Apply Link]({j['link']})" if j['link'] else "N/A"
                f.write(f"| **{j['score']}** | {j.get('freshness_badge', '🟢 FRESH')} | **{j['title']}** | {j['company']} | {j['location']} | `{j['track']}` | {url_display} |\n")
            f.write("\n")

        f.write("\n\n### 💡 Why These Ranked Highest (Match Fit & Sub-Scores)\n")
        for idx, job in enumerate(shortlisted, start=1):
            recruiter_link = f"[LinkedIn Recruiter Search]({job.get('recruiter_url', '#')})" if job.get('recruiter_url') else "—"
            peer_link = f"[LinkedIn Team Lead Search]({job.get('peer_url', '#')})" if job.get('peer_url') else "—"
            sub = job.get("sub_scores", {})
            pass_label = job.get('pass', 'Pass 1')
            f.write(f"\n**{idx}. [{pass_label}] {job['title']} at {job['company']} (Score: {job['score']})**\n")
            f.write(f"- **Sub-Scores:** Spon: {sub.get('sponsorship',0)}/30 | Skills: {sub.get('skills',0)}/30 | Sen: {sub.get('seniority',0)}/20 | Dom: {sub.get('domain',0)}/10 | Log: {sub.get('logistics',0)}/10\n")
            for r in job["reasons"]:
                f.write(f"- {r}\n")
            f.write(f"- **Source Contacts:** 🤝 {recruiter_link} · 👥 {peer_link}\n")
                
        if company_cap_overflow:
            f.write("\n\n### 🛡️ Company Daily Cap Reserve (Held to Prevent ATS Spam / Spraying)\n\n")
            f.write(f"> These roles passed Gate 0 and scored highly, but are held in reserve because the company already reached the daily cap of **{MAX_PER_COMPANY} applications**.\n\n")
            f.write("| Score | Freshness | Title | Company | Location | Track | Apply URL |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for job in company_cap_overflow:
                url_display = f"[Link]({job['link']})" if job['link'] else "N/A"
                f.write(f"| **{job['score']}** | {job.get('freshness_badge', '🟢 FRESH')} | **{job['title']}** | {job['company']} | {job['location']} | `{job['track']}` | {url_display} |\n")

        if below_threshold:
            f.write("\n\n### ⚠️ Below Fit Threshold (<50)\n\n")
            f.write("| Score | Verdict | Title | Company | Location | One-Line Rationale | Apply URL |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for job in below_threshold:
                reasons_str = "; ".join(job["reasons"])
                url_display = f"[Link]({job['link']})" if job['link'] else "N/A"
                f.write(f"| {job['score']} | {job['verdict']} | {job['title']} | {job['company']} | {job['location']} | {reasons_str} | {url_display} |\n")
                
        if gated_out:
            f.write("\n\n### 🚫 Excluded / Gated Out (Verbatim Eligibility Gate)\n\n")
            for job in gated_out:
                reasons_str = "; ".join(job["reasons"])
                url_display = f"[Posting Link]({job['link']})" if job['link'] else "N/A"
                f.write(f"- **{job['company']} — {job['title']}**: `{job['verdict']}` — {reasons_str}. {url_display}\n")
                
        f.write("\n\n---\n")
        f.write("### 🧑 Next Action (Gate A Approval)\n")
        f.write("Please review the shortlist table above and approve the rows to tailor.\n")
            
    print(f"Ranking complete: {len(ranked_jobs)} postings evaluated ({len(shortlisted)} shortlisted).")
    print(f"Handoffs saved to:\n  - {ranked_json_path}\n  - {ranked_md_path}")

if __name__ == "__main__":
    main()

