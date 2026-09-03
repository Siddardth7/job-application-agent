#!/usr/bin/env python3
"""Networking handoff sheet — the Excel round trip between the apply-run and Supabase.

  export   Build networking_<date>.xlsx from the template: one block per role scoring
           above 70 (or specified roles) that is still live, pre-filled with Role / URL /
           Company / Location header and Job Posted Date. Contact rows left blank for you
           to fill after sourcing.
  import   Read a filled sheet back and upsert the contact rows into Supabase.

Usage:
  python3 networking_sheet.py export [--date YYYY-MM-DD] [--out FILE] [--template FILE]
  python3 networking_sheet.py import FILE [--dry-run]

Needs SUPABASE_KEY in the environment (refresh.sh sources .env; so does this).
"""
import argparse
import copy
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

from openpyxl import load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

import refresh  # reuses the one Supabase config + REST reader; no second copy of either

HERE = os.path.dirname(os.path.abspath(__file__))
_PRIMARY_TEMPLATE = os.path.expanduser(
    "~/Documents/Professional/JobSearch/JDs/Job_Applications - Networking Template.xlsx")
_FALLBACK_TEMPLATE = os.path.join(HERE, "daily_run", "networking_2026-08-20.xlsx")
TEMPLATE = _PRIMARY_TEMPLATE if os.path.exists(_PRIMARY_TEMPLATE) else _FALLBACK_TEMPLATE
OUT_DIR = os.path.join(HERE, "daily_run")

# The gate, decided 2026-08-22: strictly above 70, and still live. Dropped/rejected/
# expired roles are not worth spending outreach on.
MIN_SCORE = 70
DEAD_STATUSES = {"dropped", "rejected", "expired"}

# Template geometry:
# 4 header rows (Target Role, Job URL Link, Company, Location of Role)
# Table header row at top + 4
# 10 data rows from top + 5 to top + 14
# 2 spacer rows
FIRST_HEADER_ROW, STRIDE, DATA_ROWS = 5, 17, 10
COLS = ["Job Title", "Job Posted Date", "Contact Name",
        "Profile URL", "Persona", "Status", "Notes"]
COL_LETTERS = ["B", "C", "D", "E", "F", "G", "H"]

# Round-trip vocab. Free text here means silent upsert failures, so both are dropdowns.
PERSONAS = ["SENIOR_MANAGER", "PEER_ENGINEER", "RECRUITER", "ALUMNI"]
OUTREACH = ["sourced", "drafted", "sent", "not_accepted", "accepted", "replied", "positive", "meeting_scheduled", "negative", "referral_asked", "referral_secured", "no_response", "dropped"]

# Bracketed ID in the Target Role line (Req ID or job_id).
JOBID_RE = re.compile(r"\[([A-Za-z0-9_.-]+)\]\s*$")


