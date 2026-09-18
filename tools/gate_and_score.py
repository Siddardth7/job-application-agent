#!/usr/bin/env python3
"""
gate_and_score.py — Stage 2 of the daily run: Gate 0, one score, one shortlist.

One formula, out of 100, every weight and cue list overridable in
config/search_profile.json under "scoring" (defaults in SCORING_DEFAULTS):

  coverage     40  of what this posting asks for, how much the candidate can claim
                   truthfully (tools/keyword_engine.py against data/keyword_taxonomy.json)
  sponsorship  25  stated in the JD, else the H-1B filing record, else the user's own
                   known-sponsor tiers; silence is neutral, never zero
  domain       15  position of the matched domain in the profile's ordered `domains` list
  role_fit     15  discipline (core / adjacent / off) and level (years vs candidate.max_years)
  logistics     5  fresh vs reposted, direct employer vs staffing agency

Gate 0 runs first and drops with a quoted snippet: company on the non-sponsor list,
no-sponsorship / export-control / citizenship / clearance language (skipped entirely
when candidate.needs_sponsorship is false), title-level drops, non-English text,
local-residency-only, and the seen ledger.

Every row lands in exactly one bucket, and none is lost silently:
  Apply       top `shortlist_size` confident rows at or above `apply_threshold`
  Reserve     confident and above threshold, held by `max_per_company` or the size
  Unverified  above threshold but the keyword check was thin — shown, not ranked
  Needs JD    no description; cannot be scored; listed for the user to fetch
  Drop        gated, off-discipline, or below threshold

After ranking, every row is appended to seen_jobs.csv with its bucket as status so
tomorrow's fetch does not surface it again. Yesterday's Apply/Reserve rows that were
not applied are carried into today's batch once (daily_run/ranked_<date>.json).

Usage:
  python3 tools/gate_and_score.py                  # rank .pipeline/fetched.json
  python3 tools/gate_and_score.py --no-ledger      # do not append to seen_jobs.csv
  python3 tools/gate_and_score.py --no-carry       # ignore yesterday's leftovers
  python3 tools/gate_and_score.py --self-test
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
HISTORY_DIR = ROOT_DIR / "daily_run"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import load_config  # noqa: E402
from lib import ledger  # noqa: E402
import keyword_engine as ke  # noqa: E402

USCIS_LOOKUP_FILE = ROOT_DIR / "data" / "uscis_h1b_lookup.json"

# ── Defaults: everything a user may want to retune, in one place ────────────

SCORING_DEFAULTS = {
    "weights": {"coverage": 40, "sponsorship": 25, "domain": 15, "role_fit": 15, "logistics": 5},
    "apply_threshold": 50,
    "shortlist_size": 15,
    "max_per_company": 2,
    "domain_floor": 3,
    "sponsorship": {"stated": 25, "filing_tiers": [[50, 22], [10, 17], [1, 12]], "silent": 8, "international_floor": 15},
    "role_fit": {"entry": 15, "unstated": 10, "within_max_years": 12, "over_max_years": 5,
                 "far_over_margin_years": 3, "adjacent_discipline_factor": 0.5},
    "logistics": {"fresh": 5, "reposted": 2, "staffing": 1},
    # Discipline. core_role_cues defaults to the profile's role_titles + adjacent_titles.
    "core_role_cues": [],
    "off_discipline_cues": ["inspector", "auditor", "software", "sales", "account manager", "recruiter",
                            "designer", "architect", "data scientist", "financial", "marketing", "nurse",
                            "driver", "field service", "customer service"],
    # Titles that are never the candidate's level or discipline, whatever the JD says.
    "title_drop_cues": ["machinist", "operator", "assembler", "welder", "fabricator", "apprentice",
                        "principal", "director", "head of", "vice president", "vp ", "chief", "executive",
                        "senior manager", "staff engineer"],
    "drop_non_english": True,
    "drop_intl_staffing": True,
    "carry_over_days": 1,
}
CANDIDATE_DEFAULTS = {"needs_sponsorship": True, "max_years": 2, "languages": ["english"]}


def build_cfg(profile: dict | None = None) -> dict:
    """Merge SCORING_DEFAULTS with the profile's `scoring` block (one level deep)."""
    profile = profile if profile is not None else load_config()
    sc = json.loads(json.dumps(SCORING_DEFAULTS))
    for k, v in (profile.get("scoring") or {}).items():
        if isinstance(v, dict) and isinstance(sc.get(k), dict):
            sc[k].update(v)
        else:
            sc[k] = v
    search = profile.get("search") or {}
    if not sc["core_role_cues"]:
        sc["core_role_cues"] = [t.lower() for t in (search.get("role_titles") or []) + (search.get("adjacent_titles") or [])]
    cand = {**CANDIDATE_DEFAULTS, **(profile.get("candidate") or {})}
    return {"scoring": sc, "candidate": cand,
            "domains": profile.get("domains") or [], "default_domain": profile.get("default_domain", "Uncategorized"),
            "known_non_sponsors": profile.get("known_non_sponsors") or {},
            "known_itar_flags": profile.get("known_itar_flags") or {},
            "known_sponsors": profile.get("known_sponsors") or {},
            "staffing_agencies": [a.lower() for a in profile.get("staffing_agencies") or []],
            "anchors": [a.lower() for a in profile.get("target_anchors") or []]}


# ── Text helpers ────────────────────────────────────────────────────────────

def word_match(term: str, text: str) -> bool:
    """Boundary-aware containment; alphanumeric lookarounds so gd&t / cp/cpk / 8d work."""
    return re.search(r'(?<![a-z0-9])' + re.escape(term.lower()) + r'(?![a-z0-9])', text.lower()) is not None


