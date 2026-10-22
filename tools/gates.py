#!/usr/bin/env python3
"""
gates.py: Gate 0 for the niche sprint (visa / ITAR / sponsorship, future-start
interns, title level, language, local residency) plus the required-years reader.
Used by tools/triage.py. Split out of the Fortify-era gate_and_score.py so the
keyword engine and taxonomy could go.

  python3 tools/gates.py --self-test
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import load_config  # noqa: E402

GATE_DEFAULTS = {
    "off_discipline_cues": ["inspector", "auditor", "software", "sales", "account manager", "recruiter",
                            "designer", "architect", "data scientist", "financial", "marketing", "nurse",
                            "driver", "field service", "customer service"],
    # Titles that are never the candidate's level or discipline, whatever the JD says.
    "title_drop_cues": ["machinist", "operator", "assembler", "welder", "fabricator", "apprentice",
                        "principal", "director", "head of", "vice president", "vp ", "chief", "executive",
                        "senior manager", "staff engineer"],
    "drop_non_english": True,
    "drop_future_intern_year": 2027,   # intern / co-op programs starting summer of this year or later are dropped; 0 turns it off
    "drop_intl_staffing": True,
}
CANDIDATE_DEFAULTS = {"needs_sponsorship": True, "max_years": 2, "languages": ["english"]}


def build_cfg(profile: dict | None = None) -> dict:
    """Merge GATE_DEFAULTS with the profile's `scoring` block (one level deep)."""
    profile = profile if profile is not None else load_config()
    sc = json.loads(json.dumps(GATE_DEFAULTS))
    for k, v in (profile.get("scoring") or {}).items():
        if isinstance(v, dict) and isinstance(sc.get(k), dict):
            sc[k].update(v)
        else:
            sc[k] = v
    cand = {**CANDIDATE_DEFAULTS, **(profile.get("candidate") or {})}
    return {"scoring": sc, "candidate": cand,
            "known_non_sponsors": profile.get("known_non_sponsors") or {},
            "known_itar_flags": profile.get("known_itar_flags") or {},
            "staffing_agencies": [a.lower() for a in profile.get("staffing_agencies") or []]}

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
    (r'(?i)(?:will|would|does|do|can|could|are|is|must|shall|should|may)\s+not\s+(?:\w+\s+){0,4}?sponsor', "No visa sponsorship", "hard"),
    (r'(?i)\bcannot\s+(?:\w+\s+){0,4}?sponsor', "No visa sponsorship", "hard"),
    (r'(?i)(?:unable|not\s+able|unwilling)\s+to\s+(?:\w+\s+){0,3}?sponsor', "No visa sponsorship", "hard"),
    (r'(?i)(?:does|do|will|can|cannot)\s+not?\s+(?:provide|offer|support|extend)\s+(?:\w+\s+){0,3}?sponsorship', "No visa sponsorship", "hard"),
    # "It is ATI's policy to not provide immigration sponsorship" (2026-10-20 miss)
    (r'(?i)\bpolicy\s+(?:is\s+)?(?:to\s+)?not\s+(?:to\s+)?(?:provide|offer|support|extend)\s+(?:\w+\s+){0,3}?sponsorship', "No visa sponsorship", "hard"),
    (r'(?i)\bno\s+(?:visa\s+|immigration\s+|work\s+visa\s+|employment\s+|h-?1b\s+)?sponsorship\b', "No visa sponsorship", "hard"),
    (r'(?i)sponsorship\s+(?:is|will)\s+not\s+(?:be\s+)?(?:available|offered|provided|considered)', "No visa sponsorship", "hard"),
    (r'(?i)not\s+eligible\s+for\s+(?:[\w-]+\s+){0,4}?(?:\w+-)?sponsor', "No visa sponsorship", "hard"),
    # "without corporate sponsorship", "without any sponsorship", "without need for employer sponsored visa"
    (r'(?i)without\s+(?:the\s+)?(?:need\s+(?:for\s+)?)?(?:[\w-]+\s+){0,3}?sponsor', "Must work without sponsorship", "hard"),
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
_NO_SPONSOR_RES = [re.compile(p) for p, label, mode in VISA_ITAR_PATTERNS if mode == "hard" and "sponsorship" in label.lower()]


