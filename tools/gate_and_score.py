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
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# Make sibling tools importable no matter how this file is invoked
# (python3 tools/x.py, cwd elsewhere, or imported from a test).
sys.path.insert(0, str(Path(__file__).resolve().parent))
PIPELINE_DIR = ROOT_DIR / ".pipeline"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import load_config, classify_domain  # noqa: E402

CONFIG = load_config()

USCIS_LOOKUP_FILE = ROOT_DIR / "data" / "uscis_h1b_lookup.json"
COMPANY_INTEL_FILE = ROOT_DIR / "company_intel.md"
SEEN_JOBS_CSV = ROOT_DIR / "seen_jobs.csv"

# ── Gate 0: eligibility patterns ────────────────────────────────────────────
#
# Match the CONCEPT, not a list of phrasings. The 2026-09-09 escapes (Panasonic
# "does not sponsor applicants for work visas", ASML "Export ADMINISTRATION
# Regulations") were both phrase-list misses: the old list wanted "no sponsorship"
# / "will not sponsor" and `export\s+control` literally. Enumerating wordings
# loses to the next posting; negation-near-the-verb does not.
#
# Each entry is (pattern, label, rescuable). `rescuable` means a positive
# work-authorization statement in the SAME sentence downgrades the hit to
# CAUTION instead of gating — a JD that says "US citizens, permanent residents
# and visa holders are all welcome" names citizenship without restricting on it.
# ITAR and explicit no-sponsor are never rescuable: an employer that sponsors
# H-1B still cannot put a non-US-person on export-controlled work.
#
# Patterns carry their own (?i) so `full_text` keeps its original case; \bEAR\b
# must stay case-sensitive or it fires on "ear protection" in the PPE section.
VISA_ITAR_PATTERNS = [
    # ── Explicit refusal to sponsor ──
    (r'(?i)(?:will|would|does|do|can|could|are|is)\s+not\s+(?:\w+\s+){0,4}?sponsor',
     "No Visa Sponsorship Policy", False),
    (r'(?i)(?:unable|not\s+able|unwilling)\s+to\s+(?:\w+\s+){0,3}?sponsor',
     "No Visa Sponsorship Policy", False),
    (r'(?i)(?:does|do|will|can|cannot)\s+not?\s+(?:provide|offer|support|extend)\s+(?:\w+\s+){0,3}?sponsorship',
     "No Visa Sponsorship Policy", False),
    (r'(?i)\bno\s+(?:visa\s+|immigration\s+|work\s+visa\s+|employment\s+|h-?1b\s+)?sponsorship\b',
     "No Visa Sponsorship Policy", False),
    (r'(?i)sponsorship\s+(?:is|will)\s+not\s+(?:be\s+)?(?:available|offered|provided|considered)',
     "No Visa Sponsorship Policy", False),
    (r'(?i)without\s+(?:the\s+need\s+for\s+)?(?:visa\s+|company\s+|employer\s+|current\s+or\s+future\s+)?sponsorship',
     "Must Work Without Sponsorship", False),
    (r'(?i)authoriz\w+\s+to\s+work[^.]{0,80}?without\s+(?:visa\s+)?sponsorship',
     "Must Work Without Sponsorship", False),
    # ── Export control / controlled technology ──
    (r'(?i)\b(?:itar|ear99|defense\s+trade\s+controls|deemed\s+export)\b',
     "ITAR / Export Control Restriction", False),
    (r'(?i)export\s+(?:control|controlled|administration\s+regulations|licensing)',
     "ITAR / Export Control Restriction", False),
    (r'(?i)controlled\s+technology',
     "Export-Controlled Technology Access", False),
    (r'\bEAR\b',
     "ITAR / Export Control Restriction", False),
    (r'(?i)\bu\.?\s?s\.?\s+persons?\b',
     "U.S. Person Status Required", False),
    # ── Citizenship / residency / clearance ──
    # `citizens?` — the old pattern was `citizen(?:ship)?\b`, which never matched
    # the plural "U.S. citizens only" because \b does not fire between n and s.
    (r'(?i)\bu\.?s\.?\s*citizens?(?:hip)?\b',
     "U.S. Citizenship Required", True),
    (r'(?i)citizenship\s+(?:is\s+)?required|must\s+be\s+a\s+(?:u\.?s\.?\s+)?citizen',
     "U.S. Citizenship Required", False),
    (r'(?i)\b(?:permanent\s+resident|green\s+card\s+holder)s?\s+(?:only|required)\b',
     "Permanent Resident / Green Card Only", False),
    (r'(?i)\b(?:security\s+clearance|active\s+secret|top\s+secret|ts/sci|dod\s+clearance|government\s+clearance)\b',
     "Security Clearance Required", False),
    (r'(?i)able\s+to\s+obtain\s+(?:and\s+maintain\s+)?(?:a\s+)?(?:u\.?s\.?\s+)?(?:government\s+|security\s+)?clearance',
     "Security Clearance Required", False),
]