def _sentence_around(text: str, start: int, end: int, following: int = 0) -> str:
    """The sentence containing a match, plus `following` sentences after it."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
    right = end
    for _ in range(following + 1):
        rights = [p for p in (text.find(".", right), text.find("\n", right)) if p != -1]
        right = (min(rights) + 1) if rights else len(text)
        if right >= len(text):
            break
    return text[left + 1:right].strip().rstrip(".")


# ── Gate 0 patterns (generic; the personal lists live in config) ────────────
#
# Each entry: (pattern, label, mode). Modes:
#   hard        gate on any hit
#   rescuable   a positive work-authorization phrase in the same sentence downgrades to CAUTION
#   requirement gate only if the same sentence reads as a requirement; else CAUTION
#               (export-control boilerplate "comply with export control laws" is not a US-person rule)
VISA_ITAR_PATTERNS = [
    (r'(?i)(?:will|would|does|do|can|could|are|is)\s+not\s+(?:\w+\s+){0,4}?sponsor', "No visa sponsorship", "hard"),
    (r'(?i)(?:unable|not\s+able|unwilling)\s+to\s+(?:\w+\s+){0,3}?sponsor', "No visa sponsorship", "hard"),
    (r'(?i)(?:does|do|will|can|cannot)\s+not?\s+(?:provide|offer|support|extend)\s+(?:\w+\s+){0,3}?sponsorship', "No visa sponsorship", "hard"),
    (r'(?i)\bno\s+(?:visa\s+|immigration\s+|work\s+visa\s+|employment\s+|h-?1b\s+)?sponsorship\b', "No visa sponsorship", "hard"),
    (r'(?i)sponsorship\s+(?:is|will)\s+not\s+(?:be\s+)?(?:available|offered|provided|considered)', "No visa sponsorship", "hard"),
    (r'(?i)not\s+eligible\s+for\s+(?:[\w-]+\s+){0,4}?sponsorship', "No visa sponsorship", "hard"),
    (r'(?i)without\s+(?:the\s+need\s+for\s+)?(?:visa\s+|company\s+|employer\s+|current\s+or\s+future\s+)?sponsorship', "Must work without sponsorship", "hard"),
    (r'(?i)authoriz\w+\s+to\s+work[^.]{0,80}?without\s+(?:visa\s+)?sponsorship', "Must work without sponsorship", "hard"),
    (r'(?i)\b(?:itar|ear99|defense\s+trade\s+controls|deemed\s+export)\b', "ITAR / export control", "requirement"),
    (r'(?i)export\s+(?:control|controlled|administration\s+regulations|licensing)', "ITAR / export control", "requirement"),
    (r'(?i)controlled\s+technology', "Export-controlled technology", "requirement"),
    (r'\bEAR\b', "ITAR / export control", "requirement"),
    (r'(?i)\bu\.?\s?s\.?\s+persons?\b', "U.S. person status required", "hard"),
    (r'(?i)\bu\.?s\.?\s*citizens?(?:hip)?\b', "U.S. citizenship required", "rescuable"),
    (r'(?i)citizenship\s+(?:is\s+)?required|must\s+be\s+a\s+(?:u\.?s\.?\s+)?citizen', "U.S. citizenship required", "hard"),
    (r'(?i)\b(?:permanent\s+resident|green\s+card\s+holder)s?\s+(?:only|required)\b', "Permanent resident only", "hard"),
    (r'(?i)\b(?:security\s+clearance|active\s+secret|top\s+secret|ts/sci|dod\s+clearance|government\s+clearance)\b', "Security clearance required", "hard"),
    (r'(?i)able\s+to\s+obtain\s+(?:and\s+maintain\s+)?(?:a\s+)?(?:u\.?s\.?\s+)?(?:government\s+|security\s+)?clearance', "Security clearance required", "hard"),
]
POSITIVE_SPONSOR_RE = re.compile(
    r'(?i)\b(?:visa\s+sponsorship\s+available|will\s+sponsor|we\s+sponsor|sponsorship\s+(?:is\s+)?(?:available|provided|offered)'
    r'|visa\s+holders?|international\s+(?:applicants?|candidates?)\s+(?:are\s+)?welcome'
    r'|all\s+work\s+authoriz\w+|h-?1b|stem\s+opt|\bopt\b|\bcpt\b|visa\s+support|relocation\s+provided)\b')
REQUIREMENT_SENTENCE_RE = re.compile(
    r'(?i)\b(?:must|required?|requires|eligib\w+|only|need\s+to\s+be|citizen|u\.?s\.?\s+person|permanent\s+resident|green\s+card|clearance)\b')
# "may require a license", "offer contingent on a license", "if we determine": the
# employer is saying it hires non-US persons when it can. That is a caution to read
# at Gate A, not a drop.
CONDITIONAL_RE = re.compile(r'(?i)\b(?:may|might|could)\s+(?:be\s+)?(?:require|necessary|need|have\s+to)|contingent|if\s+\w+\s+determines|eligible\s+for\s+(?:government\s+)?authori')
RESIDENCY_PATTERNS = [
    (r'(?i)\b(?:residents?\s+only|only\s+residents?)\b', "Local residency only"),
    (r'(?i)\b(?:woonachtig\s+in|inwoners?\s+van)\b', "Local residency only"),
    (r'(?i)\b(?:eu\s+citizenship\s+required|must\s+hold\s+(?:an?\s+)?eu\s+passport)\b', "EU citizenship required"),
]
# Language cue lists. A foreign job-title word gates on its own (a posting titled
# "Ingénieur Qualité" is not in English whatever the body says); otherwise two
# distinct body cues from one language are needed, never one (audit R4: "taken"
# in the old Dutch list gated an English JD). No cue is a common English word.
LANGUAGE_TITLE_CUES = {
    "dutch": ["stagiair", "stagiaire", "werkstudent", "kwaliteitsingenieur", "medewerker"],
    "german": ["praktikum", "praktikant", "werkstudent", "abschlussarbeit", "ingenieur", "ingenieurin", "qualitätsingenieur", "fachkraft"],
    "french": ["ingénieur", "ingénieure", "stage", "stagiaire", "alternance", "alternant", "qualité", "amélioration", "pièce", "chargé", "technicien"],
    "italian": ["ingegnere", "tirocinio", "tirocinante", "qualità", "addetto", "responsabile"],
    "spanish": ["ingeniero", "ingeniera", "prácticas", "calidad", "técnico", "responsable de"],
    "portuguese": ["estágio", "estagiário", "engenheiro", "engenheira", "qualidade", "técnico de"],
    "polish": ["inżynier", "specjalista", "jakości", "staż", "stażysta"],
}
LANGUAGE_CUES = {
    "dutch": ["functieomschrijving", "profiel", "aanbod", "wij zoeken", "kandidaten", "solliciteer", "nederlands", "werkzaamheden", "vereisten"],
    "german": ["stellenbeschreibung", "ihre aufgaben", "ihr profil", "wir bieten", "anforderungen", "bewerben", "deutschkenntnisse", "kenntnisse", "erfahrung"],
    "french": ["description du poste", "vos missions", "votre profil", "nous offrons", "exigences", "postuler", "français", "compétences", "expérience"],
    "italian": ["descrizione del lavoro", "mansioni", "il tuo profilo", "cosa offriamo", "requisiti", "candidati", "italiano", "competenze", "esperienza"],
    "spanish": ["descripción del puesto", "responsabilidades", "tu perfil", "ofrecemos", "requisitos", "español", "experiencia", "habilidades", "conocimientos"],
    "polish": ["inżynier", "jakości", "produkcja", "stanowisko", "wymagania", "obowiązki", "praca", "doświadczenie", "umiejętności"],
    "portuguese": ["descrição", "responsabilidades", "requisitos", "oferecemos", "experiência", "conhecimentos", "candidatura", "vaga", "atividades"],
}
INTL_LOCATION_RE = re.compile(r'(?i)\b(europe|belgium|netherlands|germany|france|italy|spain|sweden|switzerland|austria|ireland|denmark|australia|canada|singapore|united kingdom|uk)\b')


def detect_foreign_language(title: str, text: str, accepted: list[str]) -> str:
    t, low = title.lower(), text.lower()
    for lang, cues in LANGUAGE_TITLE_CUES.items():
        if lang not in accepted and any(word_match(c, t) for c in cues):
            return lang
    for lang, cues in LANGUAGE_CUES.items():
        if lang not in accepted and sum(1 for c in cues if word_match(c, low)) >= 2:
            return lang
    return ""


def check_eligibility_gate(job: dict, cfg: dict) -> tuple[bool, str, str, list[str]]:
    """Returns (passed, verdict, quoted_reason, caution_notes). Original-case text, so \\bEAR\\b works."""
    sc, cand = cfg["scoring"], cfg["candidate"]
    company_lower = (job.get("company") or "").lower()
    title_lower = (job.get("title") or "").lower()
    full_text = f"{job.get('title', '')} {job.get('company', '')} {job.get('description', '') or ''}"
    cautions: list[str] = []

    def caution(note: str) -> None:
        if note not in cautions:   # overlapping patterns can hit the same sentence twice
            cautions.append(note)

    if cand["needs_sponsorship"]:
        for co, reason in cfg["known_non_sponsors"].items():
            if co and word_match(co, company_lower):
                return False, "VISA RISK (SKIP)", f"Company gate: {reason}", cautions
        # Company-level flag, not a gate: the JD is silent but the employer's product line is ITAR-heavy.
        for co, reason in cfg["known_itar_flags"].items():
            if co and word_match(co, company_lower):
                caution(f"Company flag: {reason}")
        for pattern, label, mode in VISA_ITAR_PATTERNS:
            m = re.search(pattern, full_text)
            if not m:
                continue
            sentence = _sentence_around(full_text, m.start(), m.end())
            if mode == "rescuable" and POSITIVE_SPONSOR_RE.search(sentence):
                caution(f"{label} mentioned but not restrictive: \"{sentence[:160]}\"")
                continue
            if mode == "rescuable":
                # "except US citizens ... as defined by 8 U.S.C. ... may have to go through an export licensing
                # review": conditional, not a bar. Fixed char window because "8 U.S.C." breaks sentence splitting.
                window = " ".join(full_text[m.start():m.end() + 200].split())
                if CONDITIONAL_RE.search(window):
                    caution(f"{label} is conditional (license / case-by-case), read before applying: \"{window[:200]}\"")
                    continue
            if mode == "requirement":
                window = _sentence_around(full_text, m.start(), m.end(), following=1)
                if not REQUIREMENT_SENTENCE_RE.search(window):
                    caution(f"{label} mentioned as compliance boilerplate, not a requirement: \"{window[:200]}\"")
                    continue
                if CONDITIONAL_RE.search(window):
                    caution(f"{label} is conditional (license / case-by-case), read before applying: \"{window[:200]}\"")
                    continue
            start, end = max(0, m.start() - 120), min(len(full_text), m.end() + 120)
            snippet = " ".join(full_text[start:end].split())
            return False, "VISA RISK (SKIP)", f"{label} (Matched snippet: \"...{snippet}...\")", cautions

    for cue in sc["title_drop_cues"]:
        if cue and cue in f" {title_lower} ":
            return False, "DROP (TITLE)", f"Title-level drop: '{cue.strip()}' in \"{job.get('title')}\"", cautions

    if sc["drop_non_english"]:
        lang = detect_foreign_language(job.get("title") or "", full_text, [l.lower() for l in cand["languages"]])
        if lang:
            return False, "DROP (LANGUAGE)", f"{lang.title()}-language posting; candidate languages: {', '.join(cand['languages'])}", cautions

    for pat, label in RESIDENCY_PATTERNS:
        m = re.search(pat, full_text)
        if m:
            return False, "DROP (LOCAL-RESIDENCY)", f"{label}: \"{_sentence_around(full_text, m.start(), m.end())[:160]}\"", cautions

    is_intl = (job.get("source") or "").endswith("intl") or bool(INTL_LOCATION_RE.search(job.get("location") or ""))
    if sc["drop_intl_staffing"] and is_intl and any(word_match(a, company_lower) for a in cfg["staffing_agencies"]):
        return False, "DROP (INTL-STAFFING)", "International staffing agency; agencies do not sponsor relocation", cautions

    return True, "ELIGIBLE", "", cautions


# ── Sponsorship ─────────────────────────────────────────────────────────────

_USCIS = None


def uscis_data() -> dict:
    global _USCIS
    if _USCIS is None:
        try:
            _USCIS = json.loads(USCIS_LOOKUP_FILE.read_text(encoding="utf-8")) if USCIS_LOOKUP_FILE.exists() else {}
        except Exception as e:
            print(f"Warning loading USCIS lookup: {e}", file=sys.stderr)
            _USCIS = {}
    return _USCIS


def uscis_approvals(company: str, data: dict | None = None) -> int:
    """Approval count for the employer. Exact name first; otherwise token-boundary containment
    (audit R10: substring matching let 'KLA' hit every employer containing those letters)."""
    data = uscis_data() if data is None else data
    if not data or not company:
        return 0
    name_norm = company.strip().upper()
    if name_norm in data:
        return data[name_norm].get("approvals", 0)
    if len(ledger.normalize_company(company)) < 3:
        return 0
    pat = re.compile(r'(?<![A-Z0-9])' + re.escape(name_norm) + r'(?![A-Z0-9])')
    best = 0
    for name, d in data.items():
        if pat.search(name):
            best = max(best, d.get("approvals", 0))
    return best


def score_sponsorship(job: dict, text: str, cfg: dict, is_intl: bool) -> tuple[int, str]:
    sc, w = cfg["scoring"]["sponsorship"], cfg["scoring"]["weights"]["sponsorship"]
    if not cfg["candidate"]["needs_sponsorship"]:
        return w, "candidate does not need sponsorship"
    if POSITIVE_SPONSOR_RE.search(text):
        return min(w, sc["stated"]), "JD states sponsorship / visa holders welcome"
    approvals = uscis_approvals(job.get("company", ""))
    for floor, pts in sc["filing_tiers"]:
        if approvals >= floor:
            return min(w, pts), f"H-1B filing record: {approvals} approvals"
    company = (job.get("company") or "").lower()
    for tier, spec in (cfg["known_sponsors"] or {}).items():
        if not isinstance(spec, dict):
            continue
        if any(word_match(k, company) for k in spec.get("companies", []) if k):
            pts = round(spec.get("points", sc["silent"]) * w / max(spec.get("points_out_of", w), 1))
            return min(w, pts), f"known sponsor ({tier} in your profile)"
    if is_intl:
        return min(w, sc["international_floor"]), "international role: skilled-worker visa baseline"
    return min(w, sc["silent"]), "silent, no filing record: neutral, not penalised"


# ── Domain ──────────────────────────────────────────────────────────────────

ANCHOR_HITS = 3  # ponytail: one anchor-company match outweighs three generic cue words


def score_domain(text: str, cfg: dict) -> tuple[int, str]:
    """
    The domain with the MOST cue hits wins; ties go to profile order. A hit on one
    of the domain's anchor companies counts as ANCHOR_HITS, so "Lucid Motors" stays
    CleanTech/EV even when the JD says "automotive" and "industrial" more often.
    Points fall linearly from the first-listed domain to the floor.

    Was: first domain in list order with ANY hit. A pharma JD whose boilerplate
    industry list said "aerospace" once was labelled Aerospace over a Precision/
    Regulated domain that matched twice (audit 2026-09-12, United Pharma row).
    """
    w, floor = cfg["scoring"]["weights"]["domain"], cfg["scoring"]["domain_floor"]
    domains = cfg["domains"]
    n = len(domains)
    best, best_hits = None, 0
    for i, d in enumerate(domains):
        cues = (d.get("cues") or []) + (d.get("title_keywords") or [])
        hits = sum(1 for c in cues if c and word_match(c, text))
        hits += ANCHOR_HITS * sum(1 for c in (d.get("company_keywords") or []) if c and word_match(c, text))
        if hits > best_hits:
            best, best_hits = i, hits
    if best is None:
        return floor, cfg["default_domain"]
    pts = w if n <= 1 else round(w - (w - floor) * best / (n - 1))
    return pts, domains[best]["name"]


# ── Role fit ────────────────────────────────────────────────────────────────

_YEARS_RANGE = re.compile(r'(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)', re.I)
_YEARS_ONE = re.compile(r'(\d{1,2})\s*\+?\s*(?:years?|yrs?)', re.I)
ENTRY_CUES = ["entry", "entry-level", "associate", "new grad", "new college grad", "graduate", "university",
              "junior", "jr", "i", "1", "level i", "level 1", "intern", "co-op", "coop", "early career", "rotational"]
SENIOR_CUES = ["senior", "sr", "lead", "ii", "iii", "2", "3", "level ii", "level 2", "level iii"]


def required_years(text: str) -> int | None:
    """
    Minimum years of experience the posting requires, or None if it never says.
    Reads requirement-zone lines when the JD has a requirements heading, else
    every line; only lines that mention experience count, so "founded 10 years
    ago" and "10-year warranty" never do (audit R7). Ranges take the low bound.
    """
    zoned, saw_req = ke.zone_lines(text or "")
    lines = [l for l, z in zoned if (z == "REQUIREMENT" if saw_req else True)]
    found = []
    for line in lines:
        if not re.search(r'(?i)\bexperience\b', line):
            continue
        for m in _YEARS_RANGE.finditer(line):
            found.append(int(m.group(1)))
        for m in _YEARS_ONE.finditer(_YEARS_RANGE.sub(" ", line)):
            found.append(int(m.group(1)))
    return min(found) if found else None


def score_role_fit(title: str, text: str, cfg: dict) -> tuple[int, str, bool]:
    """Returns (points, why, off_discipline)."""
    sc, w = cfg["scoring"]["role_fit"], cfg["scoring"]["weights"]["role_fit"]
    t = f" {title.lower()} "
    is_core = any(cue and cue in t for cue in cfg["scoring"]["core_role_cues"])
    if not is_core and any(cue and cue in t for cue in cfg["scoring"]["off_discipline_cues"]):
        return 0, f"off-discipline title ({title.strip()})", True

    max_years = int(cfg["candidate"]["max_years"])
    yrs = required_years(text)
    if yrs is not None:
        if yrs <= max_years:
            lvl, why = sc["within_max_years"], f"{yrs}+ years required, within your {max_years}"
        elif yrs > max_years + sc["far_over_margin_years"]:
            lvl, why = 0, f"{yrs}+ years required, far over your {max_years}"
        else:
            lvl, why = sc["over_max_years"], f"{yrs}+ years required, over your {max_years}"
    elif any(word_match(k, t) for k in ENTRY_CUES):
        lvl, why = sc["entry"], "entry / new grad / level I title"
    elif any(word_match(k, t) for k in SENIOR_CUES):
        lvl, why = sc["over_max_years"], "level II+ / senior title, years unstated"
    else:
        lvl, why = sc["unstated"], "level unstated"
    lvl = min(w, lvl)
    if not is_core:
        return round(lvl * sc["adjacent_discipline_factor"]), f"{why}; adjacent discipline, not one of your titles", False
    return lvl, why, False


# ── The score ───────────────────────────────────────────────────────────────

def score_job(job: dict, cfg: dict, tax: ke.Taxonomy) -> dict:
    sc, W = cfg["scoring"], cfg["scoring"]["weights"]
    title, company = job.get("title", "") or "", job.get("company", "") or ""
    desc = job.get("description", "") or ""
    combined = f"{title} {company} {desc}"
    is_intl = (job.get("source") or "").endswith("intl") or bool(INTL_LOCATION_RE.search(job.get("location") or ""))

    kw = ke.analyse(desc, tax)
    if kw["coverage"] is None:
        cov, cov_why = 0, f"no coverage signal ({kw['extraction']})"
    else:
        cov = round(W["coverage"] * kw["coverage"])
        cov_why = (f"{kw['coverage_percent']}% weighted ({kw['counts']['PROVEN']}P/{kw['counts']['EVIDENCED']}E/"
                   f"{kw['counts']['ADJACENT']}A/{kw['counts']['GAP']}G of {kw['keyword_total']})")
        if kw["extraction"] == "THIN":
            scale = kw["keyword_total"] / ke.MIN_CONFIDENT_KEYWORDS
            cov = round(cov * scale)
            cov_why += f" [THIN: {kw['keyword_total']} terms, scaled x{scale:.2f}]"

    spon, spon_why = score_sponsorship(job, combined, cfg, is_intl)
    dom, dom_label = score_domain(combined, cfg)
    fit, fit_why, off = score_role_fit(title, desc, cfg)
    log_, log_why = sc["logistics"]["fresh"], "fresh posting, direct employer"
    if job.get("freshness") == "REPOSTED":
        log_, log_why = sc["logistics"]["reposted"], "reposted / standing opening"
    if any(word_match(a, company.lower()) for a in cfg["staffing_agencies"]):
        log_, log_why = sc["logistics"]["staffing"], "staffing agency, not the employer"
    log_ = min(W["logistics"], log_)

    sub = {"coverage": cov, "sponsorship": spon, "domain": dom, "role_fit": fit, "logistics": log_}
    confidence = "NONE" if kw["extraction"] == "EMPTY_JD" else ("HIGH" if kw["extraction"] == "OK" else "LOW")
    return {
        "score": sum(sub.values()), "sub_scores": sub, "off_discipline": off, "confidence": confidence,
        "reasons": [
            f"Coverage ({cov}/{W['coverage']}) — {cov_why}",
            f"Sponsorship ({spon}/{W['sponsorship']}) — {spon_why}",
            f"Domain ({dom}/{W['domain']}) — {dom_label}",
            f"Role fit ({fit}/{W['role_fit']}) — {fit_why}",
            f"Logistics ({log_}/{W['logistics']}) — {log_why}",
        ],
        "domain": dom_label,
        "coverage_percent": kw["coverage_percent"], "keyword_counts": kw["counts"], "keyword_total": kw["keyword_total"],
        "extraction": kw["extraction"], "extraction_note": kw["extraction_note"],
        "claimable_keywords": kw["claimable"], "gap_keywords": kw["not_claimable"],
        "adjacent_keywords": kw["buckets"]["ADJACENT"], "required_gaps": kw["required_gaps"],
        "taxonomy_version": kw["taxonomy_version"],
    }


def rank_batch(jobs: list[dict], cfg: dict, tax: ke.Taxonomy, seen: ledger.Seen) -> list[dict]:
    """Gate, score and bucket every row. Pure: no files touched."""
    sc = cfg["scoring"]
    out = []
    for job in jobs:
        row = {**job, "gate0_passed": False, "caution_notes": []}
        why_seen = seen.match(job) if job.get("pass_num") != 0 and not job.get("carried_from") else ""
        if why_seen:
            out.append({**row, "score": 0, "sub_scores": {}, "bucket": "Drop", "lane": "Drop",
                        "verdict": "ALREADY SEEN", "reasons": [why_seen]})
            continue
        passed, verdict, reason, cautions = check_eligibility_gate(job, cfg)
        if not passed:
            out.append({**row, "score": 0, "sub_scores": {}, "bucket": "Drop", "lane": "Drop",
                        "verdict": verdict, "reasons": [reason], "caution_notes": cautions})
            continue
        s = score_job(job, cfg, tax)
        row.update(s, gate0_passed=True, caution_notes=cautions)
        if s["off_discipline"]:
            bucket, verdict = "Drop", "DROP (off-discipline)"
        elif s["confidence"] == "NONE":
            bucket, verdict = "Needs JD", "No description: cannot be scored"
        elif s["score"] < sc["apply_threshold"]:
            bucket, verdict = "Drop", f"Below threshold ({s['score']} < {sc['apply_threshold']})"
        elif s["confidence"] == "LOW":
            bucket, verdict = "Unverified", f"Above threshold but keyword check {s['extraction']}"
        else:
            bucket, verdict = "Apply", "Fit"
        row.update(bucket=bucket, lane=bucket, verdict=verdict)
        out.append(row)

    # Shortlist: confident Apply rows, best first, company-capped, top N.
    apply_rows = sorted([r for r in out if r["bucket"] == "Apply"], key=lambda r: -r["score"])
    counts: dict[str, int] = {}
    kept = 0
    for r in apply_rows:
        co = ledger.normalize_company(r.get("company", ""))
        if counts.get(co, 0) >= sc["max_per_company"]:
            r.update(bucket="Reserve", lane="Reserve", verdict=f"Held: {sc['max_per_company']} per company per day")
            continue
        if kept >= sc["shortlist_size"]:
            r.update(bucket="Reserve", lane="Reserve", verdict=f"Held: shortlist is {sc['shortlist_size']} rows")
            continue
        counts[co] = counts.get(co, 0) + 1
        kept += 1
    order = {"Apply": 0, "Reserve": 1, "Unverified": 2, "Needs JD": 3, "Drop": 4}
    return sorted(out, key=lambda r: (order[r["bucket"]], -r.get("score", 0)))


# ── Carry-over and ledger ───────────────────────────────────────────────────

FETCH_FIELDS = {"title", "company", "location", "link", "apply_url", "posted_at", "description", "needs_jd", "req_id",
                "seniority_level", "track", "source", "pass", "pass_num", "recruiter_url", "peer_url",
                "freshness", "freshness_badge", "freshness_detail", "mass_posted_locations"}


def load_carry_over(today: datetime, cfg: dict, seen: ledger.Seen, fetched_urls: set[str]) -> list[dict]:
    """Yesterday's Apply/Reserve rows that were not applied, tagged carried_from. `carry_over_days` back, default one."""
    rows = []
    for back in range(1, int(cfg["scoring"]["carry_over_days"]) + 1):
        day = (today - timedelta(days=back)).strftime("%Y-%m-%d")
        path = HISTORY_DIR / f"ranked_{day}.json"
        if not path.exists():
            continue
        try:
            for r in json.loads(path.read_text(encoding="utf-8")):
                if r.get("bucket") not in ("Apply", "Reserve") or r.get("carried_from"):
                    continue
                url = ledger.clean_url(r.get("link") or r.get("apply_url") or "")
                if url in fetched_urls or url in seen.applied_urls:
                    continue
                rows.append({**{k: v for k, v in r.items() if k in FETCH_FIELDS}, "carried_from": day})
        except Exception as e:
            print(f"Warning reading {path.name}: {e}", file=sys.stderr)
    return rows