def extract_req_id(url):
    """Extract Requisition ID from the JD or job URL if available."""
    if not url:
        return None
    # Workday style: _R-156221, _JR103028, _2026-R431
    m = re.search(r"_(R-?\d+|JR\d+|\d+-R\d+)", url, re.I)
    if m:
        return m.group(1)
    # iCIMS / Oracle / general /job/12345 or /jobs/12345
    m = re.search(r"/jobs?/(\d+)", url)
    if m:
        return m.group(1)
    # AcquireTM ID=7987
    m = re.search(r"ID=(\d+)", url)
    if m:
        return m.group(1)
    # Generic job path identifier
    m = re.search(r"/job/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


# ------------------------------------------------------------------------ export
def qualifying(apps, found_date=None):
    out = [a for a in apps
           if (a.get("score") or 0) > MIN_SCORE
           and a.get("status") not in DEAD_STATUSES
           and (found_date is None or a.get("found_date") == found_date)]
    out.sort(key=lambda a: (-(a.get("score") or 0), a.get("company") or ""))
    return out


def _stamp(ws, row, col_letter, src_row, value):
    """Write a value, wearing the style the template gave that cell in block 1."""
    cell = ws[f"{col_letter}{row}"]
    src = ws[f"{col_letter}{src_row}"]
    if src.has_style:
        cell._style = copy.copy(src._style)
    cell.value = value
    return cell


def build(apps, out_path, template=TEMPLATE):
    wb = load_workbook(template)
    ws = wb.active

    # Drop built-in tables and unmerge ranges so we can cleanly re-lay the sheet
    for name in list(ws.tables):
        del ws.tables[name]
    for rng in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(rng))

    style_rows = {
        "head": FIRST_HEADER_ROW,
        "url": FIRST_HEADER_ROW + 1,
        "loc": FIRST_HEADER_ROW + 2,
        "cols": FIRST_HEADER_ROW + 3,
        "data": FIRST_HEADER_ROW + 4
    }

    # Clear all cells from row 5 down to the end of the sheet
    max_clear_row = max(ws.max_row, FIRST_HEADER_ROW + STRIDE * len(apps) + DATA_ROWS + 10)
    for row in range(FIRST_HEADER_ROW, max_clear_row + 1):
        for letter in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]:
            ws[f"{letter}{row}"].value = None

    for i, a in enumerate(apps):
        top = FIRST_HEADER_ROW + i * STRIDE
        req_id = extract_req_id(a.get("job_url")) or a.get("job_id") or f"Role-{i+1}"
        
        # 4 header rows:
        # Row 1: Target Role
        _stamp(ws, top, "B", style_rows["head"],
               f"Target Role {i + 1}: {a.get('role') or ''}  [{req_id}]")
        # Row 2: Job URL Link
        _stamp(ws, top + 1, "B", style_rows["url"],
               f"Job URL Link: {a.get('job_url') or '—'}")
        # Row 3: Company Name (below Job URL)
        _stamp(ws, top + 2, "B", style_rows["loc"],
               f"Company: {a.get('company') or '—'}")
        # Row 4: Location of Role
        _stamp(ws, top + 3, "B", style_rows["loc"],
               f"Location of Role: {a.get('location') or '—'}")

        # Merge B:H for the 4 header lines
        for r in (top, top + 1, top + 2, top + 3):
            ws.merge_cells(f"B{r}:H{r}")

        # Table header row at top + 4
        hdr = top + 4
        for letter, label in zip(COL_LETTERS, COLS):
            _stamp(ws, hdr, letter, style_rows["cols"], label)

        # 10 data rows:
        for r in range(hdr + 1, hdr + 1 + DATA_ROWS):
            for letter in COL_LETTERS:
                _stamp(ws, r, letter, style_rows["data"], None)
            # Job Title (Col B) is left EMPTY for the networked contact's title
            ws[f"B{r}"] = None
            # Job Posted Date (Col C) is pre-filled with found_date
            ws[f"C{r}"] = a.get("found_date") or ""

        ref = f"B{hdr}:H{hdr + DATA_ROWS}"
        t = Table(displayName=f"Networking{i + 1}", name=f"Networking{i + 1}", ref=ref)
        t.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showRowStripes=True,
            showFirstColumn=True, showLastColumn=True, showColumnStripes=False)
        ws.add_table(t)

        # Dropdowns for Persona (Col F) and Status (Col G)
        for letter, vocab in (("F", PERSONAS), ("G", OUTREACH)):
            dv = DataValidation(type="list", formula1='"' + ",".join(vocab) + '"',
                                allow_blank=True, showErrorMessage=True)
            dv.error = "Pick a value from the list — free text will not import."
            ws.add_data_validation(dv)
            dv.add(f"{letter}{hdr + 1}:{letter}{hdr + DATA_ROWS}")

    # Set column widths
    col_widths = {"B": 28, "C": 16, "D": 22, "E": 30, "F": 18, "G": 18, "H": 35}
    for letter, width in col_widths.items():
        ws.column_dimensions[letter].width = width

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    wb.save(out_path)
    return out_path


# ------------------------------------------------------------------------ import
def parse(path):
    """Read every block. Rows are scanned past the template's 10, so extra rows count."""
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    blocks, row, misses = [], 1, []
    while row <= ws.max_row:
        v = ws[f"B{row}"].value
        if isinstance(v, str) and v.strip().lower().startswith("target role"):
            m = JOBID_RE.search(v.strip())
            if not m:
                misses.append((row, v.strip()))
                row += 1
                continue
            
            # Find the header row by searching for "Contact Name" in B:H within the next 6 rows
            hdr = None
            for probe in range(row + 1, min(row + 8, ws.max_row + 1)):
                row_vals = [str(ws[f"{L}{probe}"].value or "").strip() for L in COL_LETTERS]
                if "Contact Name" in row_vals:
                    hdr = probe
                    break
            
            if hdr is None:
                hdr = row + 4

            company_val = ""
            for probe in range(row + 1, hdr):
                p_text = str(ws[f"B{probe}"].value or "")
                if p_text.lower().startswith("company:"):
                    company_val = p_text.split(":", 1)[1].strip()

            rows, r = [], hdr + 1
            while r <= ws.max_row:
                nxt = ws[f"B{r}"].value
                if isinstance(nxt, str) and nxt.strip().lower().startswith("target role"):
                    break
                cells = {c: ws[f"{L}{r}"].value
                         for c, L in zip(COLS, COL_LETTERS)}
                if any(str(x).strip() for x in cells.values() if x is not None):
                    rows.append((r, cells))
                r += 1
            blocks.append({
                "job_id": m.group(1),
                "label": v.strip(),
                "company": company_val,
                "rows": rows
            })
            row = r
        else:
            row += 1
    return blocks, misses