# Positive work-authorization language. Used two ways: to rescue a `rescuable`
# gate hit that only MENTIONS citizenship, and for the §4.A +5 sponsorship bonus.
POSITIVE_SPONSOR_RE = re.compile(
    r'(?i)\b(?:visa\s+sponsorship\s+available|will\s+sponsor|we\s+sponsor|sponsorship\s+(?:is\s+)?(?:available|provided|offered)'
    r'|visa\s+holders?|international\s+(?:applicants?|candidates?)\s+(?:are\s+)?welcome'
    r'|all\s+work\s+authoriz\w+|h-?1b|stem\s+opt|\bopt\b|\bcpt\b|visa\s+support|relocation\s+provided)\b'
)


def _sentence_around(text: str, start: int, end: int) -> str:
    """The sentence containing a match, for context-sensitive gate decisions."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
    right_dot = text.find(".", end)
    right_nl = text.find("\n", end)
    candidates = [p for p in (right_dot, right_nl) if p != -1]
    right = min(candidates) if candidates else len(text)
    return text[left + 1:right].strip()


def word_match(term: str, text: str) -> bool:
    """
    Case-insensitive, boundary-aware containment test.

    Replaces the old `term in text`, which matched substrings and made the whole
    Skills axis noise: `doe` hit "DOEs not sponsor", `car` hit the recruiter
    "Mark CARr", `nde` hit "inteNDEd", `fai`/`fair` hit "FAIrness and honesty".
    On 2026-09-09 every row scoring >=70 listed `car, nde` as matched skills.

    Boundaries are alphanumeric-only (not \\b) because our vocabulary is full of
    symbol-edged terms — `gd&t`, `cp/cpk`, `gage r&r`, `8d`. \\b after `&` or `/`
    asserts against the wrong character class and never fires.
    """
    return re.search(r'(?<![a-z0-9])' + re.escape(term.lower()) + r'(?![a-z0-9])',
                     text.lower()) is not None

# Explicit Company-level intel skips (company_intel.md)
KNOWN_NON_SPONSORS = CONFIG["known_non_sponsors"]

TARGET_ANCHORS = CONFIG["target_anchors"]

# Unified candidate master toolkit (grounded in data/candidate_resume_database.json)
CANDIDATE_MASTER_TOOLKIT = CONFIG["master_toolkit"]

# Staffing Agencies (Section 8)
STAFFING_AGENCIES = CONFIG["staffing_agencies"]

def normalize_company(name: str) -> str:
    """Normalize company name by stripping legal entities, sub-brands, and noise."""
    if not name:
        return ""
    c = name.lower()
    c = re.sub(r'\b(inc|incorporated|corp|corporation|llc|ltd|limited|co|company|technologies|solutions|group|americas|europe|healthcare|dimatix|north america|gmbh|sa|bv|nv|srl)\b', '', c)
    return re.sub(r'[^a-z0-9]', '', c)

def normalize_title(title: str) -> str:
    """Normalize job title by stripping shifts, levels, grades, and parentheticals."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r'\b(1st|2nd|3rd|first|second|third|night)\s*shift\b', '', t)
    t = re.sub(r'\b(i|ii|iii|iv|v|1|2|3|4|5|e1|e2|e3|e4|associate|junior|senior|sr|lead|entry\s*level|new\s*college\s*grad|ncg)\b', '', t)
    t = re.sub(r'\(.*?\)|\[.*?\]', '', t)
    return re.sub(r'[^a-z0-9]', '', t)