def append_ledger(rows: list[dict], today: str) -> int:
    """Append every ranked row with its bucket as status. Adds a req_id column to the header if absent."""
    path = ledger.SEEN_JOBS_CSV
    header = "first_seen_date,market,company,title_normalized,city,job_url,fingerprint,status,req_id"
    if not path.exists():
        path.write_text(header + "\n", encoding="utf-8")
    else:
        first, _, rest = path.read_text(encoding="utf-8", errors="ignore").partition("\n")
        if "req_id" not in first:
            path.write_text(first.rstrip() + ",req_id\n" + rest, encoding="utf-8")
    existing = ledger.load_seen(path, supabase=False)
    new_rows = []
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            if r.get("carried_from") or r.get("verdict") == "ALREADY SEEN":
                continue
            url = ledger.clean_url(r.get("link") or r.get("apply_url") or "")
            if url and url in existing.urls:
                continue
            status = {"Apply": "shortlisted", "Reserve": "shortlisted", "Unverified": "unscored",
                      "Needs JD": "unscored", "Drop": "dropped"}[r["bucket"]]
            market = "INTL" if (r.get("source") or "").endswith("intl") else "US"
            fp = ledger.fingerprints(r.get("company", ""), r.get("title", ""))[0]
            row = {"first_seen_date": today, "market": market, "company": r.get("company", ""),
                   "title": (r.get("title") or "").lower(), "city": r.get("location", ""), "job_url": url,
                   "fingerprint": fp, "status": status, "req_id": r.get("req_id", "")}
            w.writerow([row[k] for k in ("first_seen_date", "market", "company", "title", "city", "job_url", "fingerprint", "status", "req_id")])
            new_rows.append(row)
    # Mirror to the shared Supabase ledger so other machines / tools skip these too.
    ledger.push_rows(new_rows)
    return len(new_rows)