def normalize_persona(p):
    if not p:
        return None
    p_str = str(p).strip()
    if p_str in PERSONAS:
        return p_str
    norm = p_str.upper().replace(" ", "_").replace("-", "_")
    if norm in PERSONAS:
        return norm
    if any(k in norm for k in ["HIRING", "MANAGER", "LEAD", "DIRECTOR", "VP", "HEAD"]):
        return "SENIOR_MANAGER"
    if any(k in norm for k in ["PEER", "ENGINEER", "SPECIALIST", "ANALYST"]):
        return "PEER_ENGINEER"
    if any(k in norm for k in ["RECRUIT", "TALENT", "SOURCER", "HR"]):
        return "RECRUITER"
    if any(k in norm for k in ["ALUM", "ILLINOIS", "VNR"]):
        return "ALUMNI"
    return None


def to_contacts(blocks, apps):
    """Turn filled rows into contact records. Match by Req ID, job_id, or company."""
    out, problems = [], []
    
    # Index applications by multiple keys for reliable matching
    apps_by_id = {}
    for a in apps:
        apps_by_id[a["job_id"]] = a
        req = extract_req_id(a.get("job_url"))
        if req:
            apps_by_id[req] = a
        if a.get("job_url"):
            # Also index by unique parts of job_url
            apps_by_id[a["job_url"]] = a

    for b in blocks:
        raw_id = b["job_id"]
        app = apps_by_id.get(raw_id)
        if not app:
            # Try searching in job_urls
            matched = [a for a in apps if raw_id in (a.get("job_url") or "") or raw_id in (a.get("notes") or "")]
            if matched:
                app = matched[0]
        if not app and b.get("company"):
            matched = [a for a in apps if a.get("company", "").lower() == b["company"].lower()]
            if matched:
                app = matched[0]

        if not app:
            problems.append(f"{b['label']}: ID {raw_id} could not be resolved to an application")
            continue

        app_id = app["job_id"]
        for rownum, c in b["rows"]:
            name = (c.get("Contact Name") or "").strip() if c.get("Contact Name") else ""
            if not name:
                continue
            persona_raw = (c.get("Persona") or "").strip()
            persona = normalize_persona(persona_raw)
            status = ((c.get("Status") or "").strip() or "sourced")
            where = f"row {rownum} ({name})"
            if persona_raw and not persona:
                problems.append(f"{where}: persona '{persona_raw}' cannot be mapped to {PERSONAS}")
                continue
            if status not in OUTREACH:
                problems.append(f"{where}: status '{status}' is not a valid outreach_status")
                continue
            url = (c.get("Profile URL") or "")
            url = url.strip() if isinstance(url, str) else ""
            job_title = (c.get("Job Title") or "").strip() if c.get("Job Title") else None
            notes = c.get("Notes") or None

            out.append({
                "name": name,
                "title": job_title,
                "company": b.get("company") or app.get("company") or "",
                "application_id": app_id,
                "persona": persona,
                "linkedin_url": url or None,
                "channel": "linkedin" if "linkedin.com" in url.lower() else None,
                "outreach_status": status,
                "notes": notes,
                "last_touch": (datetime.date.today().isoformat()
                               if status not in ("sourced", "drafted") else None),
            })
    return out, problems


def _post(rows):
    """Upsert contacts: update existing (name, application_id) records or insert new ones with valid sequential IDs."""
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("ERROR: needs SUPABASE_KEY in the environment (put it in .env).")
    
    existing = refresh._rest("contacts")
    existing_map = {
        (c["name"].strip().lower(), c["application_id"]): c
        for c in existing if c.get("name") and c.get("application_id")
    }
    
    next_id = max((c["id"] for c in existing if isinstance(c.get("id"), int)), default=0) + 1
    
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    result = []
    to_insert = []
    
    for r in rows:
        key_pair = (r["name"].strip().lower(), r["application_id"])
        if key_pair in existing_map:
            # Update existing contact
            c_id = existing_map[key_pair]["id"]
            patch_url = f"{refresh.SUPABASE_URL}/rest/v1/contacts?id=eq.{c_id}"
            req = urllib.request.Request(
                patch_url, data=json.dumps(r).encode(), method="PATCH", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode() or "[]")
                result.extend(data)
        else:
            # New contact with assigned ID
            r_copy = dict(r)
            r_copy["id"] = next_id
            next_id += 1
            to_insert.append(r_copy)

    if to_insert:
        post_url = f"{refresh.SUPABASE_URL}/rest/v1/contacts"
        req = urllib.request.Request(
            post_url, data=json.dumps(to_insert).encode(), method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode() or "[]")
            result.extend(data)

    return result


