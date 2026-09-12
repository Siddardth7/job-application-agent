#!/usr/bin/env python3
"""
fetch_jobs.py — Stage 1 of the daily run. Every posting the ranker will see comes
from here, and nothing is carried over from a previous run: each batch is what the
six passes found today.

  Pass 0  your hand-found postings      --jds=DIR (Markdown files) and/or --urls=FILE / --url=...
  Pass 1  company career sites (free)   node tools/ats_scan.mjs over tools/portals.json, 3 days
  Pass 2  LinkedIn, target companies    anchors x role titles, 3 days
  Pass 3  LinkedIn, all domains         every domain company x role titles, 24 hours
  Pass 4  LinkedIn, non-full-time       contract / temporary / internship / co-op / technician, 24 hours
  Pass 5  LinkedIn, international       role + adjacent titles per configured country, 3 days

Windows and Apify spend caps live in config/search_profile.json under
search.pass_days and search.apify_pass_caps (defaults below).

Every pass reports raw rows, kept rows, cap, and — if it failed — why. That table is
written to .pipeline/fetched.md and .pipeline/fetch_report.json so the ranker and the
user can see how the fetch actually went, not just what survived.

The fetcher never writes seen_jobs.csv. The ranker records dropped rows there; the
Stage 4 logger records applied rows.

Usage:
  python3 tools/fetch_jobs.py                       # all passes
  python3 tools/fetch_jobs.py --pass=1,2            # some passes
  python3 tools/fetch_jobs.py --ats-only            # no Apify spend (passes 2-5 skipped)
  python3 tools/fetch_jobs.py --jds=JDs/09-12 --url=https://www.linkedin.com/jobs/view/123
  python3 tools/fetch_jobs.py --dry-run             # offline, from tests/fixtures/fetch_sample.json
  python3 tools/fetch_jobs.py --self-test
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.profile_config import (load_config, classify_domain, peer_role_keyword,  # noqa: E402
                                linkedin_query, search_terms, _or)
from lib import ledger  # noqa: E402

CONFIG = load_config()
ROOT_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT_DIR / ".pipeline"
PORTALS_JSON = ROOT_DIR / "tools" / "portals.json"
if not PORTALS_JSON.exists():  # pre-setup fallback; /setup writes the user's own
    PORTALS_JSON = ROOT_DIR / "tools" / "portals.example.json"
ATS_SCAN_MJS = ROOT_DIR / "tools" / "ats_scan.mjs"
FIXTURE = ROOT_DIR / "tests" / "fixtures" / "fetch_sample.json"

ACTOR_ID = "curious_coder~linkedin-jobs-scraper"
UA = "Mozilla/5.0 (compatible; JobSearchPipeline/1.0)"

PASS_LABELS = {
    0: "Pass 0: your hand-found postings",
    1: "Pass 1: company career sites (ATS, free)",
    2: "Pass 2: LinkedIn, target companies",
    3: "Pass 3: LinkedIn, all domains",
    4: "Pass 4: LinkedIn, contract / technician / intern / co-op",
    5: "Pass 5: LinkedIn, international",
}
_DEFAULT_CAPS = {2: 0.12, 3: 0.12, 4: 0.10, 5: 0.12}
_DEFAULT_DAYS = {1: 3, 2: 3, 3: 1, 4: 1, 5: 3}
REPOST_AGE_DAYS = 14
NEEDS_JD_MAX = 10


def pass_cap(n: int) -> float:
    caps = (CONFIG.get("search") or {}).get("apify_pass_caps") or {}
    return float(caps.get(str(n), _DEFAULT_CAPS.get(n, 0.10)))


def pass_days(n: int) -> int:
    days = (CONFIG.get("search") or {}).get("pass_days") or {}
    return int(days.get(str(n), _DEFAULT_DAYS.get(n, 3)))


# ── Location ────────────────────────────────────────────────────────────────

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
    "new england", "puerto rico",   # regions LinkedIn uses as locations
]
_US_RE = re.compile(
    r'(?<![a-z])(?:united states(?: of america)?|usa|u\.s\.a?\.?|' + "|".join(US_STATES) + r')(?![a-z])'
    r'|,\s*[A-Z]{2}(?:\s|$|,)'      # "Indianapolis, IN"
)


def is_us_location(location: str) -> bool:
    return bool(_US_RE.search(location.lower())) or bool(re.search(r',\s*[A-Z]{2}(?:\s*,|\s*$)', location))


def is_geo_blocked(location: str) -> bool:
    """
    True when the location names a blocked country. Word-bounded (audit F1: the
    old substring test blocked Indianapolis via "india" and New England via
    "england") and a US location is never blocked, whatever else the string says.
    """
    if not location:
        return False
    if is_us_location(location):
        return False
    loc = location.lower()
    for country in CONFIG["search"]["blocked_locations"]:
        if re.search(r'(?<![a-z])' + re.escape(country.lower()) + r'(?![a-z])', loc):
            return True
    return False


# ── Sources ─────────────────────────────────────────────────────────────────

def run_ats_scan(skip_companies: list[str]) -> tuple[list[dict], str, list[str]]:
    """Run tools/ats_scan.mjs. Returns (rows, error, portals_skipped)."""
    cfg = json.loads(PORTALS_JSON.read_text(encoding="utf-8"))
    skipped = [p["name"] for p in cfg.get("portals", [])
               if any(k in p.get("name", "").lower() for k in skip_companies)]
    if skipped:
        cfg["portals"] = [p for p in cfg["portals"] if p["name"] not in skipped]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(cfg, tmp)
        tmp_path = tmp.name
    try:
        res = subprocess.run(["node", str(ATS_SCAN_MJS), tmp_path, "--since-days", str(pass_days(1))],
                             cwd=str(ROOT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, timeout=300)
        if res.returncode != 0:
            return [], f"ats_scan exited {res.returncode}: {res.stderr.strip()[-300:]}", skipped
        return json.loads(res.stdout), "", skipped
    except Exception as e:
        return [], f"ats_scan exception: {e}", skipped
    finally:
        os.unlink(tmp_path)


def run_apify(urls: list[str], cap_usd: float, per_url: int, token: str) -> tuple[list[dict], str]:
    """One Apify run for a pass. Returns (rows, error). Never raises."""
    if not token:
        return [], "no APIFY_TOKEN in .env"
    if not urls:
        return [], "no search URLs built from config"
    body = {"urls": urls, "limitPerSource": per_url, "scrapeCompany": False, "autoConvertToAiSearch": True}
    q = urllib.parse.urlencode({
        "token": token, "maxTotalChargeUsd": f"{cap_usd:.2f}",
        "fields": "title,companyName,location,postedAt,seniorityLevel,link,applyUrl,companyWebsite,descriptionText",
    })
    req = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items?{q}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except Exception as e:
        return [], f"Apify call failed: {e}"


def apify_last_run_usd(token: str) -> float | None:
    """Dollars Apify actually charged for the actor's most recent run (the one
    run_apify just finished). The sync endpoint returns only dataset items, so
    this is a second, free GET. None if it cannot be read — never raises."""
    if not token:
        return None
    try:
        req = urllib.request.Request(f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs/last?token={token}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data") or {}
        return round(float(data.get("usageTotalUsd")), 4) if data.get("usageTotalUsd") is not None else None
    except Exception:
        return None


def fetch_linkedin_guest(url: str) -> dict | None:
    """A single pasted LinkedIn job URL via the public guest endpoint (no login)."""
    jid = ledger.job_id_from_url(url)
    if not jid:
        return None
    try:
        req = urllib.request.Request(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    def grab(pat):
        m = re.search(pat, page, re.S)
        return html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ""

    desc = grab(r'show-more-less-html__markup[^>]*>(.*?)</div>')
    return {
        "title": grab(r'<h2[^>]*top-card-layout__title[^>]*>(.*?)</h2>'),
        "companyName": grab(r'topcard__org-name-link[^>]*>(.*?)</a>'),
        "location": grab(r'topcard__flavor--bullet[^>]*>(.*?)</span>'),
        "link": f"https://www.linkedin.com/jobs/view/{jid}",
        "applyUrl": url,
        "postedAt": "",
        "descriptionText": desc,
    }


def load_user_jds(jd_dir: Path | None) -> list[dict]:
    """Markdown JDs the user saved. Company/title/location/link come from the file, never a hard-coded list."""
    if jd_dir is None:
        today = datetime.now()
        for name in (today.strftime("%m:%d"), today.strftime("%m-%d"), today.strftime("%Y-%m-%d")):
            if (ROOT_DIR / "JDs" / name).is_dir():
                jd_dir = ROOT_DIR / "JDs" / name
                break
    if jd_dir is None or not jd_dir.is_dir():
        return []
    rows = []
    for f in sorted(jd_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="ignore")

        def field(name):
            m = re.search(r'\*\*' + name + r':\*\*\s*(.+)', text, re.I) or re.search(r'^' + name + r':\s*(.+)$', text, re.I | re.M)
            return m.group(1).strip().strip('*') if m else ""

        title = field("Title") or (re.search(r'^#\s+(.+)$', text, re.M) or [None, ""])[1] or f.stem
        company = field("Company")
        if not company and " - " in f.stem:
            company = f.stem.split(" - ")[0].strip()
        link_m = re.search(r'\*\*Source:\*\*\s*\[.*?\]\((.*?)\)', text) or re.search(r'https?://\S+', text)
        rows.append({
            "title": title.strip(), "companyName": company or "Unknown (from JD file)",
            "location": field("Location") or "", "link": link_m.group(1) if link_m else "",
            "applyUrl": link_m.group(1) if link_m else "", "postedAt": datetime.now().strftime("%Y-%m-%d"),
            "descriptionText": text,
        })
    return rows


# ── Normalisation ───────────────────────────────────────────────────────────

def classify_job_freshness(posted_at: str, description: str = "") -> tuple[str, str, str]:
    """
    FRESH unless the posting says it is a repost or is older than REPOST_AGE_DAYS.
    Every pass already filters by date at the source, so the old hard-coded
    LinkedIn ID cutoff (audit F3) is gone: it needed a monthly edit and dropped
    rows silently when it went stale.
    """
    if re.search(r'(?i)\bre-?posted\b|\[repost\]', description):
        return "REPOSTED", "🔄 REPOSTED", "Reposted (tagged in posting text)"
    if posted_at:
        try:
            age = (datetime.now() - datetime.strptime(posted_at[:10], "%Y-%m-%d")).days
            if age > REPOST_AGE_DAYS:
                return "REPOSTED", "🔄 REPOSTED", f"Standing opening ({age}d old, posted {posted_at[:10]})"
            return "FRESH", "🟢 FRESH", f"Posted {posted_at[:10]} ({age}d ago)"
        except ValueError:
            pass
    return "FRESH", "🟢 FRESH", "Fresh opening"


def people_links(company: str, title: str) -> tuple[str, str]:
    base = "https://www.linkedin.com/search/results/people/?origin=GLOBAL_SEARCH_HEADER&keywords="
    recruiter = base + urllib.parse.quote_plus(f'"{company.strip()}" recruiter OR "talent acquisition"')
    peer = base + urllib.parse.quote_plus(f'"{company.strip()}" {peer_role_keyword(title)}')
    return recruiter, peer


def normalize_job(item: dict, source_type: str, pass_num: int) -> dict:
    g = lambda *keys: next((str(item[k]).strip() for k in keys if item.get(k)), "")  # noqa: E731
    title, company = g("title"), g("companyName", "company")
    link = g("link", "applyUrl")
    description = g("descriptionText", "description")
    posted_at = g("postedAt")
    fresh, badge, detail = classify_job_freshness(posted_at, description)
    recruiter_url, peer_url = people_links(company, title)
    return {
        "title": title, "company": company, "location": g("location"),
        "link": link, "apply_url": g("applyUrl") or link, "posted_at": posted_at,
        "description": description, "needs_jd": not description,
        "req_id": g("reqId", "req_id") or ledger.extract_req_id(link, description),
        "seniority_level": g("seniorityLevel"),
        "track": classify_domain(company, title),
        "source": source_type, "pass": f"Pass {pass_num}", "pass_num": pass_num,
        "recruiter_url": recruiter_url, "peer_url": peer_url,
        "freshness": fresh, "freshness_badge": badge, "freshness_detail": detail,
        "mass_posted_locations": [],
    }


# ── Filter + dedup (pure, so the self-test can exercise it) ─────────────────

def process_batch(raw_jobs: list[dict], seen: ledger.Seen) -> tuple[list[dict], dict]:
    survivors: dict[str, dict] = {}
    urls_in_run: set[str] = set()
    reqs_in_run: set[str] = set()
    drops = {"no_title_or_company": 0, "reposted": 0, "geo_blocked": 0, "already_seen": 0,
             "duplicate_in_run": 0, "merged_same_company_title": 0}
    for job in raw_jobs:
        if not job.get("title") or not job.get("company"):
            drops["no_title_or_company"] += 1
            continue
        if job.get("freshness") == "REPOSTED":
            drops["reposted"] += 1
            continue
        if is_geo_blocked(job.get("location", "")) and not job.get("source", "").endswith("intl"):
            drops["geo_blocked"] += 1
            continue
        why = seen.match(job) if job.get("pass_num") != 0 else ""
        if why:
            drops["already_seen"] += 1
            continue
        url = ledger.clean_url(job.get("link") or job.get("apply_url") or "")
        rid = job.get("req_id", "")
        if (url and url in urls_in_run) or (rid and rid in reqs_in_run):
            drops["duplicate_in_run"] += 1
            continue
        if url:
            urls_in_run.add(url)
        if rid:
            reqs_in_run.add(rid)
        sig = ledger.fingerprints(job["company"], job["title"])[0]
        if sig in survivors:
            first = survivors[sig]
            if job.get("location") and job["location"] != first.get("location"):
                first["mass_posted_locations"].append(job["location"])
            if not first.get("description") and job.get("description"):   # keep the copy that has a JD
                first["description"], first["needs_jd"] = job["description"], False
            drops["merged_same_company_title"] += 1
            continue
        survivors[sig] = job
    out = list(survivors.values())
    for job in out:
        if job["mass_posted_locations"]:
            job["location"] = f"{job['location']} (+{len(job['mass_posted_locations'])} cities)"
    return out, drops


def pick_needs_jd(survivors: list[dict]) -> list[dict]:
    """
    Rows that arrived without a description, best first, capped at NEEDS_JD_MAX.
    The ranker cannot score them; these are the ones worth asking the user to
    fetch by hand. Anchor company > title is one of the configured role titles
    > a configured domain > a US location.
    """
    st = search_terms()
    default_domain = CONFIG.get("default_domain")

    def score(j):
        co, t = j["company"].lower(), j["title"].lower()
        return (3 * any(a in co for a in st["anchors"])
                + 2 * any(re.search(r'(?<![a-z])' + re.escape(r.lower()) + r'(?![a-z])', t) for r in st["titles"])
                + (j.get("track") != default_domain) + is_us_location(j.get("location", "")))

    rows = [j for j in survivors if j.get("needs_jd")]
    rows.sort(key=score, reverse=True)
    return rows[:NEEDS_JD_MAX]


# ── Main ────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str]) -> dict:
    a = {"passes": [0, 1, 2, 3, 4, 5], "ats_only": False, "jds": None, "urls": [],
         "dry_run": "--dry-run" in argv, "self_test": "--self-test" in argv}
    for arg in argv:
        if arg.startswith("--pass=") and arg[7:] != "all":
            try:
                a["passes"] = sorted({int(x) for x in arg[7:].split(",")})
            except ValueError:
                print(f"Invalid --pass value {arg[7:]!r}; running all passes.")
        elif arg == "--ats-only":
            a["ats_only"] = True
        elif arg.startswith("--jds="):
            a["jds"] = Path(arg[6:]).expanduser()
        elif arg.startswith("--url="):
            a["urls"].append(arg[6:])
        elif arg.startswith("--urls="):
            a["urls"] += [l.strip() for l in Path(arg[7:]).read_text().splitlines() if l.strip()]
    return a


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    ledger.load_env()
    token = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_KEY", "")
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8")) if args["dry_run"] else None

    seen = ledger.load_seen(supabase=not args["dry_run"])
    print(f"Seen ledger: {len(seen.urls)} URLs, {len(seen.req_ids)} requisition ids, {len(seen.fps)} fingerprints.")

    st = search_terms()
    non_sponsors = list(CONFIG.get("known_non_sponsors", {}).keys())
    raw_jobs: list[dict] = []
    report: list[dict] = []
    skipped_portals: list[str] = []

    def record(n, status, raw, reason="", cap=None, spend=None):
        report.append({"pass": n, "label": PASS_LABELS[n], "status": status, "raw": raw,
                       "reason": reason, "cap_usd": cap, "spend_usd": spend, "days": pass_days(n) if n else None})
        spent = f", ${spend:.2f} spent" if spend is not None else ""
        print(f"  {PASS_LABELS[n]}: {status} ({raw} raw{spent}){' — ' + reason if reason else ''}")

    def apify_pass(n, urls, per_url):
        if args["ats_only"]:
            record(n, "skipped", 0, "--ats-only", pass_cap(n))
            return
        if args["dry_run"]:
            rows, err, spend = list(fixture["linkedin"]), "", None
        else:
            rows, err = run_apify(urls, pass_cap(n), per_url, token)
            spend = apify_last_run_usd(token)
        src = "linkedin_apify_intl" if n == 5 else f"linkedin_apify_p{n}"
        raw_jobs.extend(normalize_job(r, src, n) for r in rows)
        record(n, "failed" if err else "ok", len(rows), err, pass_cap(n), spend)

    for n in args["passes"]:
        if n == 0:
            rows = load_user_jds(args["jds"])
            for u in args["urls"]:
                r = fetch_linkedin_guest(u) if "linkedin.com" in u else None
                rows.append(r or {"title": "", "companyName": "", "link": u, "applyUrl": u})
            raw_jobs.extend(normalize_job(r, "manual_jd", 0) for r in rows)
            record(0, "ok" if rows else "skipped", len(rows), "" if rows else "no --jds folder or --url given")

        elif n == 1:
            if args["dry_run"]:
                rows, err, skipped_portals = list(fixture["ats"]), "", []
            else:
                rows, err, skipped_portals = run_ats_scan(non_sponsors)
            raw_jobs.extend(normalize_job(r, "ats_direct", 1) for r in rows)
            record(1, "failed" if err else "ok", len(rows), err)

        elif n == 2:
            urls = [linkedin_query(f'{_or(st["anchors"][i:i + 3])} AND {_or(st["titles"])}', days=pass_days(2))
                    for i in range(0, len(st["anchors"]), 3)]
            apify_pass(2, urls, 25)

        elif n == 3:
            urls = [linkedin_query(f'{_or(st["domain_companies"][i:i + 5])} AND {_or(st["titles"])}', days=pass_days(3))
                    for i in range(0, len(st["domain_companies"]), 5)]
            urls.append(linkedin_query(_or(st["titles"]), days=pass_days(3)))
            apify_pass(3, urls, 40)

        elif n == 4:
            titles = _or(st["titles"] + st["adjacent_titles"])
            urls = [linkedin_query(titles, days=pass_days(4), experience=None, job_type="C,T,I"),
                    linkedin_query(f'{titles} AND ("co-op" OR "intern" OR "contract")', days=pass_days(4), experience="1,2,3"),
                    linkedin_query(_or(st["adjacent_titles"]), days=pass_days(4), experience="1,2,3")]
            apify_pass(4, [u for u in urls if '("")' not in u], 40)

        elif n == 5:
            if not st["intl_locations"]:
                record(5, "skipped", 0, "no search.intl_locations configured")
                continue
            kw = _or(st["titles"] + st["adjacent_titles"])
            urls = [linkedin_query(kw, location=loc, days=pass_days(5), experience=None) for loc in st["intl_locations"]]
            apify_pass(5, urls, 40)

    survivors, drops = process_batch(raw_jobs, seen)
    kept_by_pass = {n: sum(1 for j in survivors if j["pass_num"] == n) for n in PASS_LABELS}
    for r in report:
        r["kept"] = kept_by_pass[r["pass"]]
    needs_jd = pick_needs_jd(survivors)

    (PIPELINE_DIR / "fetched.json").write_text(json.dumps(survivors, indent=2), encoding="utf-8")
    fetch_report = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args["dry_run"], "passes": report, "drops": drops,
        "raw_total": len(raw_jobs), "survivors": len(survivors),
        "portals_skipped_non_sponsor": skipped_portals,
        "needs_jd": [{"company": j["company"], "title": j["title"], "location": j["location"], "link": j["link"]} for j in needs_jd],
        "needs_jd_total": sum(1 for j in survivors if j.get("needs_jd")),
    }
    (PIPELINE_DIR / "fetch_report.json").write_text(json.dumps(fetch_report, indent=2), encoding="utf-8")
    write_fetched_md(survivors, fetch_report)

    print(f"\nFetch: {len(raw_jobs)} raw -> {len(survivors)} new postings for the ranker "
          f"({fetch_report['needs_jd_total']} without a job description).")
    print(f"Handoffs: {PIPELINE_DIR / 'fetched.json'}, fetched.md, fetch_report.json")
    return 0


def write_fetched_md(survivors: list[dict], rep: dict) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    L = [f"# Fetched Postings — {today}{' (DRY RUN)' if rep['dry_run'] else ''}\n",
         f"**{rep['raw_total']} raw rows across {len(rep['passes'])} passes → {rep['survivors']} new postings for the ranker.**\n",
         "## How each pass went\n",
         "| Pass | Status | Window | Raw | Kept | Apify spent / cap | Note |", "|---|---|---|---:|---:|---|---|"]
    for p in rep["passes"]:
        status = {"ok": "✅ ok", "failed": "❌ FAILED", "skipped": "⏭ skipped"}[p["status"]]
        cap = f"${p['cap_usd']:.2f}" if p["cap_usd"] else "free"
        if p["cap_usd"]:
            cap = (f"${p['spend_usd']:.2f} / " if p.get("spend_usd") is not None else "? / ") + cap
        L.append(f"| {p['label']} | {status} | {str(p['days']) + 'd' if p['days'] else '—'} | {p['raw']} | {p['kept']} | {cap} | {p['reason']} |")
    spent = [p["spend_usd"] for p in rep["passes"] if p.get("spend_usd") is not None]
    if spent:
        L.append(f"\n**Apify spend this run: ${sum(spent):.2f}** (read back from each run's usage; the cap is what it could not exceed).\n")
    d = rep["drops"]
    L.append(f"\nDropped before the ranker: {d['reposted']} reposted · {d['geo_blocked']} outside the US (non-international passes) · "
             f"{d['already_seen']} already in the seen ledger · {d['duplicate_in_run']} duplicate URL/requisition · "
             f"{d['merged_same_company_title']} merged into a multi-city row · {d['no_title_or_company']} unusable.\n")
    if rep["portals_skipped_non_sponsor"]:
        L.append(f"> ⚠️ **Career sites skipped** because the company is in your `known_non_sponsors` list: "
                 f"{', '.join(rep['portals_skipped_non_sponsor'])}. Remove them from `tools/portals.json` to stop seeing this.\n")
    if rep["needs_jd"]:
        L += [f"## Postings worth a job description ({len(rep['needs_jd'])} of {rep['needs_jd_total']} without one)\n",
              "The ranker cannot score a posting without its text. These look like the best of the ones that arrived blank. "
              "Paste the description into a Markdown file under `JDs/<today>/` (or give the URL back with `--url=`) and rerun pass 0.\n",
              "| Company | Title | Location | Link |", "|---|---|---|---|"]
        L += [f"| **{j['company']}** | {j['title']} | {j['location']} | [open]({j['link']}) |" for j in rep["needs_jd"]]
        L.append("")
    L += ["## New postings\n",
          "| # | Pass | Company | Title | Location | JD | Freshness | Domain | Source | Apply | Networking |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, j in enumerate(survivors, 1):
        L.append(f"| {i} | `{j['pass']}` | **{j['company']}** | {j['title']} | {j['location']} | {'—' if j['needs_jd'] else '✓'} | "
                 f"{j['freshness_badge']} | {j['track']} | `{j['source']}` | {'[Apply](' + j['link'] + ')' if j['link'] else 'N/A'} | "
                 f"[Recruiter]({j['recruiter_url']}) · [Team Lead]({j['peer_url']}) |")
    (PIPELINE_DIR / "fetched.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ── Self-test (offline) ─────────────────────────────────────────────────────

def run_self_test() -> int:
    fails = []

    def check(name, ok):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            fails.append(name)

    print("geo gate (audit F1)")
    check("Indianapolis, IN is not blocked", not is_geo_blocked("Indianapolis, IN"))
    check("Fort Wayne, Indiana is not blocked", not is_geo_blocked("Fort Wayne, Indiana"))
    check("Boston, New England is not blocked", not is_geo_blocked("Boston, New England"))
    check("Pune, India is blocked", is_geo_blocked("Pune, India"))
    check("Manchester, England is blocked", is_geo_blocked("Manchester, England"))
    check("empty location passes", not is_geo_blocked(""))

    print("\nfreshness (audit F3): dates, not LinkedIn id cutoffs")
    check("recent date is FRESH", classify_job_freshness("2099-01-01")[0] == "FRESH")
    check("old date is REPOSTED", classify_job_freshness("2020-01-01")[0] == "REPOSTED")
    check("'reposted' in text is REPOSTED", classify_job_freshness("", "This role has been reposted")[0] == "REPOSTED")
    check("no date, no text is FRESH", classify_job_freshness("")[0] == "FRESH")

    print("\nbatch processing on the fixture")
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = [normalize_job(r, "ats_direct", 1) for r in fx["ats"]] + [normalize_job(r, "linkedin_apify_p3", 3) for r in fx["linkedin"]]
    seen = ledger.Seen()
    out, drops = process_batch(raw, seen)
    names = {(j["company"], j["title"]) for j in out}
    check("Indianapolis row survives", ("Northwind Aero", "Quality Engineer I") in names)
    check("Manchester, England row dropped (geo)", ("Northwind Aero", "Supplier Quality Engineer") not in names and drops["geo_blocked"] >= 2)
    check("two Fabrikam rows merge into one with +1 cities",
          sum(1 for j in out if j["company"] == "Fabrikam Motors") == 1 and any("+1 cities" in j["location"] for j in out if j["company"] == "Fabrikam Motors"))
    check("reposted technician dropped", drops["reposted"] == 1)
    check("Contoso Process Engineer merged, JD kept from the LinkedIn copy",
          sum(1 for j in out if j["company"] == "Contoso Cells") == 1 and not next(j for j in out if j["company"] == "Contoso Cells")["needs_jd"])
    check("Workday requisition id captured", next(j for j in out if j["title"] == "Quality Engineer I")["req_id"] == "JR-100001")
    seen2 = ledger.Seen(); seen2.add(req_id="JR-100001")
    out2, drops2 = process_batch(raw, seen2)
    check("requisition id in ledger drops the row", drops2["already_seen"] == 1 and ("Northwind Aero", "Quality Engineer I") not in {(j["company"], j["title"]) for j in out2})
    check("needs-JD picks are only blank rows", all(j["needs_jd"] for j in pick_needs_jd(out)))

    print("\nargs")
    check("--pass=1,3 parses", parse_args(["--pass=1,3"])["passes"] == [1, 3])
    check("--ats-only parses", parse_args(["--ats-only"])["ats_only"])

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILURE(S): ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    sys.exit(main(sys.argv[1:]))