# ── Rendering ───────────────────────────────────────────────────────────────

def write_outputs(ranked: list[dict], cfg: dict, today: str, ledger_written: int, carried: int) -> None:
    sc, W = cfg["scoring"], cfg["scoring"]["weights"]
    by = {b: [r for r in ranked if r["bucket"] == b] for b in ("Apply", "Reserve", "Unverified", "Needs JD", "Drop")}
    gated = [r for r in by["Drop"] if not r["gate0_passed"]]
    below = [r for r in by["Drop"] if r["gate0_passed"]]

    (PIPELINE_DIR / "ranked.json").write_text(json.dumps(ranked, indent=2), encoding="utf-8")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"ranked_{today}.json").write_text(json.dumps(ranked, indent=2), encoding="utf-8")

    L = [f"# 🎯 Gate A — Scored Shortlist — {today}\n",
         f"**{len(ranked)} postings evaluated** ({carried} carried from yesterday): **{len(by['Apply'])} to apply**, "
         f"{len(by['Reserve'])} in reserve, {len(by['Unverified'])} unverified, {len(by['Needs JD'])} need a JD, "
         f"{len(below)} below threshold, {len(gated)} gated. {ledger_written} rows recorded in the seen ledger.\n",
         f"> Score = Coverage {W['coverage']} + Sponsorship {W['sponsorship']} + Domain {W['domain']} + Role fit {W['role_fit']} + "
         f"Logistics {W['logistics']}. Apply at ≥ {sc['apply_threshold']}, top {sc['shortlist_size']}, max {sc['max_per_company']} per company. "
         f"`KW` = P/E/A/G counts of the ATS terms the JD asks for; Cov% weights required terms 2x.\n"]

    def table(rows, title, note=""):
        L.append(f"\n## {title} ({len(rows)})\n")
        if note:
            L.append(note + "\n")
        if not rows:
            L.append("_none_\n")
            return
        L.extend(["| # | Score | Cov% | KW (P/E/A/G) | Fit | Spon | Company | Title | Location | Pass | Apply | Networking |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"])
        for i, r in enumerate(rows, 1):
            kc, s = r.get("keyword_counts", {}), r.get("sub_scores", {})
            cov = f"{r['coverage_percent']}%" if r.get("coverage_percent") is not None else "—"
            if r.get("extraction") not in ("OK", None):
                cov += f" ⚠️{r['extraction']}"
            carried_mark = " ↩︎" if r.get("carried_from") else ""
            L.append(f"| {i} | **{r['score']}** | {cov} | {r.get('keyword_total', 0)} ({kc.get('PROVEN', 0)}/{kc.get('EVIDENCED', 0)}/{kc.get('ADJACENT', 0)}/{kc.get('GAP', 0)}) "
                     f"| {s.get('role_fit', 0)} | {s.get('sponsorship', 0)} | **{r['company']}**{carried_mark} | {r['title']} | {r['location']} | `{r.get('pass', '')}` "
                     f"| {'[Apply](' + r['link'] + ')' if r.get('link') else 'N/A'} | [Recruiter]({r.get('recruiter_url', '#')}) · [Team Lead]({r.get('peer_url', '#')}) |")

    table(by["Apply"], "Apply", "Confident scores above threshold. Approve rows to tailor.")
    L.append("\n### Why each Apply row scored what it did\n")
    for i, r in enumerate(by["Apply"], 1):
        L.append(f"\n**{i}. {r['title']} — {r['company']} ({r['score']})**")
        L += [f"- {x}" for x in r["reasons"]]
        if r.get("claimable_keywords"):
            L.append(f"- ✅ Claimable: {', '.join(r['claimable_keywords'])}")
        if r.get("adjacent_keywords"):
            L.append(f"- 🟡 Adjacent (half credit): {', '.join(r['adjacent_keywords'])}")
        if r.get("gap_keywords"):
            L.append(f"- ❌ Gap (not claimable today): {', '.join(r['gap_keywords'])}")
        if r.get("required_gaps"):
            L.append(f"- 🚨 Required terms not fully proven: {', '.join(r['required_gaps'])}")
        for n in r.get("caution_notes", []):
            L.append(f"- 🟠 Caution: {n}")
    L.append("\n> To claim a gap term, reply with the term and your evidence; it is written to `data/keyword_taxonomy.json` as proven.\n")
    table(by["Reserve"], "Reserve", "Scored as Apply but held by the company cap or the shortlist size. Say the word to promote one.")
    table(by["Unverified"], "Unverified", "Above threshold, but the keyword check was thin or unscoped, so the score is low-confidence. Read the JD before trusting the number.")
    table(by["Needs JD"], "Needs a job description", "No text arrived, so nothing could be checked. Paste the JD into `JDs/<today>/` and rerun pass 0 to score these.")
    L.append(f"\n## Below threshold ({len(below)})\n")
    L += ["| Score | Company | Title | Location | Why |", "|---|---|---|---|---|"] if below else ["_none_"]
    L += [f"| {r['score']} | {r['company']} | {r['title']} | {r['location']} | {'; '.join(r['reasons'])} |" for r in below]
    L.append(f"\n## Gated out ({len(gated)})\n")
    L += [f"- **{r['company']} — {r['title']}**: `{r['verdict']}` — {'; '.join(r['reasons'])}" for r in gated] or ["_none_"]
    L.append("\n---\n### 🧑 Gate A\nReview the Apply table and name the rows to tailor. Promote a Reserve or Unverified row by number.\n")
    (PIPELINE_DIR / "ranked.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    slim_keys = ("company", "title", "location", "link", "score", "sub_scores", "confidence", "coverage_percent",
                 "keyword_total", "keyword_counts", "extraction", "extraction_note", "claimable_keywords",
                 "adjacent_keywords", "gap_keywords", "required_gaps", "caution_notes", "verdict", "freshness", "carried_from", "pass")
    totals = {b: len(v) for b, v in by.items()}
    totals.update({"gated": len(gated), "below_threshold": len(below), "ledger_written": ledger_written, "carried": carried})
    summary = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "formula": W, "apply_threshold": sc["apply_threshold"], "shortlist_size": sc["shortlist_size"],
        "totals": totals,
        "gated": [{"company": r["company"], "title": r["title"], "verdict": r["verdict"], "reason": r["reasons"][0]} for r in gated],
        "apply": [{k: r.get(k) for k in slim_keys} for r in by["Apply"]],
        "reserve": [{k: r.get(k) for k in slim_keys} for r in by["Reserve"]],
        "unverified": [{k: r.get(k) for k in slim_keys} for r in by["Unverified"]],
        "needs_jd": [{"company": r["company"], "title": r["title"], "location": r["location"], "link": r["link"]} for r in by["Needs JD"]],
    }
    (PIPELINE_DIR / "ranked_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    fetched = PIPELINE_DIR / "fetched.json"
    if not fetched.exists():
        print(f"Error: {fetched} does not exist. Run tools/fetch_jobs.py first.", file=sys.stderr)
        return 1
    jobs = json.loads(fetched.read_text(encoding="utf-8"))
    cfg = build_cfg()
    tax = ke.Taxonomy.load()
    seen = ledger.load_seen()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    carried = [] if "--no-carry" in argv else load_carry_over(now, cfg, seen, {ledger.clean_url(j.get("link", "")) for j in jobs})
    ranked = rank_batch(jobs + carried, cfg, tax, seen)
    written = 0 if "--no-ledger" in argv else append_ledger(ranked, today)
    write_outputs(ranked, cfg, today, written, len(carried))

    by: dict[str, int] = {}
    for r in ranked:
        by[r["bucket"]] = by.get(r["bucket"], 0) + 1
    print(f"Ranked {len(ranked)} ({len(carried)} carried): " + ", ".join(f"{k} {v}" for k, v in by.items()))
    print(f"Ledger: {written} rows appended. Handoffs: {PIPELINE_DIR / 'ranked.json'}, ranked.md, ranked_summary.json")
    return 0


# ── Self-test: synthetic profile, synthetic taxonomy, no personal data ──────

def _test_profile() -> dict:
    return {
        "candidate": {"needs_sponsorship": True, "max_years": 2, "languages": ["english"]},
        "search": {"role_titles": ["Quality Engineer", "Process Engineer"], "adjacent_titles": ["Quality Technician"]},
        "target_anchors": ["northwind"],
        "domains": [{"name": "Aero", "title_keywords": ["aerospace", "composites"], "company_keywords": ["northwind"]},
                    {"name": "Semi", "title_keywords": ["wafer", "semiconductor"], "company_keywords": []},
                    {"name": "Auto", "title_keywords": ["automotive"], "company_keywords": []}],
        "default_domain": "General",
        "known_non_sponsors": {"nosponsor corp": "policy: no sponsorship"},
        "known_sponsors": {"tier1": {"points": 26, "points_out_of": 30, "companies": ["contoso"]}},
        "staffing_agencies": ["acme staffing"],
        "scoring": {"shortlist_size": 3, "max_per_company": 1},
    }


def run_self_test() -> int:
    fails = []

    def check(name, ok):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            fails.append(name)

    cfg = build_cfg(_test_profile())
    tax = ke.Taxonomy.load(ke.TEST_TAXONOMY)
    seen = ledger.Seen()
    jd_ok = "Requirements\n- SPC and PFMEA experience required\n- GD&T, CMM, 8D\n- Control plans\n- Bachelor's degree, 0-2 years experience\n"

    def job(**kw):
        base = {"title": "Quality Engineer", "company": "Widget Works", "location": "Austin, TX", "link": "https://x/1",
                "description": jd_ok, "source": "linkedin_apify_p2", "freshness": "FRESH", "pass_num": 2}
        return {**base, **kw}

    print("config is the source of every knob")
    check("weights sum to 100", sum(cfg["scoring"]["weights"].values()) == 100)
    check("core cues default to the profile's titles", "quality engineer" in cfg["scoring"]["core_role_cues"])
    check("profile scoring overrides apply", cfg["scoring"]["shortlist_size"] == 3)

    print("\nGate 0")
    g = lambda **kw: check_eligibility_gate(job(**kw), cfg)  # noqa: E731
    check("English JD with 'taken' is not a language drop (R4)", g(description="Actions to be taken. " + jd_ok)[0])
    check("two Dutch body cues gate", not g(description="Functieomschrijving: ... Profiel: ...")[0])
    check("one foreign body cue does not gate", g(description="Profiel: " + jd_ok)[0])
    check("foreign title word gates on its own", not g(title="Ingénieur Qualité", description=jd_ok)[0])
    check("accepted language is not gated", check_eligibility_gate(job(title="Ingénieur Qualité"), build_cfg({**_test_profile(), "candidate": {"languages": ["english", "french"]}}))[0])
    check("same caution never listed twice",
          len(check_eligibility_gate(job(description="Export control regulations (ITAR/EAR) may apply to this role. "
                                                     "ITAR and EAR compliance is part of our onboarding."), cfg)[3])
          == len(set(check_eligibility_gate(job(description="Export control regulations (ITAR/EAR) may apply to this role. "
                                                            "ITAR and EAR compliance is part of our onboarding."), cfg)[3])))
    check("export-control boilerplate is CAUTION not gate (R5)", g(description="Comply with export control laws. " + jd_ok)[0])
    check("export-control requirement gates", not g(description="Must be a U.S. person to access export controlled technology. " + jd_ok)[0])
    check("requirement in the NEXT sentence still gates", not g(description="Work involves ITAR data. Applicants must be U.S. persons. " + jd_ok)[0])
    check("'may require a license' is CAUTION not gate", g(description="This role may require access to export controlled information. Applicants must be authorized or eligible for government authorization. " + jd_ok)[0])
    check("'does not sponsor' gates", not g(description="We do not sponsor work visas. " + jd_ok)[0])
    check("'not eligible for ... sponsorship' gates", not g(description="This position is not eligible for employment-based visa sponsorship, now or in the future. " + jd_ok)[0])
    check("welcoming citizenship mention is CAUTION", g(description="US citizens and visa holders welcome. " + jd_ok)[0])
    check("conditional citizenship (licensing review) is CAUTION not gate", g(description="Applicants for this position - except US Citizens and protected individuals as defined by 8 U.S.C. 1324b(a)(3) - may have to go through an export licensing review process. " + jd_ok)[0])
    check("hard citizenship still gates", not g(description="U.S. citizenship is required for this position. " + jd_ok)[0])
    check("'ear protection' does not trip EAR", g(description="PPE: ear protection. " + jd_ok)[0])
    check("company gate from config", not g(company="NoSponsor Corp")[0])
    check("needs_sponsorship=false skips visa gates", check_eligibility_gate(job(company="NoSponsor Corp"), build_cfg({**_test_profile(), "candidate": {"needs_sponsorship": False}}))[0])
    check("title drop cue (director)", not g(title="Director of Quality")[0])
    check("intern title is NOT dropped (Pass 4 fetches them)", g(title="Quality Engineering Intern")[0])
    check("technician title is NOT dropped", g(title="Quality Technician")[0])

    print("\nrole fit and years (R7)")
    check("'founded 10 years ago' is not a requirement", required_years("About us\nFounded 10 years ago.\nRequirements\n- SPC experience") is None)
    check("'2-5 years experience' takes the low bound", required_years("Requirements\n- 2-5 years of experience") == 2)
    check("'5+ years experience' is 5", required_years("Requirements\n- 5+ years experience in quality") == 5)
    check("within max years scores full", score_role_fit("Quality Engineer", "Requirements\n- 0-2 years experience", cfg)[0] == 12)
    check("far over max years scores 0", score_role_fit("Quality Engineer", "Requirements\n- 8+ years experience", cfg)[0] == 0)
    check("off-discipline title flagged", score_role_fit("Quality Inspector", jd_ok, cfg)[2])
    check("adjacent discipline halves level credit", score_role_fit("Materials Engineer I", "Bachelor's", cfg)[0] == round(15 * 0.5))

    print("\nsponsorship and domain")
    check("stated sponsorship scores max", score_sponsorship(job(), "visa sponsorship available", cfg, False)[0] == 25)
    check("known sponsor tier scaled to axis", score_sponsorship(job(company="Contoso"), "nothing", cfg, False)[0] == round(26 * 25 / 30))
    check("silent is neutral 8", score_sponsorship(job(company="Unknown LLC"), "nothing", cfg, False)[0] == 8)
    check("short USCIS names need a token match (R10)", uscis_approvals("KLA", {"OKLAHOMA STATE": {"approvals": 99}}) == 0)
    check("USCIS token match works", uscis_approvals("KLA", {"KLA CORPORATION": {"approvals": 99}}) == 99)
    check("first domain scores full", score_domain("composites work", cfg)[0] == 15)
    check("last domain scores the floor", score_domain("automotive plant", cfg)[0] == 3)
    check("unmatched is the floor + default label", score_domain("nothing here", cfg) == (3, "General"))
    check("most cue hits wins over list order",
          score_domain("aerospace mentioned once; wafer and semiconductor twice", cfg)[1] == "Semi")
    check("tie goes to list order", score_domain("aerospace and automotive", cfg)[1] == "Aero")
    check("anchor company beats generic cues",
          score_domain("northwind plant: automotive automotive", cfg)[1] == "Aero")

    print("\nbuckets and shortlist")
    batch = [job(link=f"https://x/{i}", company=f"Co{i}") for i in range(5)]
    batch += [job(link="https://x/dup", company="Co0"),                       # company cap
              job(link="https://x/blank", company="Blank Co", description=""),  # needs JD
              job(link="https://x/thin", company="Thin Co", description="Requirements\n- SPC, composites\n- visa sponsorship available"),
              job(link="https://x/insp", company="Insp Co", title="Quality Inspector"),
              job(link="https://x/gate", company="NoSponsor Corp")]
    ranked = rank_batch(batch, cfg, tax, seen)
    b: dict[str, int] = {}
    for r in ranked:
        b[r["bucket"]] = b.get(r["bucket"], 0) + 1
    check("top-N shortlist honoured", b.get("Apply") == 3)
    check("overflow and company-cap rows go to Reserve", b.get("Reserve") == 3)
    check("blank JD is Needs JD, not Drop", b.get("Needs JD") == 1)
    check("thin keyword check is Unverified", b.get("Unverified") == 1)
    check("off-discipline + gated are Drop", b.get("Drop") == 2)
    check("Apply rows sorted best first", [r["score"] for r in ranked[:3]] == sorted([r["score"] for r in ranked[:3]], reverse=True))
    seen.add(url="https://x/0")
    check("ledger match drops a row", any(r["verdict"] == "ALREADY SEEN" for r in rank_batch(batch, cfg, tax, seen)))
    check("pass-0 rows bypass the ledger", not any(r["verdict"] == "ALREADY SEEN" for r in rank_batch([job(link="https://x/0", pass_num=0)], cfg, tax, seen)))
    check("carried rows bypass the ledger", not any(r["verdict"] == "ALREADY SEEN" for r in rank_batch([job(link="https://x/0", carried_from="2026-01-01")], cfg, tax, seen)))

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILURE(S): ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    sys.exit(main(sys.argv[1:]))