def contacts_from_records(records):
    """Turn pipeline records (fetched/ranked/tailored rows) into contact rows.

    Each row's recruiter_url / peer_url are the 1-click LinkedIn people-search
    links generated in tools/fetch_jobs.py (reference-repo Step 4.5). This is how
    those links land in the source-of-truth contacts table — the Supabase
    `contacts` table (project chsrkysjongzgdbwqhlu, linkedin-memory). Recruiter →
    persona RECRUITER, team lead → persona SENIOR_MANAGER (the hiring-lead bucket).
    """
    out = []
    for r in records:
        app_id = r.get("job_id") or r.get("id") or r.get("application_id")
        if not app_id:
            continue
        company = (r.get("company") or "").strip()
        role = (r.get("role") or r.get("title") or "").strip()
        for url_key, persona, label in (
            ("recruiter_url", "RECRUITER", "Recruiter / TA"),
            ("peer_url", "SENIOR_MANAGER", "Team Lead"),
        ):
            url = (r.get(url_key) or "").strip()
            if not url or url == "#":
                continue
            out.append({
                # ponytail: name is a placeholder keyed on company so re-runs
                # upsert (not duplicate). If you renames it to the real person a
                # later run re-adds the search placeholder — acceptable.
                "name": f"{label} — {company}" if company else label,
                "title": None,
                "company": company,
                "application_id": app_id,
                "persona": persona,
                "linkedin_url": url,
                "channel": "linkedin",
                "hook_signal": f"1-click LinkedIn people-search for {role} at {company}. "
                               f"Open it to find and connect with the {label.lower()}.",
                "outreach_status": "sourced",
                "notes": f"Auto-sourced people-search link ({label}).",
                "last_touch": None,
            })
    return out


# -------------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export")
    e.add_argument("--date", help="only roles found on this date (default: all live >70)")
    e.add_argument("--out")
    e.add_argument("--template", default=TEMPLATE)

    i = sub.add_parser("import")
    i.add_argument("file")
    i.add_argument("--dry-run", action="store_true")

    ad = sub.add_parser("add", help="upsert recruiter/team-lead people-search links "
                                    "from a pipeline JSON (fetched/ranked/tailored) "
                                    "straight into the Supabase contacts table")
    ad.add_argument("file", help="a .pipeline/*.json carrying recruiter_url / peer_url")
    ad.add_argument("--dry-run", action="store_true")

    a = ap.parse_args()

    if a.cmd == "add":
        with open(a.file, encoding="utf-8") as f:
            records = json.load(f)
        if isinstance(records, dict):
            records = records.get("jobs") or records.get("rows") or list(records.values())
        rows = contacts_from_records(records)
        print(f"Built {len(rows)} contact row(s) from {a.file}")
        if not rows:
            sys.exit("Nothing to add (no recruiter_url / peer_url in the records).")
        if a.dry_run:
            for r in rows:
                print(f"    {r['application_id']:<12} {r['persona']:<15} {r['name'][:40]}")
            print("Dry run — nothing written.")
            return
        print(f"Upserted {len(_post(rows))} contact(s) to Supabase. "
              f"Run ./refresh.sh --fetch to rebuild the tracker.")
        return

    if a.cmd == "export":
        apps = refresh._rest("applications")
        picked = qualifying(apps, a.date)
        if not picked:
            sys.exit(f"No roles scoring above {MIN_SCORE} are live"
                     + (f" for {a.date}." if a.date else "."))
        stamp = a.date or datetime.date.today().isoformat()
        out = a.out or os.path.join(OUT_DIR, f"networking_{stamp}.xlsx")
        build(picked, out, a.template)
        print(f"Wrote {out}")
        print(f"  {len(picked)} role block(s), {DATA_ROWS} contact rows each:")
        for r in picked:
            req = extract_req_id(r.get("job_url")) or r["job_id"]
            print(f"    {req:<12} {str(r.get('score')):>3}  "
                  f"{(r.get('company') or '')[:28]:<28} {(r.get('role') or '')[:40]}")
        return

    blocks, misses = parse(a.file)
    for row, label in misses:
        print(f"  ! row {row}: no [id] in {label!r} — block skipped")
    apps = refresh._rest("applications")
    rows, problems = to_contacts(blocks, apps)
    for p in problems:
        print(f"  ! {p}")
    print(f"Parsed {len(blocks)} block(s) → {len(rows)} contact row(s)"
          + (f", {len(problems)} rejected" if problems else ""))
    if not rows:
        sys.exit("Nothing to import.")
    if a.dry_run:
        for r in rows:
            print(f"    {r['application_id']:<12} {r['name'][:28]:<28} "
                  f"{r['outreach_status']:<16} {r.get('persona') or '—'}")
        print("Dry run — nothing written.")
        return
    print(f"Upserted {len(_post(rows))} contact(s). Run ./refresh.sh --fetch to rebuild.")


if __name__ == "__main__":
    main()