def load_seen_ledger() -> tuple[set[str], set[str], set[str], set[str]]:
    """Load seen URLs, LinkedIn IDs, and raw + normalized company|title fingerprints from seen_jobs.csv and Supabase."""
    seen_urls = set()
    seen_job_ids = set()
    seen_fingerprints = set()
    seen_norm_fingerprints = set()
    
    # 1. Parse seen_jobs.csv
    if SEEN_JOBS_CSV.exists():
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
                    co_raw = ""
                    title_raw = ""
                    if row[0].startswith("2026-"):
                        if len(row) >= 4:
                            co_raw = row[2]
                            title_raw = row[3]
                    else:
                        if len(row) >= 2:
                            co_raw = row[0]
                            title_raw = row[1]
                    if co_raw and title_raw:
                        seen_norm_fingerprints.add(f"{normalize_company(co_raw)}|{normalize_title(title_raw)}")
                        seen_fingerprints.add(f"{re.sub(r'[^a-z0-9]', '', co_raw.lower())}|{re.sub(r'[^a-z0-9]', '', title_raw.lower())}")
                    if len(row) >= 7 and row[6]:
                        raw_fp = re.sub(r'[^a-z0-9|]', '', row[6].lower())
                        seen_fingerprints.add(raw_fp)
        except Exception as e:
            print(f"Warning loading seen_jobs.csv in ranker: {e}", file=sys.stderr)

    # 2. Sync from Supabase applications database of record
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    supa_url = os.environ.get("SUPABASE_URL", "https://chsrkysjongzgdbwqhlu.supabase.co")
    supa_key = os.environ.get("SUPABASE_KEY")
    if supa_key:
        try:
            req = urllib.request.Request(
                f"{supa_url}/rest/v1/applications?select=company,role,job_url",
                headers={"apikey": supa_key, "Authorization": f"Bearer {supa_key}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                supa_apps = json.loads(resp.read().decode("utf-8"))
                for app in supa_apps:
                    u = (app.get("job_url") or "").strip().split("?")[0].rstrip("/")
                    if u:
                        seen_urls.add(u)
                        m = re.search(r'(\d{8,12})', u)
                        if m:
                            seen_job_ids.add(m.group(1))
                    c = app.get("company") or ""
                    r = app.get("role") or ""
                    if c and r:
                        seen_norm_fingerprints.add(f"{normalize_company(c)}|{normalize_title(r)}")
                        seen_fingerprints.add(f"{re.sub(r'[^a-z0-9]', '', c.lower())}|{re.sub(r'[^a-z0-9]', '', r.lower())}")
        except Exception as e:
            print(f"Warning syncing seen ledger from Supabase: {e}", file=sys.stderr)
        
    return seen_urls, seen_job_ids, seen_fingerprints, seen_norm_fingerprints

SEEN_URLS, SEEN_JOB_IDS, SEEN_FINGERPRINTS, SEEN_NORM_FINGERPRINTS = load_seen_ledger()

def check_seen_ledger(job: dict) -> tuple[bool, str]:
    """Check if job has already been surfaced/applied in seen_jobs.csv or Supabase."""
    url = (job.get("link") or job.get("apply_url") or "").strip()
    clean_u = url.split("?")[0].rstrip("/")
    co_raw = job.get("company") or ""
    title_raw = job.get("title") or ""
    co = re.sub(r'[^a-z0-9]', '', co_raw.lower())
    title = re.sub(r'[^a-z0-9]', '', title_raw.lower())
    fp = f"{co}|{title}"
    norm_fp = f"{normalize_company(co_raw)}|{normalize_title(title_raw)}"
    
    m = re.search(r'(\d{8,12})', clean_u)
    job_id = m.group(1) if m else None
    
    if clean_u and clean_u in SEEN_URLS:
        return True, f"Exact URL match in seen ledger ({clean_u})"
    if job_id and job_id in SEEN_JOB_IDS:
        return True, f"LinkedIn Job ID match in seen ledger ({job_id})"
    if fp and fp in SEEN_FINGERPRINTS:
        return True, f"Company & Title match in seen ledger ({co_raw} — {title_raw})"
    if norm_fp and norm_fp in SEEN_NORM_FINGERPRINTS:
        return True, f"Normalized Company & Title match in seen ledger ({co_raw} — {title_raw})"
        
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

def check_eligibility_gate(job: dict) -> tuple[bool, str, str, list[str]]:
    """
    Step 0: Eligibility Gate (P1_06 §3 / §7).
    Returns (passed: bool, verdict: str, quoted_reason: str, caution_notes: list[str]).

    Runs over the ORIGINAL-CASE text so the case-sensitive \\bEAR\\b pattern works.
    Every hit carries a verbatim +/-120 char snippet: a gate the user cannot audit
    is a gate the user cannot trust, in either direction. A false negative costs a
    wasted application; a false positive silently drops a good role.
    """
    company_lower = job.get("company", "").strip().lower()
    title_lower = job.get("title", "").strip().lower()
    desc = job.get("description", "")
    full_text = f"{job.get('title', '')} {job.get('company', '')} {desc}"
    caution_notes: list[str] = []

    # 1. Company-level known restrictions (company_intel.md)
    for co, reason in KNOWN_NON_SPONSORS.items():
        if co in company_lower:
            return False, "VISA RISK (SKIP)", f"Company Gate: {reason}", caution_notes

    # 2. Text-level ITAR / Citizenship / Clearance / No-Sponsorship concept check
    for pattern, label, rescuable in VISA_ITAR_PATTERNS:
        match = re.search(pattern, full_text)
        if not match:
            continue
        sentence = _sentence_around(full_text, match.start(), match.end())
        # §7 context note: a posting that NAMES citizenship while welcoming visa
        # holders is not restricting on it. Flag it (§6 CAUTION), do not gate.
        if rescuable and POSITIVE_SPONSOR_RE.search(sentence):
            caution_notes.append(f"{label} mentioned but not restrictive: \"{sentence[:160]}\"")
            continue
        start = max(0, match.start() - 120)
        end = min(len(full_text), match.end() + 120)
        snippet = " ".join(full_text[start:end].split())
        return False, "VISA RISK (SKIP)", f"{label} (Matched snippet: \"...{snippet}...\")", caution_notes

    # 3. Technician / Operator / Assembler / Apprenticeship Gate
    if any(k in title_lower for k in ["machinist", "operator", "assembler", "welder", "fabricator", "apprentice", "apprentissage", "internship", "intern", "staż", "werkstudent", "praktik", "alternance", "abschlussarbeit"]) or title_lower.startswith("stage "):
        return False, "DROP (NON-ENG)", "Shop-floor / apprentice / student internship role", caution_notes

    if "technician" in title_lower and not any(
            k in title_lower for k in ["quality", "process", "manufacturing",
                                       "inspection", "cmm", "metrology", "qa", "qc"]):
        return False, "DROP (NON-ENG)", "Technician role not quality/process-adjacent", caution_notes
        
    # 4. Seniority Gate (Section 3.4)
    if any(k in title_lower for k in ["principal", "director", "staff engineer", "head of", "senior manager", "executive"]):
        return False, "DROP (SENIORITY)", "Seniority too high (Manager/Director/Principal/Staff)", caution_notes

    # 5. Non-English Language Gate
    foreign_lang_patterns = [
        (r'\b(beschrijving|functieomschrijving|taken|profiel|aanbod|wij zoeken|kandidaten|solliciteer|nederlands)\b', "Dutch language posting"),
        (r'\b(stellenbeschreibung|ihre aufgaben|ihr profil|wir bieten|anforderungen|bewerben|deutschkenntnisse|ingenieur)\b', "German language posting"),
        (r'\b(description du poste|vos missions|votre profil|nous offrons|exigences|postuler|français|amélioration|pièce|tôlerie|travail|qualité|ingénieur)\b', "French language posting"),
        (r'\b(descrizione del lavoro|le tue mansioni|il tuo profilo|cosa offriamo|requisiti|candidati|italiano|ingegnere)\b', "Italian language posting"),
        (r'\b(descripción del puesto|tus responsabilidades|tu perfil|ofrecemos|requisitos|español|ingeniero)\b', "Spanish language posting"),
        (r'\b(inżynier|jakości|produkcja|stanowisko|wymagania|obowiązki|praca)\b', "Polish language posting")
    ]
    for pat, lang_label in foreign_lang_patterns:
        if re.search(pat, full_text, re.IGNORECASE):
            return False, "DROP (NON-ENG-LANG)", f"{lang_label}: Sid is an English speaker; non-English postings dropped.", caution_notes

    # 6. Local European Residency / Work Permit Gate
    residency_patterns = [
        (r'\b(residents?\s+only|only\s+residents?)\b', "Local residency only required"),
        (r'\b(woonachtig\s+in|inwoners?\s+van)\b', "Belgian/Dutch local residency required"),
        (r'\b(eu\s+citizenship\s+required|must\s+hold\s+eu\s+passport)\b', "EU citizenship required"),
        (r'\b(no\s+visa\s+sponsorship\s+for\s+(this|international|overseas))\b', "Explicit no international visa sponsorship")
    ]
    for pat, res_label in residency_patterns:
        if re.search(pat, full_text, re.IGNORECASE):
            return False, "DROP (LOCAL-RESIDENCY)", f"{res_label}: International applicant ineligible.", caution_notes

    # 7. Staffing Agencies in Europe (Pass 4)
    is_intl = job.get("source", "").endswith("intl") or any(k in job.get("location", "").lower() for k in ["europe", "belgium", "netherlands", "germany", "france", "italy", "spain", "sweden", "switzerland", "austria"])
    if is_intl and any(ag in company_lower for ag in ["madison recruitment", "trio personalmanagement", "jobster", "iddtek", "house of aby", "felixa", "trinamics"]):
        return False, "DROP (INTL-STAFFING)", "European staffing agency does not sponsor international relocation", caution_notes
        
    return True, "ELIGIBLE", "", caution_notes

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

    # Positive visa mention bonus (+5, P1_06 §4.A). Boundary-aware: the old
    # substring test gave every posting containing "optimize", "option" or
    # "adopted" a free +5 because "opt" was in the list.
    if POSITIVE_SPONSOR_RE.search(combined):
        spon_pts = min(30, spon_pts + 5)
        
    # B. Skills / Role Fit (30 pts) — Evaluated against candidate master toolkit
    matched_tools = [term for term in CANDIDATE_MASTER_TOOLKIT if word_match(term, combined)]
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


# ── v2 score model (tracks retired 2026-09-09) ──────────────────────────────
#
# v1 ranked on JD keyword DENSITY: it counted how many of Sid's toolkit words
# appeared in the posting. That is backwards — it rewarded a battery JD for
# saying "battery", a word Sid cannot claim. v2 ranks on truthful COVERAGE:
# of the things this posting actually asks for, how much can Sid put on a
# resume without lying.
#
# Weights: coverage 40 + domain 15 + seniority 15 = 70/100 is fit, per the
# 2026-09-09 spec. Sponsorship keeps 25 and stays a gate, not a tiebreaker.

V2_WEIGHTS = {"coverage": 40, "sponsorship": 25, "domain": 15, "seniority": 15, "logistics": 5}

_DOMAIN_TABLE = None


def load_domain_priority() -> dict:
    global _DOMAIN_TABLE
    if _DOMAIN_TABLE is None:
        path = ROOT_DIR / "data" / "domain_priority.json"
        _DOMAIN_TABLE = json.loads(path.read_text(encoding="utf-8"))
    return _DOMAIN_TABLE


def score_domain_v2(text: str) -> tuple[int, str]:
    """First matching domain in priority order wins; unclassified is the floor."""
    table = load_domain_priority()
    for dom in table["domains"]:
        if any(word_match(cue, text) for cue in dom["cues"]):
            return dom["points"], dom["label"]
    last = table["domains"][-1]
    return last["points"], last["label"]


def score_sponsorship_v2(job: dict, text: str) -> tuple[int, str]:
    """
    'Silence is not permission' — a JD that says nothing about sponsorship is
    unverified, not clear. That is what the H-1B lookup is for. P1_06 §4.A's
    benefit-of-the-doubt rule survives: not-in-lookup is a neutral 8, never 0.
    (An explicit negative never reaches here — it gates in Gate 0.)
    """
    if POSITIVE_SPONSOR_RE.search(text):
        return 25, "JD states sponsorship available"
    approvals = get_uscis_approvals(job.get("company", ""))
    if approvals >= 50:
        return 22, f"proven sponsor ({approvals} H-1B filings)"
    if approvals >= 10:
        return 17, f"moderate sponsor ({approvals} filings)"
    if approvals >= 1:
        return 12, f"occasional sponsor ({approvals} filings)"
    return 8, "silent, no filing record — neutral, not penalised"


# P1_06 §5's qualitative gate: a role can clear the numeric floor and still be a
# no-fit because it is the wrong discipline. v1 enforced this inside the Skills
# axis via is_core_qe / is_mfg_process; v2 makes it explicit so it cannot be lost
# again. Without it the 2026-09-09 batch floated two "Flight Inspector" staffing
# roles into the top ten on keyword coverage alone.
CORE_ROLE_CUES = [
    "quality engineer", "supplier quality", "manufacturing quality", "process quality",
    "quality assurance engineer", "qa engineer", "qms", "quality systems",
    "process engineer", "manufacturing engineer", "production engineer",
    "composites engineer", "materials engineer", "industrial engineer",
    "continuous improvement engineer", "mrb", "metrology", "quality officer",
    "manufacturing technician", "quality technician", "process technician",
    "npi", "new product introduction", "yield engineer", "reliability engineer",
]
OFF_DISCIPLINE_CUES = [
    "inspector", "flight inspector", "auditor", "software", "sales", "account",
    "recruiter", "designer", "architect", "data scientist", "financial", "marketing",
    "nurse", "driver", "technician support", "field service",
]


def score_role_fit_v2(title: str, text: str) -> tuple[int, str, bool]:
    """
    Returns (points, why, off_discipline). Combines discipline and level: an
    entry-level role in the wrong discipline is not a good row, it is a drop.
    """
    t = f" {title.lower()} "
    is_core = any(cue in t for cue in CORE_ROLE_CUES)
    is_off = any(cue in t for cue in OFF_DISCIPLINE_CUES) and not is_core
    if is_off:
        return 0, f"off-discipline title ({title})", True

    if re.search(r'(?i)\b(?:6|7|8|9|10)\+?\s*years', text):
        return 0, "6+ years required", False
    if any(word_match(k, t) for k in ["entry", "associate", "new grad", "new college grad",
                                      "university", "i", "1", "level i", "level 1", "graduate"]):
        lvl, why = 15, "entry / level I / new grad"
    elif re.search(r'(?i)\b(?:4|5)\+?\s*years', text) or any(word_match(k, t) for k in ["ii", "2", "level ii"]):
        lvl, why = 4, "level II / 4-5 years"
    elif re.search(r'(?i)\b3\+?\s*years', text):
        lvl, why = 9, "3 years"
    else:
        lvl, why = 9, "level unstated"

    if not is_core:
        # Adjacent engineering, not bullseye. Half the level credit, flagged.
        return max(0, lvl // 2), f"{why}; adjacent discipline, not core QE/process", False
    return lvl, why, False


def calculate_fit_score_v2(job: dict, tax=None) -> dict:
    """Deterministic v2 row: score, sub-scores, and the full keyword report."""
    import keyword_engine as ke

    title = job.get("title", "")
    desc = job.get("description", "") or ""
    combined = f"{title} {job.get('company', '')} {desc}"

    kw = ke.analyse(desc, tax or ke.Taxonomy.load())

    # No usable coverage signal -> award the axis nothing and say so. Never
    # default a missing measurement to a passing one.
    if kw["coverage"] is None:
        cov_pts, cov_why = 0, f"no coverage signal ({kw['extraction']})"
    else:
        cov_pts = round(V2_WEIGHTS["coverage"] * kw["coverage"])
        cov_why = (f"{kw['coverage_percent']}% weighted "
                   f"({kw['counts']['PROVEN']}P/{kw['counts']['EVIDENCED']}E/"
                   f"{kw['counts']['ADJACENT']}A/{kw['counts']['GAP']}G of {kw['keyword_total']})")
        if kw["extraction"] == "THIN":
            # 100% off two terms is not the same evidence as 100% off twelve.
            # Scale the axis by how much of a denominator we actually measured,
            # otherwise thin rows outrank well-evidenced ones on a rounding.
            scale = kw["keyword_total"] / ke.MIN_CONFIDENT_KEYWORDS
            cov_pts = round(cov_pts * scale)
            cov_why += f" [THIN: {kw['keyword_total']} terms, axis scaled x{scale:.2f}]"

    spon_pts, spon_why = score_sponsorship_v2(job, combined)
    dom_pts, dom_label = score_domain_v2(combined)
    sen_pts, sen_why, off_discipline = score_role_fit_v2(title, desc)

    log_pts = 5
    if job.get("freshness") == "REPOSTED":
        log_pts = 2
    if any(a in job.get("company", "").lower() for a in STAFFING_AGENCIES):
        log_pts = 1

    sub = {"coverage": cov_pts, "sponsorship": spon_pts, "domain": dom_pts,
           "role_fit": sen_pts, "logistics": log_pts}
    total = sum(sub.values())

    return {
        "score_v2": total,
        "sub_scores_v2": sub,
        "keyword_report": kw,
        # P1_06 §5: off-discipline is a no-fit DROP regardless of the number.
        "off_discipline": off_discipline,
        "verdict_v2": "DROP (off-discipline)" if off_discipline else None,
        "reasons_v2": [
            f"Coverage ({cov_pts}/{V2_WEIGHTS['coverage']}) — {cov_why}",
            f"Sponsorship ({spon_pts}/{V2_WEIGHTS['sponsorship']}) — {spon_why}",
            f"Domain ({dom_pts}/{V2_WEIGHTS['domain']}) — {dom_label}",
            f"Role fit ({sen_pts}/{V2_WEIGHTS['seniority']}) — {sen_why}",
            f"Logistics ({log_pts}/{V2_WEIGHTS['logistics']}) — {job.get('freshness', 'FRESH')}",
        ],
        "gap_keywords": kw["not_claimable"],
        "claimable_keywords": kw["claimable"],
    }


# ── Self-test ───────────────────────────────────────────────────────────────

FIXTURE_DIR = ROOT_DIR / "tests" / "fixtures"


def _load_fixture(name: str) -> dict:
    """Parse a tests/fixtures/*.txt back into the job dict shape the gates expect."""
    raw = (FIXTURE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    head, _, body = raw.partition("\n\n")
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip()
    return {
        "title": meta.get("title", ""),
        "company": meta.get("company", ""),
        "location": meta.get("location", ""),
        "link": meta.get("link", ""),
        "description": body,
        "source": "fixture",
    }


def run_self_test() -> int:
    """Assert-based regression check. No framework: `python3 tools/gate_and_score.py --self-test`."""
    failures = []

    def check(name, actual, expected):
        ok = actual == expected
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        expected {expected!r}\n        got      {actual!r}")
            failures.append(name)

    print("word_match — the 2026-09-09 substring bug")
    check("'nde' does not match 'intended'", word_match("nde", "the intended process"), False)
    check("'car' does not match 'Mark Carr'", word_match("car", "Meet the recruiter: Mark Carr"), False)
    check("'doe' does not match 'does not sponsor'", word_match("doe", "Panasonic does not sponsor"), False)
    check("'fai' does not match 'fairness'", word_match("fai", "fairness and honesty"), False)
    check("'fai' still matches a real FAI mention", word_match("fai", "Perform FAI per AS9102"), True)
    check("'gd&t' survives symbol edges", word_match("gd&t", "Reading GD&T callouts"), True)
    check("'8d' survives a digit-leading term", word_match("8d", "Led an 8D investigation"), True)
    check("'cp/cpk' survives a slash", word_match("cp/cpk", "Track Cp/Cpk weekly"), True)

    print("\nGate 0 — the roles that escaped on 2026-09-09")
    cases = [
        ("panasonic_qet1", False, "No Visa Sponsorship Policy"),
        # ASML's JD names Export Administration Regulations AND controlled
        # technology; either is fatal, the EAR clause just appears first.
        ("asml_nxe", False, "ITAR / Export Control Restriction"),
        ("gulfstream_sqa", False, "No Visa Sponsorship Policy"),   # regression: already worked
        ("micron_ncg", True, None),
        ("sponsor_friendly", True, None),
        ("spc_repeated", True, None),
        ("benefits_only", True, None),
    ]
    for name, should_pass, label in cases:
        if not (FIXTURE_DIR / f"{name}.txt").exists():
            # The real-posting fixtures are verbatim employer text and stay local
            # (gitignored). A clone only carries the synthetic ones.
            print(f"  SKIP  {name} (fixture not present in this checkout)")
            continue
        passed, verdict, reason, _cautions = check_eligibility_gate(_load_fixture(name))
        check(f"{name} gate passes={should_pass}", passed, should_pass)
        if label:
            check(f"{name} gated on '{label}'", reason.split(" (Matched")[0], label)

    print("\nGate 0 — false-positive guards")
    friendly = _load_fixture("sponsor_friendly")
    _p, _v, _r, cautions = check_eligibility_gate(friendly)
    check("welcoming citizenship mention is CAUTION, not a gate", len(cautions) >= 1, True)
    check("'ear protection' does not trip the EAR export rule",
          check_eligibility_gate({"title": "QE", "company": "Acme",
                                  "description": "PPE required: safety glasses and ear protection."})[0], True)
    check("'optimize' does not count as an OPT sponsorship signal",
          POSITIVE_SPONSOR_RE.search("we optimize adopted options") is None, True)
    check("real STEM OPT mention does count",
          POSITIVE_SPONSOR_RE.search("We consider STEM OPT candidates") is not None, True)

    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILURE(S): ' + ', '.join(failures)}")
    return 1 if failures else 0


def main():
    # v2 is computed on every run so the two models can be compared on real
    # batches (shadow). It only ROUTES when --v2 is passed, so flipping the
    # ranker is a flag change in DAILY_RUN, and reverting is the same flag.
    use_v2 = "--v2" in sys.argv

    fetched_json_path = PIPELINE_DIR / "fetched.json"
    if not fetched_json_path.exists():
        print(f"Error: {fetched_json_path} does not exist. Run tools/fetch_jobs.py first.", file=sys.stderr)
        sys.exit(1)

    with open(fetched_json_path, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    import keyword_engine as ke
    taxonomy = ke.Taxonomy.load()

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
        passed_gate0, verdict, gate_reason, caution_notes = check_eligibility_gate(job)
        
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
        v2 = calculate_fit_score_v2(job, taxonomy)

        if sprint_track == "Track 2: Curated Target":
            lane = "Track 2: Curated Target"
            verdict = "Strong Fit (Target Lane)"
        elif sprint_track == "Track 1: Broad-Fit Apply":
            lane = "Track 1: Broad-Fit Apply"
            verdict = "Strong Fit (Direct Apply)"
        else:
            lane = "Drop"
            verdict = "Below Fit Threshold (<50)"

        if use_v2:
            # P1_06 §5: off-discipline is a no-fit DROP whatever the number says.
            if v2["off_discipline"]:
                lane, verdict = "Drop", v2["verdict_v2"]
            elif v2["score_v2"] >= 50:
                lane = "Track 1: Broad-Fit Apply"
                verdict = "Strong Fit (Direct Apply)"
            else:
                lane, verdict = "Drop", "Below Fit Threshold (<50)"

        ranked_jobs.append({
            **job,
            "score": v2["score_v2"] if use_v2 else score,
            "sub_scores": v2["sub_scores_v2"] if use_v2 else sub_scores,
            "verdict": verdict,
            "lane": lane,
            "track": sprint_track,
            "reasons": v2["reasons_v2"] if use_v2 else reasons,
            "recommended_resume": rec_resume,
            "gate0_passed": True,
            "caution_notes": caution_notes,
            # Both models on every row, whichever is routing. This is what makes
            # a shadow batch comparable and a flip reversible.
            "score_v1": score,
            "sub_scores_v1": sub_scores,
            "score_v2": v2["score_v2"],
            "sub_scores_v2": v2["sub_scores_v2"],
            "reasons_v2": v2["reasons_v2"],
            "coverage_percent": v2["keyword_report"]["coverage_percent"],
            "keyword_counts": v2["keyword_report"]["counts"],
            "keyword_total": v2["keyword_report"]["keyword_total"],
            "extraction": v2["keyword_report"]["extraction"],
            "extraction_note": v2["keyword_report"]["extraction_note"],
            "claimable_keywords": v2["claimable_keywords"],
            "gap_keywords": v2["gap_keywords"],
            "adjacent_keywords": v2["keyword_report"]["buckets"]["ADJACENT"],
            "required_gaps": v2["keyword_report"]["required_gaps"],
            "taxonomy_version": v2["keyword_report"]["taxonomy_version"],
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
        
        f.write(f"> 🔤 **Keyword coverage** (taxonomy v{shortlisted[0].get('taxonomy_version', '?') if shortlisted else '?'}): "
                f"`KW` is total ATS terms extracted from the JD's requirements, then how many are "
                f"**P**roven / **E**videnced / **A**djacent (half credit) / **G**ap. `Cov%` weights required terms 2x preferred.\n\n")

        f.write("### 🎯 Shortlist (Approved for Customization)\n\n")
        f.write("| # | Pass | Score | v2 | Cov% | KW (P/E/A/G) | Freshness | Verdict | Title | Company | Location | Recommended Resume | Apply URL | 1-Click Networking |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")

        for idx, job in enumerate(shortlisted, start=1):
            url_display = f"[Apply Link]({job['link']})" if job['link'] else "N/A"
            recruiter_link = f"[Recruiter]({job.get('recruiter_url', '#')})" if job.get('recruiter_url') else "—"
            peer_link = f"[Team Lead]({job.get('peer_url', '#')})" if job.get('peer_url') else "—"
            fresh_badge = job.get('freshness_badge', '🟢 FRESH')
            pass_label = job.get('pass', 'Pass 1')
            kc = job.get('keyword_counts', {})
            kw_cell = (f"{job.get('keyword_total', 0)} ({kc.get('PROVEN',0)}/{kc.get('EVIDENCED',0)}"
                       f"/{kc.get('ADJACENT',0)}/{kc.get('GAP',0)})")
            cov = job.get('coverage_percent')
            ext = job.get('extraction', '')
            cov_cell = f"{cov}%" if cov is not None else "—"
            if ext in ("THIN", "UNSCOPED", "NONE", "EMPTY_JD"):
                cov_cell += f" ⚠️{ext}"
            f.write(f"| {idx} | `{pass_label}` | **{job['score']}** | {job.get('score_v2','—')} | {cov_cell} | {kw_cell} | {fresh_badge} | {job['verdict']} | **{job['title']}** | {job['company']} | {job['location']} | `{job['recommended_resume']}` | {url_display} | {recruiter_link} · {peer_link} |\n")

        # Per-row keyword detail: what the resume can claim, and what it must omit.
        # The gap list is the point of Gate A — it is where Sid decides whether a
        # term is genuinely unclaimable or just missing from the taxonomy.
        f.write("\n\n### 🔤 Keyword Coverage Detail\n\n")
        f.write("> To claim a gap term, reply with the term and your evidence. It is written to "
                "`data/keyword_taxonomy.json` as proven, and every future run scores it that way.\n\n")
        for idx, job in enumerate(shortlisted, start=1):
            f.write(f"\n**{idx}. {job['title']} — {job['company']}** "
                    f"(cov {job.get('coverage_percent')}%, {job.get('keyword_total',0)} terms, `{job.get('extraction')}`)\n")
            if job.get('extraction_note'):
                f.write(f"- ⚠️ {job['extraction_note']}\n")
            if job.get('claimable_keywords'):
                f.write(f"- ✅ **Claimable:** {', '.join(job['claimable_keywords'])}\n")
            if job.get('adjacent_keywords'):
                f.write(f"- 🟡 **Adjacent (half credit, defensible in interview):** {', '.join(job['adjacent_keywords'])}\n")
            if job.get('gap_keywords'):
                f.write(f"- ❌ **Gap (NOT claimable today):** {', '.join(job['gap_keywords'])}\n")
            if job.get('required_gaps'):
                f.write(f"- 🚨 **Required terms not fully proven:** {', '.join(job['required_gaps'])}\n")
            if job.get('caution_notes'):
                for note in job['caution_notes']:
                    f.write(f"- 🟠 **Visa CAUTION:** {note}\n")
        f.write("\n")

        f.write("\n\n### 📂 Shortlist Breakdown by Search Pass\n\n")
        pass_names = {
            "Pass 0": "Pass 0: your hand-found postings",
            "Pass 1": "Pass 1: company career sites (ATS, free)",
            "Pass 2": "Pass 2: LinkedIn, target companies",
            "Pass 3": "Pass 3: LinkedIn, all domains",
            "Pass 4": "Pass 4: LinkedIn, contract / technician / intern / co-op",
            "Pass 5": "Pass 5: LinkedIn, international",
        }
        for p_key in pass_names:
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
            
    # Slim handoff for the ranker skill's audit pass. ranked.json carries every
    # JD description (796 KB on 2026-09-09); an agent that reads it pays for the
    # whole batch to check a dozen rows. This carries the decisions, not the prose.
    summary_path = PIPELINE_DIR / "ranked_summary.json"
    summary = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "routing_model": "v2" if use_v2 else "v1 (v2 shadow)",
        "taxonomy_version": (shortlisted[0].get("taxonomy_version") if shortlisted else None),
        "totals": {
            "evaluated": len(ranked_jobs),
            "shortlisted": len(shortlisted),
            "company_cap_reserve": len(company_cap_overflow),
            "below_threshold": len(below_threshold),
            "gated_out": len(gated_out),
        },
        "gated": [
            {"company": j["company"], "title": j["title"], "verdict": j["verdict"],
             "reason": j["reasons"][0] if j.get("reasons") else ""}
            for j in gated_out
        ],
        "shortlist": [
            {k: j.get(k) for k in (
                "company", "title", "location", "link", "score", "score_v1", "score_v2",
                "sub_scores_v2", "coverage_percent", "keyword_total", "keyword_counts",
                "extraction", "extraction_note", "claimable_keywords", "adjacent_keywords",
                "gap_keywords", "required_gaps", "caution_notes", "verdict", "freshness")}
            for j in shortlisted
        ],
        "needs_triage": [
            {"company": j["company"], "title": j["title"], "extraction": j.get("extraction"),
             "note": j.get("extraction_note"), "has_jd": bool((j.get("description") or "").strip())}
            for j in ranked_jobs
            if j.get("gate0_passed") and j.get("extraction") in ("NONE", "EMPTY_JD", "THIN", "UNSCOPED")
        ],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Ranking complete: {len(ranked_jobs)} postings evaluated ({len(shortlisted)} shortlisted).")
    print(f"Routing model: {'v2 (coverage)' if use_v2 else 'v1 — v2 computed in shadow'}")
    print(f"Handoffs saved to:\n  - {ranked_json_path}\n  - {ranked_md_path}\n  - {summary_path}")

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    main()