def stated_sponsorship(text: str) -> bool:
    """A POSITIVE_SPONSOR_RE hit that is not next to a no-sponsorship phrase. "Must not require sponsorship
    (e.g., H-1B, O-1)" names H-1B to refuse it. A char window, not a sentence: "e.g." breaks sentence splits."""
    for m in POSITIVE_SPONSOR_RE.finditer(text):
        window = text[max(0, m.start() - 250):m.end() + 100]
        if not any(p.search(window) for p in _NO_SPONSOR_RES):
            return True
    return False


# Intern / co-op programs that start after the candidate's visa runway (learning_log 2026-09-21).
INTERN_TITLE_RE = re.compile(r'(?i)\b(?:intern(?:ship)?s?|co-?ops?)\b')
YEAR_RE = re.compile(r'\b(20[2-9]\d)\b')
PROGRAM_TIMING_RE = re.compile(r'(?i)\b(?:start(?:s|ing)?|begin(?:s|ning)?|program|summer|spring|fall|autumn|winter|semester|term|dates?|duration|session)\b')
GRADUATION_RE = re.compile(r'(?i)\b(?:graduat\w*|degree|expected|anticipated|class\s+of|enrolled)\b')
START_TOKEN_RE = re.compile(r'(?i)\b(?:winter|spring|summer|fall|autumn)\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d')
EARLY_START_RE = re.compile(r'(?i)^(?:winter|spring|jan|feb|mar|apr)')


def future_intern_start(job: dict, min_year: int) -> str:
    """The quoted timing text when an intern / co-op title starts in summer of min_year or later, else "".
    Not a future start: a sentence with any earlier year (a range that began already, Aug 2026 - May 2027),
    a graduation-date sentence (eligibility, not timing), a title that carries an earlier year ("2026 Intern
    Conversion", full-time by 2027), or a min_year program whose first month or season is winter to April."""
    title = job.get("title") or ""
    if not min_year or not INTERN_TITLE_RE.search(title) or any(int(y) < min_year for y in YEAR_RE.findall(title)):
        return ""
    for sentence in [title] + re.split(r'(?<=[.!?])\s+|\n', job.get("description") or ""):
        years = [int(y) for y in YEAR_RE.findall(sentence)]
        if not years or min(years) < min_year:
            continue
        if sentence is not title and (not PROGRAM_TIMING_RE.search(sentence) or GRADUATION_RE.search(sentence)):
            continue
        first = START_TOKEN_RE.search(sentence)
        if min(years) == min_year and first and EARLY_START_RE.match(first.group()):
            continue
        return " ".join(sentence.split())[:160]
    return ""


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
    "german": ["praktikum", "praktikant", "werkstudent", "abschlussarbeit", "ingenieur", "ingenieurin", "qualitätsingenieur", "fachkraft",
               "techniker", "mitarbeiter", "qualitätsmanagement", "qualitätssicherung"],
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
# Phrase cues miss postings that never use those exact phrases (Vishay Itzehoe, KRAUSE-Werk, 2026-09-28).
# Running prose in another language is dense in function words that are not English words; an English JD
# with one foreign sentence is not. Chosen to avoid English collisions ("die", "van", "met", "per", "las", "con").
LANGUAGE_FUNCTION_WORDS = {
    "german": "und der das mit für sie wir ist von eine oder nicht werden auch bei sich dem zur zum sind haben wird ihre unser".split(),
    "dutch": "het een voor zijn wij niet ook naar bij wordt worden jouw onze".split(),
    "french": "les des une pour vous nous est dans sur avec sont notre votre aux ces être".split(),
    "spanish": "los una para por del como más nuestro usted sus también".split(),
    "italian": "gli una con della delle sono nel nella nostro anche degli".split(),
    "portuguese": "não uma para com dos das são nosso nossa também você".split(),
}
FUNCTION_WORD_MIN_HITS, FUNCTION_WORD_MIN_SHARE = 12, 0.05
WORD_RE = re.compile(r"[a-zäöüßéèêàçñãõáíóúâôœ]+")
INTL_LOCATION_RE = re.compile(r'(?i)\b(europe|belgium|netherlands|germany|france|italy|spain|sweden|switzerland|austria|ireland|denmark|australia|canada|singapore|united kingdom|uk)\b')


