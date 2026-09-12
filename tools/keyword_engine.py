#!/usr/bin/env python3
"""
keyword_engine.py — truthful ATS keyword coverage for the ranker and customiser.

Answers one question per posting: *how much of what this JD actually asks for can
the candidate put on a resume without lying?* That number, not JD keyword density, is
what the ranker sorts on.

Why not let an LLM extract the keywords: the coverage percentage has to be
comparable across runs and testable in CI. Free-form extraction gives a different
denominator every time, so 78% today and 71% next week would mean nothing. The
domain here is narrow enough to enumerate, so we match a controlled vocabulary
(data/keyword_taxonomy.json) and let the model audit the result instead.

Pipeline, per JD:
  1. scope        — find the requirement blocks, ignore benefits/EEO/about-us
  2. extract      — match the controlled vocabulary, word-bounded, dedup to canonical
  3. weight       — required (2) vs preferred (1), and record why
  4. classify     — PROVEN / EVIDENCED / ADJACENT / GAP against the evidence catalog
  5. coverage     — weighted credit over weighted total

The section state machine and the "an empty result is not a clean pass" contract
are adapted from career-ops' jd-skill-gap.mjs (MIT, already vendored as a sibling
clone for tools/ats_scan.mjs). Their scar tissue is worth inheriting: without the
non-requirement headers, a benefits list turns "401k" and "Equity" into skill
gaps; without the diagnose step, "extracted nothing" reads identically to "no
gaps found", which is the more dangerous of the two.

Usage:
  python3 tools/keyword_engine.py --self-test
  python3 tools/keyword_engine.py --audit                 # taxonomy drift check
  python3 tools/keyword_engine.py tests/fixtures/micron_ncg.txt
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
TAXONOMY_FILE = ROOT_DIR / "data" / "keyword_taxonomy.json"

# At most this many keywords enter the denominator. A 3,000-word posting must not
# become a 40-item checklist; required terms fill the budget before preferred ones.
MAX_KEYWORDS = 15

# Below this, a coverage percentage is not meaningful enough to rank on.
MIN_CONFIDENT_KEYWORDS = 4

WEIGHT_REQUIRED = 2
WEIGHT_PREFERRED = 1

CREDIT = {"PROVEN": 1.0, "EVIDENCED": 1.0, "ADJACENT": 0.5, "GAP": 0.0}

# ── Section scoping ─────────────────────────────────────────────────────────
#
# Opens a requirements block. Real postings rarely use the literal word
# "Requirements" — the modern ATS templates ship "What you'll bring", "Who you
# are", "You have". A JD that yields zero keywords because we only looked for
# one heading reads exactly like a JD with no requirements, which is the failure
# this list exists to prevent.
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

REQUIRED_CUE_RE = re.compile(
    r'(?i)\b(?:required|require[sd]?|must\s+have|must\s+be|mandatory|essential|minimum)\b')
PREFERRED_CUE_RE = re.compile(
    r'(?i)\b(?:preferred|prefer|nice\s+to\s+have|desired|desirable|a\s+plus|bonus|'
    r'beneficial|advantageous|ideally|helpful)\b')


# ── Taxonomy ────────────────────────────────────────────────────────────────

class Taxonomy:
    """The controlled vocabulary plus the candidate evidence catalog."""

    def __init__(self, data: dict):
        self.version = data.get("version", "0")
        self.terms = data["terms"]
        self.families = data.get("families", {})
        self.by_canonical = {t["canonical"]: t for t in self.terms}
        # Longest alias first so "process fmea" wins over "fmea" on the same span.
        self._alias_index = sorted(
            ((alias, t) for t in self.terms for alias in t["aliases"]),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        # A family is "reachable" if anything in it is claimable. One hop only:
        # chaining SPC -> Cp/Cpk -> APQP -> PPAP would eventually prove everything,
        # which is exactly how a coverage metric gets gamed.
        self.reachable_families = {
            t["family"] for t in self.terms if t["status"] in ("proven", "evidenced")
        }

    @classmethod
    def load(cls, path: Path = TAXONOMY_FILE) -> "Taxonomy":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def anchors_for(self, family: str) -> list[str]:
        """Claimable terms in a family — the 'defensible because…' evidence at Gate A."""
        return [t["canonical"] for t in self.terms
                if t["family"] == family and t["status"] in ("proven", "evidenced")]


def term_in_text(alias: str, text: str) -> bool:
    """
    Word-bounded containment.

    Boundaries are alphanumeric lookarounds rather than \\b because the vocabulary
    is full of symbol-edged terms — gd&t, cp/cpk, gage r&r, 8d, c++. After '&' or
    '/', \\b asserts against the wrong character class and never fires.
    """
    return re.search(r'(?<![a-z0-9])' + re.escape(alias.lower()) + r'(?![a-z0-9])',
                     text.lower()) is not None


# ── Stage 1: scope ──────────────────────────────────────────────────────────

def zone_lines(jd_text: str) -> tuple[list[tuple[str, str]], bool]:
    """
    Label every line REQUIREMENT / NEUTRAL / EXCLUDED. Returns (lines, saw_req).

    career-ops' jd-skill-gap does this as a binary keep/drop, which is right for
    their purpose (report gaps, no scoring). Measured against our own 163-row
    batch, binary scoping halved the denominator — median 4 vocabulary hits per
    JD down to 2 — because real postings name half their tooling under
    Responsibilities, not under Qualifications. A 2-term denominator makes
    coverage meaningless: 13 rows scored a trivial 100% off one or two terms.

    So: three zones, not two. EXCLUDED still hard-drops the actual hazard
    (benefits, EEO, legal, physical demands — the blocks that turn "401k" and
    "Carrot" into skill gaps). NEUTRAL keeps responsibilities prose but weights
    it as preferred rather than required. Only REQUIREMENT can carry full weight.
    """
    lines = jd_text.split("\n")
    out: list[tuple[str, str]] = []
    zone = "NEUTRAL"
    saw_req = False

    for line in lines:
        # Checked first so a heading matching both (e.g. "Why this role") closes.
        if NON_REQUIREMENT_HEADER_RE.match(line):
            zone = "EXCLUDED" if _is_hard_excluded(line) else "NEUTRAL"
            continue
        if REQUIREMENT_HEADER_RE.match(line):
            zone = "REQUIREMENT"
            saw_req = True
            continue
        out.append((line, zone))

    return out, saw_req


# Headers whose contents must never contribute a keyword at any weight. A
# responsibilities block is merely lower-signal; a benefits block is poison.
_HARD_EXCLUDE_RE = re.compile(
    r'(?i)^\s*#{0,6}\s*\**\s*(?:benefits?|perks?|compensation|salary|pay\s+range|'
    r'total\s+rewards|what\s+we\s+offer|equal\s+(?:opportunity|employment)|eeo|'
    r'diversity|accommodation|physical\s+(?:demands|requirements)|work\s+environment|'
    r'how\s+to\s+apply|to\s+apply|application\s+process|interview\s+process|'
    r'disclaimer|legal|privacy|about\s+(?:us|the\s+company|our))\b')


def _is_hard_excluded(line: str) -> bool:
    return bool(_HARD_EXCLUDE_RE.match(line))


# ── Stage 2+3: extract and weight ───────────────────────────────────────────

def extract_keywords(jd_text: str, tax: Taxonomy) -> tuple[list[dict], dict]:
    """
    Pull canonical vocabulary terms out of the requirement blocks.

    Each term appears at most once no matter how often the JD repeats it — a
    posting that says SPC ten times is asking for SPC once.
    """
    zoned, saw_section = zone_lines(jd_text)
    found: dict[str, dict] = {}

    for line, zone in zoned:
        if zone == "EXCLUDED" or not line.strip():
            continue
        required_cue = bool(REQUIRED_CUE_RE.search(line))
        preferred_cue = bool(PREFERRED_CUE_RE.search(line))

        if zone == "REQUIREMENT":
            # An explicit "required" wins even inside a Preferred block, and an
            # explicit "preferred" demotes even inside a Required block — the
            # sentence is a stronger signal than the heading it sits under.
            if required_cue:
                weight, why = WEIGHT_REQUIRED, "required (stated in line)"
            elif preferred_cue:
                weight, why = WEIGHT_PREFERRED, "preferred (stated in line)"
            else:
                weight, why = WEIGHT_REQUIRED, "required (in a requirements block)"
        else:
            # Responsibilities and unheaded prose: real signal, but the posting
            # never called it a requirement, so it cannot carry required weight.
            weight = WEIGHT_REQUIRED if required_cue else WEIGHT_PREFERRED
            why = "required (stated in line)" if required_cue else "mentioned (responsibilities/prose)"

        for alias, term in tax._alias_index:
            if not term_in_text(alias, line):
                continue
            canon = term["canonical"]
            prev = found.get(canon)
            if prev is None or weight > prev["weight"]:
                found[canon] = {"canonical": canon, "weight": weight,
                                "weight_reason": why, "matched_alias": alias,
                                "zone": zone}

    ordered = sorted(found.values(), key=lambda k: (-k["weight"], k["canonical"]))
    return ordered[:MAX_KEYWORDS], {
        "saw_requirement_section": saw_section,
        "extracted_before_cap": len(found),
    }


# ── Stage 4: classify ───────────────────────────────────────────────────────

def classify(keyword: dict, tax: Taxonomy) -> dict:
    """Attach tier, credit, and the evidence (or the lack of it) to one keyword."""
    term = tax.by_canonical[keyword["canonical"]]
    status = term["status"]
    out = dict(keyword)
    out["family"] = term["family"]
    out["resume_safe"] = term.get("resume_safe") or term["canonical"]

    if status == "proven":
        out.update(tier="PROVEN", evidence=term["evidence"])
    elif status == "evidenced":
        out.update(tier="EVIDENCED", evidence=term["evidence"])
    elif term["family"] in tax.reachable_families:
        anchors = tax.anchors_for(term["family"])
        out.update(tier="ADJACENT", evidence=[],
                   adjacent_to=anchors,
                   adjacency_note=f"same family as {', '.join(anchors[:3])} — defensible, not identical")
    else:
        out.update(tier="GAP", evidence=[])

    out["credit"] = CREDIT[out["tier"]]
    return out


# ── Stage 5: coverage ───────────────────────────────────────────────────────

def analyse(jd_text: str, tax: Taxonomy | None = None) -> dict:
    """
    Full per-JD keyword report. This is the ranker's Coverage axis input and the
    customiser's claim boundary.

    `coverage` is None — never 0.0 and never 1.0 — when nothing could be
    extracted. A check that did not run must not read as a clean pass; that
    distinction is the whole point of `extraction`.
    """
    tax = tax or Taxonomy.load()
    raw, meta = extract_keywords(jd_text or "", tax)
    keywords = [classify(k, tax) for k in raw]

    if not (jd_text or "").strip():
        extraction = "EMPTY_JD"
    elif not keywords:
        extraction = "NONE"
    elif len(keywords) < MIN_CONFIDENT_KEYWORDS:
        # A denominator of one or two terms makes 100% meaningless. On the
        # 2026-09-09 batch, 13 rows scored a trivial 100% off one or two hits.
        extraction = "THIN"
    elif not meta["saw_requirement_section"]:
        extraction = "UNSCOPED"
    else:
        extraction = "OK"

    buckets = {tier: [k["canonical"] for k in keywords if k["tier"] == tier]
               for tier in ("PROVEN", "EVIDENCED", "ADJACENT", "GAP")}

    weighted_total = sum(k["weight"] for k in keywords)
    weighted_credit = sum(k["weight"] * k["credit"] for k in keywords)
    coverage = (weighted_credit / weighted_total) if weighted_total else None

    required = [k for k in keywords if k["weight"] == WEIGHT_REQUIRED]
    required_met = [k for k in required if k["credit"] >= 1.0]

    return {
        "taxonomy_version": tax.version,
        "extraction": extraction,
        "extraction_note": _diagnose(extraction),
        "keywords": keywords,
        "keyword_total": len(keywords),
        "counts": {t: len(v) for t, v in buckets.items()},
        "buckets": buckets,
        "coverage": round(coverage, 4) if coverage is not None else None,
        "coverage_percent": round(coverage * 100) if coverage is not None else None,
        "required_total": len(required),
        "required_met": len(required_met),
        "required_gaps": [k["canonical"] for k in required if k["credit"] < 1.0],
        "claimable": [k["resume_safe"] for k in keywords if k["tier"] in ("PROVEN", "EVIDENCED")],
        "not_claimable": [k["canonical"] for k in keywords if k["tier"] == "GAP"],
    }


def _diagnose(extraction: str) -> str:
    return {
        "OK": "",
        "THIN": f"Fewer than {MIN_CONFIDENT_KEYWORDS} vocabulary terms matched. The percentage is real but the denominator is too small to rank on — treat as low confidence.",
        "EMPTY_JD": "No JD text. Nothing was checked — this is not 'no gaps'. P1_06 §9: confidence low, cannot clear a gate.",
        "NONE": "A requirements section was scanned but no vocabulary term matched. Nothing was classified; read the JD before trusting this row.",
        "UNSCOPED": "No requirements section recognized, so the whole posting was scanned. Keywords may include responsibilities rather than requirements.",
    }[extraction]


# ── Taxonomy drift audit ────────────────────────────────────────────────────

def run_audit() -> int:
    """
    Every proven/evidenced claim must carry evidence, and every gap must not.
    Cheaper than a seeder and catches the failure a seeder cannot: the catalog
    drifting away from the resume it claims to describe.
    """
    tax = Taxonomy.load()
    problems = []
    for t in tax.terms:
        if t["status"] in ("proven", "evidenced") and not t.get("evidence"):
            problems.append(f"{t['canonical']}: status={t['status']} but no evidence")
        if t["status"] == "gap" and t.get("evidence"):
            problems.append(f"{t['canonical']}: status=gap but carries evidence — promote or clear it")
        if t["family"] not in tax.families:
            problems.append(f"{t['canonical']}: unknown family '{t['family']}'")
        for alias in t["aliases"]:
            if alias != alias.lower():
                problems.append(f"{t['canonical']}: alias '{alias}' must be lowercase")

    counts = {}
    for t in tax.terms:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    print(f"taxonomy v{tax.version}: {len(tax.terms)} terms  {counts}")
    print(f"families with claimable evidence: {len(tax.reachable_families)}/{len(tax.families)}")
    unreachable = sorted(set(tax.families) - tax.reachable_families)
    if unreachable:
        print(f"no-credit families (every term a hard gap): {', '.join(unreachable)}")
    for p in problems:
        print(f"  PROBLEM  {p}")
    print("AUDIT OK" if not problems else f"{len(problems)} PROBLEM(S)")
    return 1 if problems else 0


# ── Self-test ───────────────────────────────────────────────────────────────

TEST_TAXONOMY = ROOT_DIR / "tests" / "fixtures" / "taxonomy_test.json"


def run_self_test() -> int:
    # The synthetic fixture, never the user's real catalog: the assertions below
    # encode a fixed evidence graph, and CI has no personal taxonomy at all.
    tax = Taxonomy.load(TEST_TAXONOMY)
    failures = []

    def check(name, actual, expected):
        ok = actual == expected
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        expected {expected!r}\n        got      {actual!r}")
            failures.append(name)

    print("word boundaries")
    check("'nde' does not match 'intended'", term_in_text("nde", "the intended process"), False)
    check("'gd&t' matches across the ampersand", term_in_text("gd&t", "read GD&T callouts"), True)
    check("'8d' matches a digit-leading term", term_in_text("8d", "ran an 8D"), True)

    print("\nno inflation from repetition")
    spc = (ROOT_DIR / "tests/fixtures/spc_repeated.txt").read_text(encoding="utf-8")
    r = analyse(spc, tax)
    check("SPC x10 counts once", r["buckets"]["PROVEN"].count("SPC"), 1)
    check("PFMEA picked up as required", "PFMEA" in r["buckets"]["PROVEN"], True)
    check("APQP is not claimable", "APQP" in r["not_claimable"] or "APQP" in r["buckets"]["ADJACENT"], True)

    print("\nbenefits and EEO never become requirements")
    ben = (ROOT_DIR / "tests/fixtures/benefits_only.txt").read_text(encoding="utf-8")
    rb = analyse(ben, tax)
    check("benefits-only JD extracts nothing", rb["keyword_total"], 0)
    check("...and coverage is None, NOT 100%", rb["coverage"], None)
    check("...and it says the check did not run", rb["extraction"], "NONE")
    check("empty JD is EMPTY_JD, not 100%", analyse("", tax)["coverage"], None)

    print("\nevidence discipline")
    aero = (ROOT_DIR / "tests/fixtures/sponsor_friendly.txt").read_text(encoding="utf-8")
    ra = analyse(aero, tax)
    for term in ("PFMEA", "GD&T", "CMM", "8D", "Control Plan"):
        check(f"{term} is claimable on the aero fixture", term in ra["claimable"] or
              term in ra["buckets"]["PROVEN"] or term in ra["buckets"]["EVIDENCED"], True)
    check("Cp/Cpk is ADJACENT, not proven",
          classify({"canonical": "Cp/Cpk", "weight": 2}, tax)["tier"], "ADJACENT")
    check("APQP is ADJACENT via core_tools (Control Plan is proven)",
          classify({"canonical": "APQP", "weight": 2}, tax)["tier"], "ADJACENT")
    check("SAP is a hard GAP (no claimable term in erp)",
          classify({"canonical": "SAP", "weight": 2}, tax)["tier"], "GAP")
    check("Battery cell mfg is a hard GAP",
          classify({"canonical": "Battery Cell Manufacturing", "weight": 2}, tax)["tier"], "GAP")
    # DOE earns half credit via the Six Sigma Green Belt curriculum, not via the
    # vulcan-doe planning doc (which P1_03 forbids listing). Adjacent, not proven.
    check("DOE is ADJACENT, never PROVEN",
          classify({"canonical": "DOE", "weight": 2}, tax)["tier"], "ADJACENT")
    # Weak adjacencies that a machining background does NOT license.
    check("Welding is a hard GAP, not adjacent to CNC",
          classify({"canonical": "Welding", "weight": 2}, tax)["tier"], "GAP")
    check("Additive Manufacturing is a hard GAP",
          classify({"canonical": "Additive Manufacturing", "weight": 2}, tax)["tier"], "GAP")

    print("\ncoverage arithmetic")
    check("adjacent earns half credit", CREDIT["ADJACENT"], 0.5)
    check("required outweighs preferred 2:1", WEIGHT_REQUIRED / WEIGHT_PREFERRED, 2.0)
    check("aero fixture coverage is a real percentage",
          isinstance(ra["coverage_percent"], int) and 0 < ra["coverage_percent"] <= 100, True)
    check("cap holds at 15", analyse(spc + aero, tax)["keyword_total"] <= MAX_KEYWORDS, True)

    print("\nreal postings")
    mic_path = ROOT_DIR / "tests/fixtures/micron_ncg.txt"
    if mic_path.exists():
        rm = analyse(mic_path.read_text(encoding="utf-8"), tax)
        check("Micron NCG extracts something", rm["keyword_total"] > 0, True)
        print(f"        [info] Micron: {rm['keyword_total']} kw, {rm['coverage_percent']}% "
              f"({rm['counts']}), extraction={rm['extraction']}")
    else:
        print("  SKIP  micron_ncg (real-posting fixture stays local; not in this checkout)")

    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILURE(S): ' + ', '.join(failures)}")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return run_self_test()
    if "--audit" in argv:
        return run_audit()
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 0
    for p in paths:
        report = analyse(Path(p).read_text(encoding="utf-8"))
        print(f"\n=== {p} ===")
        print(f"extraction: {report['extraction']}  {report['extraction_note']}")
        print(f"coverage:   {report['coverage_percent']}%  "
              f"({report['keyword_total']} kw: {report['counts']})")
        print(f"required:   {report['required_met']}/{report['required_total']} met"
              + (f"  gaps: {', '.join(report['required_gaps'])}" if report["required_gaps"] else ""))
        for k in report["keywords"]:
            note = k.get("adjacency_note", "")
            print(f"  [{k['tier']:<9}] w{k['weight']} {k['canonical']:<28} {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
