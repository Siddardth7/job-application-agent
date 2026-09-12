"""Seen-job ledger: one loader shared by the fetcher and the ranker.

Both tools used to carry their own ~80-line copy and they had drifted (the
ranker checked normalized fingerprints, the fetcher did not). This is the one
copy. Keys a posting can be recognised by, strongest first:

  req_id       the employer's requisition number (JR-202618826, REF295329K,
               Greenhouse/LinkedIn numeric ids). The only key that separates two
               postings with the same company, title and city.
  url          cleaned link (query string and trailing slash removed)
  job_id       8-12 digit id found in the URL (LinkedIn, Greenhouse, SmartRecruiters)
  fingerprint  company|title, raw and normalized (suffixes, shifts, levels stripped)

seen_jobs.csv layouts accepted (header row is skipped, cells are sniffed):
  first_seen_date,market,company,title_normalized,city,job_url,fingerprint,status[,req_id]
  company,title,location,url,date,status                       (legacy writer)
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SEEN_JOBS_CSV = ROOT_DIR / "seen_jobs.csv"

_LEGAL = r'\b(inc|incorporated|corp|corporation|llc|ltd|limited|co|company|technologies|solutions|group|americas|europe|healthcare|north america|gmbh|sa|bv|nv|srl)\b'
_LEVELS = r'\b(i|ii|iii|iv|v|1|2|3|4|5|e1|e2|e3|e4|associate|junior|senior|sr|lead|entry\s*level|new\s*college\s*grad|ncg)\b'

# Requisition ids as employers print them, in the URL or the posting text.
_REQ_IN_URL = [
    re.compile(r'_((?:JR|R|REQ)-?\d{4,})(?:[/?#]|$)', re.I),          # Workday ..._JR-202618826
    re.compile(r'/postings/(\d{6,})'),                                  # SmartRecruiters
    re.compile(r'/jobs/(\d{6,})'),                                      # Greenhouse
    re.compile(r'/jobs/view/(?:[^/]*-)?(\d{8,12})'),                    # LinkedIn
    re.compile(r'[?&](?:jobId|job_id|req(?:uisition)?Id|jobReqId)=([A-Z0-9-]{4,})', re.I),
]
_REQ_IN_TEXT = re.compile(
    r'(?i)\b(?:req(?:uisition)?\.?\s*(?:id|#|no\.?|number)?|job\s*(?:id|#|number|code)|'
    r'posting\s*(?:id|number)|reference\s*(?:id|number|no\.?|code)?|ref\.?\s*(?:no\.?|#)?)'
    r'\s*[:#\-]?\s*([A-Z]{0,6}[-_ ]?\d{3,}[A-Z0-9-]*)\b')


def normalize_company(name: str) -> str:
    if not name:
        return ""
    return re.sub(r'[^a-z0-9]', '', re.sub(_LEGAL, '', name.lower()))


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r'\b(1st|2nd|3rd|first|second|third|night)\s*shift\b', '', t)
    t = re.sub(_LEVELS, '', t)
    t = re.sub(r'\(.*?\)|\[.*?\]', '', t)
    return re.sub(r'[^a-z0-9]', '', t)


def clean_url(url: str) -> str:
    return (url or "").strip().split("?")[0].rstrip("/")


def job_id_from_url(url: str) -> str | None:
    m = re.search(r'(\d{8,12})', clean_url(url))
    return m.group(1) if m else None


def extract_req_id(url: str, text: str = "") -> str:
    """Employer requisition id from the URL first, then the posting text. '' if none."""
    for pat in _REQ_IN_URL:
        m = pat.search(url or "")
        if m:
            return m.group(1).upper()
    m = _REQ_IN_TEXT.search(text or "")
    return m.group(1).upper().replace(" ", "") if m else ""


def fingerprints(company: str, title: str) -> tuple[str, str]:
    """(raw, normalized) company|title keys."""
    raw = f"{re.sub(r'[^a-z0-9]', '', (company or '').lower())}|{re.sub(r'[^a-z0-9]', '', (title or '').lower())}"
    return raw, f"{normalize_company(company)}|{normalize_title(title)}"


def load_env() -> None:
    """Load .env into os.environ without overriding what is already set."""
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


class Seen:
    """Everything the ledger and the applications table already know about."""

    def __init__(self):
        self.urls: set[str] = set()
        self.job_ids: set[str] = set()
        self.fps: set[str] = set()
        self.req_ids: set[str] = set()

    def add(self, company: str = "", title: str = "", url: str = "", req_id: str = "") -> None:
        u = clean_url(url)
        if u:
            self.urls.add(u)
            jid = job_id_from_url(u)
            if jid:
                self.job_ids.add(jid)
            rid = extract_req_id(u)
            if rid:
                self.req_ids.add(rid)
        if company and title:
            self.fps.update(fingerprints(company, title))
        if req_id:
            self.req_ids.add(req_id.upper())

    def match(self, job: dict) -> str:
        """Why this job is already seen, or '' if it is new."""
        url = clean_url(job.get("link") or job.get("apply_url") or "")
        rid = (job.get("req_id") or "").upper()
        if rid and rid in self.req_ids:
            return f"requisition id {rid} already in ledger"
        if url and url in self.urls:
            return "URL already in ledger"
        jid = job_id_from_url(url)
        if jid and jid in self.job_ids:
            return f"job id {jid} already in ledger"
        raw, norm = fingerprints(job.get("company", ""), job.get("title", ""))
        if raw in self.fps or norm in self.fps:
            return "company + title already in ledger"
        return ""

    def __len__(self) -> int:
        return len(self.urls) + len(self.req_ids) + len(self.fps)


def load_seen(csv_path: Path = SEEN_JOBS_CSV, supabase: bool = True) -> Seen:
    seen = Seen()
    if csv_path.exists():
        try:
            with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                header = next(reader, None) or []
                req_col = header.index("req_id") if "req_id" in header else None
                for row in reader:
                    if not row:
                        continue
                    url = next((c for c in row if c.startswith("http")), "")
                    if row[0][:4].isdigit() and len(row) >= 4:      # dated layout
                        co, title = row[2], row[3]
                    elif len(row) >= 2:                              # legacy layout
                        co, title = row[0], row[1]
                    else:
                        co = title = ""
                    rid = row[req_col] if req_col is not None and len(row) > req_col else ""
                    seen.add(co, title, url, rid)
                    if len(row) >= 7 and row[6] and "|" in row[6]:
                        seen.fps.add(re.sub(r'[^a-z0-9|]', '', row[6].lower()))
        except Exception as e:
            print(f"Warning reading {csv_path.name}: {e}", file=sys.stderr)

    load_env()
    supa_url = os.environ.get("SUPABASE_URL", "")
    supa_key = os.environ.get("SUPABASE_KEY", "")
    if supabase and supa_url and supa_key:
        try:
            req = urllib.request.Request(
                f"{supa_url}/rest/v1/applications?select=company,role,job_url",
                headers={"apikey": supa_key, "Authorization": f"Bearer {supa_key}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                for app in json.loads(resp.read().decode("utf-8")):
                    seen.add(app.get("company") or "", app.get("role") or "", app.get("job_url") or "")
        except Exception as e:
            print(f"Warning syncing seen ledger from Supabase: {e}", file=sys.stderr)
    return seen


def demo() -> None:
    assert extract_req_id("https://x.wd5.myworkdayjobs.com/S/job/City/Title_JR-202618826") == "JR-202618826"
    assert extract_req_id("https://jobs.smartrecruiters.com/Co/postings/744000147328139") == "744000147328139"
    assert extract_req_id("https://www.linkedin.com/jobs/view/4457062363") == "4457062363"
    assert extract_req_id("https://acme.com/careers/apply", "Requisition ID: R0012345 Location: Austin") == "R0012345"
    assert extract_req_id("https://acme.com/careers/apply", "no id here") == ""
    s = Seen()
    s.add("Acme Inc.", "Quality Engineer II", "https://a.com/jobs/12345678?src=x", "R-1")
    assert s.match({"company": "Acme", "title": "Quality Engineer I", "link": "https://z"}) != ""   # normalized fp
    assert s.match({"company": "Other", "title": "X", "link": "https://q", "req_id": "r-1"}) != ""      # req id
    assert s.match({"company": "Other", "title": "X", "link": "https://a.com/jobs/12345678"}) != ""   # job id
    assert s.match({"company": "New Co", "title": "Process Engineer", "link": "https://n"}) == ""
    print("OK  ledger self-check passed")


if __name__ == "__main__":
    demo()