def detect_foreign_language(title: str, text: str, accepted: list[str]) -> str:
    t, low = title.lower(), text.lower()
    for lang, cues in LANGUAGE_TITLE_CUES.items():
        if lang not in accepted and any(word_match(c, t) for c in cues):
            return lang
    for lang, cues in LANGUAGE_CUES.items():
        if lang not in accepted and sum(1 for c in cues if word_match(c, low)) >= 2:
            return lang
    words = WORD_RE.findall(low)
    for lang, fw in LANGUAGE_FUNCTION_WORDS.items():
        if lang in accepted:
            continue
        hits = sum(1 for w in words if w in fw)
        if hits >= FUNCTION_WORD_MIN_HITS and hits / len(words) >= FUNCTION_WORD_MIN_SHARE:
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

        timing = future_intern_start(job, sc["drop_future_intern_year"])
        if timing:
            return False, "DROP (FUTURE-START)", f"Intern / co-op starts {sc['drop_future_intern_year']} or later, past your work-authorization runway: \"{timing}\"", cautions

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


# ── Required years ──────────────────────────────────────────────────────────

# A requirements heading opens the zone; any other known heading closes it.
REQUIREMENT_HEADER_RE = re.compile(
    r'^\s*#{0,6}\s*\**\s*(?:'
    r'required(?:\s+qualifications)?|requirements?|qualifications|'
    r'(?:basic|minimum|essential|preferred|desired)\s+(?:qualifications|requirements|skills)|'
    r'must[- ]haves?|nice[- ]to[- ]haves?|preferred|'
    r"what\s+we(?:'|’)?re\s+looking\s+for|"
    r"what\s+you(?:(?:'|’)ll|\s+will)?\s+bring|"
    r'who\s+you\s+are|about\s+you|your\s+(?:background|experience|profile)|'
    r"you(?:(?:'|’)ll|\s+will)?\s+have|"
    r'skills\s+(?:and|&)\s+experience|'
    r'(?:education|experience)\s+(?:and|&)\s+(?:experience|qualifications)|'
    r'competencies'
    r')\b',
    re.IGNORECASE,
)

# Closes a requirements block. Without these the block stays open to end-of-file
# and sweeps the benefits list into "required skills" — turning 401k and equity
# into reported gaps. Checked BEFORE the opener so a heading matching both
# (e.g. "Why this role") closes rather than reopens.
NON_REQUIREMENT_HEADER_RE = re.compile(
    r'^\s*#{0,6}\s*\**\s*(?:'
    r'you\s+will(?!\s+have)|responsibilities|duties|what\s+you(?:\'|’)?ll\s+do|'
    r'the\s+role|job\s+summary|job\s+description|position\s+summary|'
    r'benefits?|perks?|compensation|salary|pay\s+range|total\s+rewards|'
    r'what\s+we\s+offer|why\s+(?:join|work|us)|'
    r'about\s+(?:us|the\s+company|the\s+team|our)|our\s+(?:values|mission|culture)|'
    r'equal\s+(?:opportunity|employment)|eeo|diversity|accommodation|'
    r'interview\s+process|how\s+to\s+apply|to\s+apply|application\s+process|'
    r'physical\s+(?:demands|requirements)|work\s+environment|other\s+information|'
    r'disclaimer|legal|privacy'
    r')\b',
    re.IGNORECASE,
)

_YEARS_RANGE = re.compile(r'(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)', re.I)
_YEARS_ONE = re.compile(r'(\d{1,2})\s*\+?\s*(?:years?|yrs?)', re.I)


def required_years(text: str) -> int | None:
    """
    Minimum years of experience the posting requires, or None if it never says.
    Reads lines under a requirements heading when the JD has one, else every
    line; only lines that mention experience count, so "founded 10 years ago"
    and "10-year warranty" never do. Ranges take the low bound.
    """
    lines, req, in_req, saw_req = (text or "").split("\n"), [], False, False
    for line in lines:
        if NON_REQUIREMENT_HEADER_RE.match(line):
            in_req = False
        elif REQUIREMENT_HEADER_RE.match(line):
            in_req = saw_req = True
        elif in_req:
            req.append(line)
    found = []
    for line in (req if saw_req else lines):
        if not re.search(r'(?i)\bexperience\b', line):
            continue
        for m in _YEARS_RANGE.finditer(line):
            found.append(int(m.group(1)))
        for m in _YEARS_ONE.finditer(_YEARS_RANGE.sub(" ", line)):
            found.append(int(m.group(1)))
    return min(found) if found else None


# ── Self-test: synthetic profile, no personal data ──────────────────────────

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
        "staffing_agencies": ["acme staffing"],
    }


def run_self_test() -> int:
    fails = []

    def check(name, ok):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            fails.append(name)

    cfg = build_cfg(_test_profile())
    jd_ok = "Requirements\n- SPC and PFMEA experience required\n- GD&T, CMM, 8D\n- Control plans\n- Bachelor's degree, 0-2 years experience\n"

    def job(**kw):
        base = {"title": "Quality Engineer", "company": "Widget Works", "location": "Austin, TX", "link": "https://x/1",
                "description": jd_ok, "source": "linkedin_apify_p2", "freshness": "FRESH", "pass_num": 2}
        return {**base, **kw}

    print("Gate 0")
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
    check("'policy to not provide immigration sponsorship' gates", not g(description="It is ATI's policy to not provide immigration sponsorship for any of the company's positions. " + jd_ok)[0])
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

    print("\nGate 0: phrasing the 2026-09-28 run missed")
    check("'without corporate sponsorship' gates", not g(description="Must be able to work in the United States without corporate sponsorship now and within the future. " + jd_ok)[0])
    check("'without need for employer sponsored visa' gates", not g(description="Must be eligible to work in the U.S. without need for employer sponsored visa (work permit). " + jd_ok)[0])
    check("'without any sponsorship' gates", not g(description="Candidates who can work on W2 without any sponsorship are encouraged to apply. " + jd_ok)[0])
    check("'must not require sponsorship (e.g., H-1B)' gates", not g(description="Applicants must not require sponsorship for employment visa status (e.g., H-1B, O-1). " + jd_ok)[0])
    check("'not eligible for employer-sponsored work authorization' gates", not g(description="This position is not eligible for employer-sponsored work authorization. " + jd_ok)[0])
    check("'cannot sponsor' gates", not g(description="The company cannot sponsor visas. " + jd_ok)[0])
    check("'visa sponsorship provided' is not gated", g(description="Relocation and visa sponsorship provided. " + jd_ok)[0])

    print("\nGate 0: future-start intern / co-op")
    check("Summer 2027 intern title drops", not g(title="Quality Intern - Summer 2027")[0])
    check("May-Aug 2027 program in the body drops", not g(title="Quality Intern", description="The program is planned to occur between May 17 and August 6, 2027. " + jd_ok)[0])
    check("2028 program drops", not g(title="Quality Intern - Summer 2028")[0])
    check("Spring 2027 co-op is kept (rule is summer or later)", g(title="Process Co-op - Spring 2027")[0])
    check("Jan-Jun 2027 co-op is kept", g(title="Quality Co-op", description="This co-op runs from January 4, 2027, through June 25, 2027. " + jd_ok)[0])
    check("a range that began in 2026 is kept", g(title="Engineering Co-op", description="A 2 semester assignment, starting August 2026 through May 2027. " + jd_ok)[0])
    check("a graduation date is not a start date", g(title="Quality Intern", description="Students expected to graduate in summer 2027 may apply. " + jd_ok)[0])
    check("'2026 Intern Conversion' with a 2027 full-time start is kept", g(title="Quality Engineer I - 2026 Intern Conversion", description="Able to start working full-time on or before September of 2027. " + jd_ok)[0])
    check("non-intern title with a 2027 date is untouched", g(title="Quality Engineer", description="Start date in summer 2027. " + jd_ok)[0])
    check("drop_future_intern_year=0 turns it off", check_eligibility_gate(job(title="Quality Intern - Summer 2027"), build_cfg({**_test_profile(), "scoring": {"drop_future_intern_year": 0}}))[0])

    print("\nGate 0: language by function-word density")
    german = "Wir sind ein Unternehmen und suchen einen Kollegen für die Qualität. Sie werden mit dem Team arbeiten und sind bei uns willkommen. " * 3
    check("German prose without phrase cues gates", not g(description=german)[0])
    check("English JD with one German sentence is not gated", g(description=jd_ok + " Wir suchen Sie und Ihr Team für die Zukunft.")[0])

    print("\nrequired years")
    check("'founded 10 years ago' is not a requirement", required_years("About us\nFounded 10 years ago.\nRequirements\n- SPC experience") is None)
    check("'2-5 years experience' takes the low bound", required_years("Requirements\n- 2-5 years of experience") == 2)
    check("'5+ years experience' is 5", required_years("Requirements\n- 5+ years experience in quality") == 5)

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILURE(S): ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run_self_test() if "--self-test" in sys.argv else 0)
