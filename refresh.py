#!/usr/bin/env python3
"""
refresh.py — regenerate the Job Search Tracker artifact from Supabase.

ONE generator, ONE database. Run this at the end of every daily run (or any time
the DB changes) and the Cowork artifact updates itself.

Data sources (pick one):
  A) --data tracker_data.json   (default if the file exists)
       A JSON file: {"apps":[...], "contacts":[...]}.
       Claude Code produces it from the Supabase connector, e.g. run these two and
       merge into tracker_data.json:
         select json_agg(a) from (select * from applications) a;
         select json_agg(c) from (select * from contacts) c;
  B) --fetch                    (standalone, no Claude Code)
       Pulls both tables over Supabase REST. Set SUPABASE_KEY in the environment
       (service_role recommended; kept in your local shell / .env, never committed).
       SUPABASE_URL defaults to this project.

Output:
  Writes the artifact index.html (auto-deploys in Cowork) AND a local mirror.
  Override paths with --artifact and --local.

Usage:
  python refresh.py                      # uses ./tracker_data.json
  python refresh.py --data path.json
  python refresh.py --fetch              # needs SUPABASE_KEY env
"""
import os, sys, json, argparse, datetime, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))

def _load_dotenv():
    """Load .env next to this file so SUPABASE_KEY is baked into the artifact even
    when refresh.py is run directly (not via refresh.sh). Existing env vars win."""
    p = os.path.join(HERE, ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
_load_dotenv()

# ONE project: chsrkysjongzgdbwqhlu.
# SUPABASE_KEY is used HERE (server side, --fetch) to read the tables. It is deliberately
# NOT baked into the artifact: the sandbox CSP blocks external hosts, so an in-page REST
# call can never succeed, and a service_role key has no business in a published page.
# The artifact writes through the viewer's Supabase connector (MCP capability) instead.
PROJECT_ID = "chsrkysjongzgdbwqhlu"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://chsrkysjongzgdbwqhlu.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SUPA_TOOL = os.environ.get("SUPA_TOOL", "mcp__f7aaa7e8-6dcc-488f-8f2d-e906ba39c43f__execute_sql")  # legacy connector fallback only
APP_STATUSES = ["referral-pending","pending","applied","dropped","expired","shortlisted","interviewing","offer","rejected"]
# Mirrors the outreach_status_t enum in lifecycle order (extended 2026-08-22 with
# not_accepted / accepted / meeting_scheduled / referral_asked). Keep the two in sync:
# a value here that is not in the enum fails the write with a 400.
OUTREACH_STATUSES = ["sourced", "drafted", "sent", "not_accepted", "accepted", "replied", "positive", "meeting_scheduled", "negative", "referral_asked", "referral_secured", "no_response", "dropped"]
# Default artifact path (Cowork auto-deploys when this file changes). Override with --artifact.
DEFAULT_ARTIFACT = os.path.expanduser("~/Documents/Claude/Artifacts/job-search-tracker/index.html")
DEFAULT_LOCAL = os.path.join(HERE, "job_tracker.html")
# claude.ai Artifact publishes are wrapped in their own <!doctype><head><body> skeleton,
# so they take the page CONTENT only. Regenerated on every rebuild so the published
# artifact never drifts from the Cowork one.
DEFAULT_FRAGMENT = os.path.join(HERE, "job_tracker.artifact.html")

# ------------------------------------------------------------------ data load
def load_from_json(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["apps"], d["contacts"]

def _rest(table):
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        sys.exit("ERROR: --fetch needs SUPABASE_KEY (service_role recommended) in the environment.")
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*"
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def load_from_supabase():
    return _rest("applications"), _rest("contacts")

# ---------------------------------------------------- learning-log connection
# Drop reviews written in the tracker's Pipeline note field are synced into a
# managed block in learning_log.md on every rebuild. The log's own preamble says
# standing lessons are read before every run, so this closes the loop: the agent
# reads new drop reviews each session and promotes recurring patterns into a
# standing lesson above the block.
DROP_START = "<!-- DROP-REVIEWS:START -->"
DROP_END = "<!-- DROP-REVIEWS:END -->"

def sync_drop_reviews_to_learning_log(apps, path=None):
    """Rewrite the managed drop-review block in learning_log.md from current data.
    Returns rows written, or -1 if the file was already up to date."""
    path = path or os.path.join(HERE, "learning_log.md")
    rows = [a for a in apps if a.get("status") == "dropped" and (a.get("notes") or "").strip()]
    rows.sort(key=lambda a: (a.get("found_date") or ""), reverse=True)
    lines = [DROP_START,
             "## Dropped-application reviews (auto-synced from the tracker)",
             "_Sid's own reason for each drop, pulled from the Pipeline note field in the tracker. "
             "Read before scoring like any standing lesson; promote recurring patterns into a standing "
             "lesson above, then the drop can be forgotten. Regenerated by refresh.py every run — edit "
             "notes in the tracker, not here._",
             ""]
    if rows:
        for a in rows:
            note = " ".join((a.get("notes") or "").split())
            lines.append("- **{co} — {role}** (`{jid}`, found {fd}): {note}".format(
                co=a.get("company", "?"), role=a.get("role", "?"),
                jid=a.get("job_id", "?"), fd=a.get("found_date") or "—", note=note))
    else:
        lines.append("_No dropped-application reviews yet._")
    lines.append(DROP_END)
    block = "\n".join(lines)
    try:
        cur = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        cur = ""
    if DROP_START in cur and DROP_END in cur:
        new = cur[:cur.index(DROP_START)] + block + cur[cur.index(DROP_END) + len(DROP_END):]
    else:
        new = (cur.rstrip() + "\n\n" + block + "\n") if cur.strip() else block + "\n"
    if new != cur:
        open(path, "w", encoding="utf-8").write(new)
        return len(rows)
    return -1

def _selftest():
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "ll.md")
    open(p, "w").write("# Log\n\nexisting standing lesson\n")
    apps = [{"status": "dropped", "notes": "no sponsorship in JD", "job_id": "j1",
             "company": "Acme", "role": "QE", "found_date": "2026-07-20"},
            {"status": "applied", "notes": "keep", "job_id": "j2",
             "company": "B", "role": "R", "found_date": "2026-07-19"}]
    assert sync_drop_reviews_to_learning_log(apps, p) == 1
    t = open(p).read()
    assert "existing standing lesson" in t and "Acme" in t and "j2" not in t, t
    assert sync_drop_reviews_to_learning_log(apps, p) == -1              # idempotent
    apps[0]["notes"] = "ITAR / US-person only"
    assert sync_drop_reviews_to_learning_log(apps, p) == 1               # change detected
    t = open(p).read()
    assert t.count(DROP_START) == 1 and "ITAR" in t and "no sponsorship" not in t, t
    print("selftest OK")

# ------------------------------------------------------------------ template
def to_fragment(html):
    """Strip the document wrapper for a claude.ai Artifact publish: <style> + body markup.
    The <title> is dropped on purpose — the Artifact tool's `title` parameter names it,
    and a <title> parsed inside <body> is not valid markup."""
    style = html[html.index("<style>"):html.index("</style>") + len("</style>")]
    body = html[html.index("<body>") + len("<body>"):html.rindex("</body>")]
    return style + "\n" + body


def build_html(apps, contacts):
    today = datetime.date.today().isoformat()
    return (TEMPLATE
        .replace("__CSS__", CSS)
        .replace("__TODAY__", today)
        .replace("__PROJECT_ID__", PROJECT_ID)
        .replace("__SUPA_TOOL__", SUPA_TOOL)
        .replace("__APPS__", json.dumps(apps))
        .replace("__CONTACTS__", json.dumps(contacts))
        .replace("__APP_STATUSES__", json.dumps(APP_STATUSES))
        .replace("__OUTREACH_STATUSES__", json.dumps(OUTREACH_STATUSES)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "tracker_data.json"))
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--artifact", default=DEFAULT_ARTIFACT)
    ap.add_argument("--local", default=DEFAULT_LOCAL)
    ap.add_argument("--fragment", default=DEFAULT_FRAGMENT)
    ap.add_argument("--selftest", action="store_true", help="run the drop-review sync self-check and exit")
    a = ap.parse_args()
    if a.selftest:
        _selftest(); return
    if a.fetch:
        apps, contacts = load_from_supabase()
        src = "Supabase REST"
    else:
        if not os.path.exists(a.data):
            sys.exit(f"No data file at {a.data}. Use --fetch, or produce tracker_data.json from the connector.")
        apps, contacts = load_from_json(a.data)
        src = a.data
    n = sync_drop_reviews_to_learning_log(apps)
    if n >= 0: print(f"  synced {n} drop review(s) into learning_log.md")
    html = build_html(apps, contacts)
    wrote = []
    for p in [a.artifact, a.local, a.fragment]:
        if not p: continue
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(to_fragment(html) if p == a.fragment else html)
            wrote.append(p)
        except Exception as e:
            print(f"  ! could not write {p}: {e}")
    print(f"Rendered {len(apps)} applications + {len(contacts)} contacts from {src}.")
    for p in wrote: print(f"  wrote {p}")

# ================================================================== UI (CSS)
CSS = r"""
:root{
  color-scheme: light;
  --bg:#eef1ec; --panel:#ffffff; --panel-2:#f4f6f8;
  --ink:#0e1621; --muted:#3d4a57; --faint:#5d6b7a; --line:#d5dbe1;
  --edge:#0e1621; --accent:#0a66c2; --accent-soft:#e3f0fb; --accent-ink:#084b8f;
  --referral:#0a66c2; --direct:#7c4d86; --staffing:#a06a1b; --outreach:#2f7a52; --drop:#7a848d;
  --due:#8a4b00; --pos:#1b6b3a; --neg:#a32a22; --danger:#b3261e; --danger-soft:#fbe7e5;
  --sans:'Inter','SF Pro Text',system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;
  --r:9px; --shadow:4px 4px 0 var(--edge); --shadow-sm:2px 2px 0 var(--edge);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;font-weight:450;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--accent-ink);font-weight:600}
h1,h2,h3{margin:0}
.eyebrow{font-size:12px;letter-spacing:.02em;text-transform:uppercase;color:var(--muted);font-weight:800}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.hide{display:none!important}
::selection{background:var(--accent-soft)}
header{background:var(--panel);border-bottom:2px solid var(--edge);padding:15px 22px}
.htop{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.brand{font-size:21px;font-weight:900;letter-spacing:-.2px}
.brand small{display:block;font-weight:700;color:var(--faint);font-size:12px;letter-spacing:.02em;margin-top:2px}
.clock{font-size:12.5px;color:var(--muted);text-align:right;font-weight:600}
.clock b{display:block;color:var(--ink);font-size:15px;font-weight:800}
.badges{display:flex;gap:6px;margin-top:5px;justify-content:flex-end;flex-wrap:wrap}
.gatepill{display:inline-block;font-size:12px;color:var(--accent-ink);background:var(--accent-soft);border:1.5px solid var(--accent);padding:2px 9px;border-radius:20px;font-weight:800}
.livepill{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:800;padding:2px 9px;border-radius:20px;border:1.5px solid}
.livepill.on{color:#0c5b2e;background:#e2f2e8;border-color:#1b6b3a}
.livepill.off{color:#7a5c16;background:#f7efdb;border-color:#a06a1b}
.livepill .dot{width:7px;height:7px;border-radius:50%}
.livepill.on .dot{background:#1b6b3a}.livepill.off .dot{background:#a06a1b}
.tabs{display:flex;gap:8px;margin-top:15px;flex-wrap:wrap}
.tab{font-size:13.5px;letter-spacing:.01em;font-weight:800;padding:9px 18px;border:2px solid var(--edge);background:#fff;border-radius:7px;cursor:pointer;color:var(--ink);transition:box-shadow .08s}
.tab:hover{box-shadow:var(--shadow-sm)}
.tab[aria-selected="true"]{background:var(--accent);color:#fff;box-shadow:var(--shadow-sm)}
main{max-width:1280px;margin:0 auto;padding:20px 22px 60px}
.panel{display:none} .panel.active{display:block}
.srcnote{background:var(--panel);border:2px solid var(--edge);border-radius:var(--r);box-shadow:var(--shadow-sm);padding:11px 15px;color:var(--muted);font-size:13px;font-weight:500;margin-bottom:16px}
.srcnote b{color:var(--ink)}
.card{background:var(--panel);border:2px solid var(--edge);border-radius:var(--r);box-shadow:var(--shadow)}
.kpis{display:block;margin-bottom:18px}
.plinkrow{margin:5px 0 2px}
.plink{font-family:var(--mono);font-size:11.5px;color:var(--accent);text-decoration:none;
  border-bottom:1px dotted var(--accent);word-break:break-all}
.plink:hover{background:var(--accent-soft)}
.plink.none{color:var(--danger);border-bottom:0;font-style:italic}
.kpigroup{margin-bottom:13px}
.kpigroup h4{font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;
  color:var(--faint);margin:0 0 7px 2px}
.kpirow{display:grid;grid-template-columns:repeat(var(--cols),1fr);gap:11px}
@media(max-width:900px){.kpirow{grid-template-columns:repeat(3,1fr)}}
@media(max-width:480px){.kpirow{grid-template-columns:repeat(2,1fr)}}
.kpi{background:var(--panel);border:2px solid var(--edge);border-radius:var(--r);box-shadow:var(--shadow-sm);padding:13px 14px}
.kpi .n{font-variant-numeric:tabular-nums;font-size:28px;font-weight:900;letter-spacing:-.02em;line-height:1}
.kpi .l{font-size:12px;color:var(--muted);margin-top:5px;line-height:1.25;font-weight:700}
.kpi.accent{background:var(--accent);border-color:var(--edge)}.kpi.accent .n,.kpi.accent .l{color:#fff}
.kpi.warn{background:var(--danger);border-color:var(--edge)}.kpi.warn .n,.kpi.warn .l{color:#fff}
.block{padding:16px 18px}
.dash-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;margin-bottom:18px}
@media(max-width:820px){.dash-grid{grid-template-columns:1fr}}
.block .eyebrow{display:block;margin-bottom:12px}
.dist{display:flex;flex-direction:column;gap:9px}
.dist .drow{display:grid;grid-template-columns:128px 1fr 36px;align-items:center;gap:10px}
.dist .lab{font-size:13px;color:var(--ink);font-weight:600}
.dist .track{background:var(--panel-2);border-radius:20px;height:14px;overflow:hidden;border:1px solid var(--line)}
.dist .track>i{display:block;height:100%;border-radius:20px}
.dist .val{font-size:13.5px;text-align:right;font-weight:800}
.dist .grp-lab{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint);font-weight:800;margin:10px 0 1px}
.dist .grp-lab:first-child{margin-top:0}
.recent{display:flex;flex-direction:column;gap:0}
.recent-row{display:flex;align-items:center;gap:11px;padding:10px 0;border-bottom:1px solid var(--line);cursor:pointer}
.recent-row:last-child{border-bottom:none}
.recent-row:hover .recent-title{color:var(--accent-ink)}
.recent-date{font-size:12.5px;color:var(--faint);white-space:nowrap;font-weight:700;font-variant-numeric:tabular-nums}
.recent-title{font-size:13.5px;flex:1;font-weight:600}
.recent-n{font-size:12px;color:var(--muted);font-weight:700}
.tbl-scroll{overflow-x:auto;border:2px solid var(--edge);border-radius:var(--r);background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11.5px;letter-spacing:.03em;text-transform:uppercase;color:var(--faint);font-weight:800;background:var(--panel-2);cursor:pointer;white-space:nowrap}
th:hover{color:var(--ink)}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--panel-2)}
tr.od{background:var(--danger-soft)} tr.od:hover{background:#f7dcd9}
.chip{display:inline-block;font-size:11px;font-weight:800;padding:2px 8px;border-radius:20px;letter-spacing:.01em;white-space:nowrap;border:1.5px solid transparent}
.chip.referral{background:#dbeafe;color:var(--referral);border-color:#b6d3f5}
.chip.direct-apply{background:#efe4f1;color:var(--direct);border-color:#ddc3e1}
.chip.staffing{background:#f3e9d6;color:var(--staffing);border-color:#e6d3ab}
.chip.outreach{background:#dcefe3;color:var(--outreach);border-color:#bcdcc7}
.chip.t1{background:#e0edfb;color:#08417a;border-color:#bcd6f2}
.chip.t2{background:#e9edf0;color:#3c4b57;border-color:#d0d8de}
.chip.t3{background:#f2ecdd;color:#6f5416;border-color:#e3d4b3}
.chip.alum{background:#eee6fb;color:#5f36a8;border-color:#dbc9f2}
.score-pill{font-weight:900;font-variant-numeric:tabular-nums}
.score-pill.hi{color:var(--referral)}.score-pill.mid{color:var(--direct)}.score-pill.lo{color:var(--drop)}
.stagepill{font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:20px;text-transform:uppercase;letter-spacing:.02em;border:1.5px solid var(--line);background:var(--panel-2);color:var(--muted);white-space:nowrap}
.stagepill.st-applied,.stagepill.st-offer,.stagepill.st-shortlisted{background:#e2f2e8;color:var(--pos);border-color:#bce0c9}
.stagepill.st-referral-pending{background:#fdefdb;color:var(--due);border-color:#f0d6a8}
.stagepill.st-pending{background:#eaeef2;color:#3c4b57;border-color:#d0d8de}
.stagepill.st-interviewing{background:#e3f0fb;color:var(--accent-ink);border-color:#b6d3f5}
.stagepill.st-dropped,.stagepill.st-rejected,.stagepill.st-expired{background:#fbe4e2;color:var(--neg);border-color:#f0c4bf}
.od-tag{font-size:10px;font-weight:900;color:#fff;background:var(--danger);padding:1px 7px;border-radius:20px;letter-spacing:.03em}
.due-tag{font-size:10px;font-weight:900;color:#fff;background:var(--due);padding:1px 7px;border-radius:20px}
.subtoggle{display:inline-flex;gap:0;border:2px solid var(--edge);border-radius:8px;overflow:hidden;margin-bottom:14px;box-shadow:var(--shadow-sm)}
.subtoggle button{font-size:13.5px;font-weight:800;padding:9px 18px;background:#fff;border:none;cursor:pointer;color:var(--ink);border-right:2px solid var(--edge)}
.subtoggle button:last-child{border-right:none}
.subtoggle button[aria-pressed="true"]{background:var(--accent);color:#fff}
.tbl-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.tbl-tools select,.tbl-tools input{padding:8px 10px;border:2px solid var(--edge);border-radius:6px;background:#fff;font-size:13px;font-family:inherit;font-weight:600}
.tbl-tools input[type=text]{min-width:150px}
.tbl-tools input[type=number]{width:70px}
.tbl-tools label{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--faint);font-weight:800}
.toggle{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted);cursor:pointer;font-weight:700}
.chipbtn{padding:6px 13px;border:2px solid var(--edge);border-radius:999px;background:#fff;cursor:pointer;font-size:12.5px;color:var(--ink);font-weight:800}
.chipbtn.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-ink)}
.chipbtn.warn.on{background:var(--danger-soft);border-color:var(--danger);color:var(--danger)}
.pipe-count{font-size:12px;color:var(--faint);margin:0 0 8px;text-transform:uppercase;letter-spacing:.03em;font-weight:800}
select.mini{font-size:12px;font-weight:700;padding:4px 7px;border:1.5px solid var(--edge);border-radius:6px;background:#fff;cursor:pointer;font-family:inherit}
select.mini:disabled{opacity:.5;cursor:progress}
select.stageselect{font-size:13px;font-weight:800;padding:6px 10px;border:2px solid var(--edge);border-radius:6px;background:#fff;cursor:pointer;font-family:inherit}
.pipe-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.pipe-toolbar input[type=text]{padding:8px 11px;border:2px solid var(--edge);border-radius:6px;font-size:13px;background:#fff;font-family:inherit;font-weight:600;flex:1;min-width:170px}
.pipe-main{display:grid;grid-template-columns:minmax(370px,1.05fr) minmax(360px,520px);gap:16px;align-items:start}
@media(max-width:980px){.pipe-main{grid-template-columns:1fr}}
.pipe-list{max-height:74vh;overflow:auto}
.plrow{display:flex;gap:11px;padding:11px 13px;border-bottom:1px solid var(--line);cursor:pointer;align-items:flex-start}
.plrow:hover{background:var(--panel-2)}
.plrow.sel{background:var(--accent-soft)}
.plrow.od{box-shadow:inset 3px 0 0 var(--danger)}
.plrow .pr-date{font-size:11px;color:var(--faint);white-space:nowrap;padding-top:2px;width:44px;font-weight:700;font-variant-numeric:tabular-nums}
.plrow .pr-main{flex:1;min-width:0}
.plrow .pr-co{font-weight:800;font-size:14px}
.plrow .pr-role{font-size:12.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}
.plrow .pr-meta{display:flex;gap:5px;margin-top:6px;flex-wrap:wrap;align-items:center}
.plrow .pr-score{font-weight:900;font-size:14px;padding-top:2px}
.detail{padding:0;position:sticky;top:14px}
.dhead{padding:16px 18px;border-bottom:2px solid var(--edge)}
.dhead .dname{font-size:17px;font-weight:900}
.dhead .drole{color:var(--muted);font-size:13.5px;margin-top:3px;font-weight:600}
.dhead .dmeta{display:flex;gap:6px;margin-top:11px;flex-wrap:wrap;align-items:center}
.dsec{padding:14px 18px;border-bottom:1px solid var(--line)}
.dsec:last-child{border-bottom:none}
.dsec h4{margin:0 0 9px;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--faint);font-weight:800}
.dsec p{margin:0;font-size:13.5px;line-height:1.55}
.kv{display:grid;grid-template-columns:auto 1fr;gap:5px 12px;font-size:13px}
.kv .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--faint);font-weight:800;white-space:nowrap}
.kv span:not(.k){font-weight:600}
.field-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.flip{font-size:12.5px;font-weight:800;padding:7px 12px;border:2px solid var(--danger);border-radius:6px;background:var(--danger-soft);color:var(--danger);cursor:pointer}
.flip:hover{box-shadow:2px 2px 0 var(--danger)}
.notebox{width:100%;font-family:var(--sans);font-size:13px;padding:9px 11px;border:2px solid var(--edge);border-radius:7px;background:var(--panel-2);color:var(--ink);resize:vertical;font-weight:500;line-height:1.5}
.notebox:focus{outline:none;border-color:var(--accent);background:#fff}
.savebtn{font-size:12.5px;font-weight:800;padding:7px 14px;border:2px solid var(--edge);border-radius:6px;background:var(--accent-soft);color:var(--accent-ink);cursor:pointer}
.savebtn:hover{box-shadow:2px 2px 0 var(--edge)}
.note-hint{font-size:11px;color:var(--faint);font-weight:600}
.dsec.drop h4{color:var(--neg)}
.flag{color:var(--due);font-size:12px;font-weight:800;margin-top:7px;display:block}
.empty{color:var(--faint);text-align:center;padding:60px 20px;font-size:13.5px;font-weight:600}
.linkline a{font-size:12.5px;font-weight:800}
.tsec h3{margin:16px 0 9px;font-size:15.5px;font-weight:900}
.tsec h3 .c{font-weight:700;color:var(--faint);font-size:12.5px;margin-left:6px}
.tcard{background:var(--panel);border:2px solid var(--edge);border-radius:var(--r);box-shadow:var(--shadow-sm);padding:14px 16px;margin-bottom:10px;display:grid;grid-template-columns:1fr auto;gap:12px}
.tcard.od{box-shadow:inset 4px 0 0 var(--danger),var(--shadow-sm)}
.tcard.due{box-shadow:inset 4px 0 0 var(--due),var(--shadow-sm)}
.tcard .h{font-weight:900;font-size:14.5px}
.tcard .meta{color:var(--muted);font-size:12.5px;margin-top:3px;font-weight:600}
.tcard .wait{color:var(--faint);font-size:12.5px;margin-top:6px;font-weight:500}
.tcard .act{display:flex;flex-direction:column;gap:8px;align-items:flex-end;min-width:180px}
.tcard .fu{font-size:12.5px;font-weight:900}
#toasts{position:fixed;right:18px;bottom:18px;display:flex;flex-direction:column;gap:8px;z-index:80}
.toast{background:#fff;border:2px solid var(--edge);border-radius:8px;box-shadow:var(--shadow-sm);padding:10px 14px;font-size:13px;font-weight:700;max-width:340px;animation:tin .16s}
.toast.ok{border-color:var(--pos)} .toast.ok b{color:var(--pos)}
.toast.err{border-color:var(--danger)} .toast.err b{color:var(--danger)}
.toast.info{border-color:var(--accent)} .toast.info b{color:var(--accent-ink)}
.toast .sub{font-weight:500;color:var(--muted);font-size:11.5px;margin-top:2px;font-family:var(--mono)}
@keyframes tin{from{opacity:0;transform:translateY(6px)}}
#tray{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:2px solid var(--edge);box-shadow:0 -4px 0 rgba(14,22,33,.08);transform:translateY(100%);transition:transform .18s;z-index:60}
#tray.show{transform:translateY(0)}
.tray-in{max-width:1280px;margin:0 auto;padding:12px 22px}
.tray-hd{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.tray-hd b{font-size:14px;font-weight:900}
.tray-hd .x{cursor:pointer;color:var(--muted);font-size:12.5px;font-weight:700}
.chg{background:var(--panel-2);border:1.5px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:6px;display:flex;gap:10px;align-items:flex-start}
.chg .sql{flex:1;font-family:var(--mono);font-size:12px;color:#123;white-space:pre-wrap;word-break:break-word}
.chg .cp{font-size:12px;font-weight:800;padding:5px 11px;border:1.5px solid var(--edge);border-radius:6px;background:#fff;cursor:pointer;font-family:inherit}
.chg .cp.copied{background:var(--pos);color:#fff;border-color:var(--pos)}
.copyall{font-weight:900;font-size:12.5px;padding:7px 14px;border:2px solid var(--edge);border-radius:6px;background:var(--accent);color:#fff;cursor:pointer;font-family:inherit}
.tellclaude{color:var(--muted);font-size:12.5px;margin-top:6px;font-weight:500}
.tellclaude code{background:var(--panel-2);padding:1px 6px;border-radius:5px;font-family:var(--mono);font-size:11.5px}
footer{margin-top:26px;font-size:12px;color:var(--faint);text-align:center;font-weight:600}
"""

# ================================================================== UI (HTML+JS)
TEMPLATE = r"""<!DOCTYPE html>
<script type="application/json" id="cowork-artifact-meta">
{"name":"Job Search Tracker","schemaVersion":1,"description":"Supabase-backed Fortify Sprint command center — dual-track, direct-apply-first (Track 1 Broad-Fit · Track 2 Curated Target). Dashboard, Pipeline (dates drill-down, list+detail), Tracker (Job Applications | Networking tables), Follow-ups (contact nudge queue). Status/outreach/flip edits write live to the linkedin-memory DB via the Supabase connector; regenerated by refresh.py after each daily run."}
</script>
<html lang="en"><head><meta charset="UTF-8"><title>Job Search Tracker</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>__CSS__</style></head><body>
<header>
  <div class="htop">
    <div>
      <div class="brand">Job Search Tracker <small>Fortify Sprint · Dual-Track Command Center · Quality / Process Engineer</small></div>
      <div class="badges"><span class="gatepill">gate: &ge;80 referral · 45&ndash;79 direct-apply</span><span class="livepill off" id="livepill"><span class="dot"></span><span id="livetxt">snapshot</span></span></div>
    </div>
    <div class="clock">snapshot <b id="today-date">__TODAY__</b><span style="font-size:11px;color:var(--faint)">Supabase · linkedin-memory</span></div>
  </div>
  <nav class="tabs" role="tablist">
    <button class="tab" role="tab" aria-selected="true"  data-tab="dashboard">Dashboard</button>
    <button class="tab" role="tab" aria-selected="false" data-tab="pipeline">Pipeline</button>
    <button class="tab" role="tab" aria-selected="false" data-tab="tracker">Tracker</button>
    <button class="tab" role="tab" aria-selected="false" data-tab="triage">Follow-ups</button>
  </nav>
</header>
<main>
  <div class="srcnote" id="srcnote"></div>
  <section class="panel active" id="dashboard" role="tabpanel">
    <section class="kpis" id="kpis"></section>
    <div class="dash-grid">
      <div class="card block"><span class="eyebrow">Pipeline distribution</span><div class="dist" id="dist"></div></div>
      <div class="card block"><span class="eyebrow">Recently found</span><div class="recent" id="recent"></div></div>
    </div>
  </section>
  <section class="panel" id="pipeline" role="tabpanel">
    <div id="pipe-dates"></div>
    <div id="pipe-day" class="hide">
      <div class="pipe-toolbar" id="pipe-toolbar"></div>
      <div class="pipe-count" id="pipe-count"></div>
      <div class="pipe-main">
        <section class="card pipe-list" id="pipe-list"></section>
        <aside class="card detail" id="pipe-detail"><div class="empty">Select an application to see its full record.</div></aside>
      </div>
    </div>
  </section>
  <section class="panel" id="tracker" role="tabpanel">
    <div class="subtoggle" role="group" aria-label="Tracker view">
      <button id="tg-apps" aria-pressed="true">Job Applications</button>
      <button id="tg-net" aria-pressed="false">Networking</button>
    </div>
    <div id="trk-apps">
      <div class="tbl-tools" id="apps-tools"></div><div class="pipe-count" id="apps-count"></div>
      <div class="tbl-scroll"><table id="apps-table"></table></div>
    </div>
    <div id="trk-net" class="hide">
      <div class="tbl-tools" id="net-tools"></div><div class="pipe-count" id="net-count"></div>
      <div class="tbl-scroll"><table id="net-table"></table></div>
    </div>
  </section>
  <section class="panel" id="triage" role="tabpanel"><div id="triage-body"></div></section>
  <footer>One artifact · one Supabase DB (linkedin-memory) · live edits via connector · rebuilt by refresh.py after every daily run</footer>
</main>
<div id="toasts"></div>
<div id="tray"><div class="tray-in">
  <div class="tray-hd"><b>Staged changes (offline)</b> <span style="color:var(--faint);font-weight:700" id="tray-count"></span>
    <span style="flex:1"></span><button class="copyall" id="copyall">Copy all SQL</button><span class="x" id="tray-x">clear ✕</span></div>
  <div id="tray-list"></div>
  <div class="tellclaude">Edits are being staged instead of saved. Copy the SQL to run by hand, or fix the connection called out in the banner above.</div>
</div></div>
<script>
const TODAY="__TODAY__", PROJECT_ID="__PROJECT_ID__", SUPA_TOOL="__SUPA_TOOL__";
// The baked snapshot: what refresh.py rendered. The page re-reads the database at load
// (hydrate(), below) and replaces these, so a missed republish only means the FIRST paint
// is stale — never the data you end up looking at. If the live read fails for any reason,
// the snapshot is what you keep, which is exactly the old behaviour.
let APPS=__APPS__, CONTACTS=__CONTACTS__;
let SNAPSHOT_DATE="__TODAY__", HYDRATED=false;
const APP_STATUSES=__APP_STATUSES__, OUTREACH_STATUSES=__OUTREACH_STATUSES__;
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>(s==null?"":String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let appById=Object.fromEntries(APPS.map(a=>[a.job_id,a]));
const contactsFor=id=>CONTACTS.filter(c=>c.application_id===id&&c.outreach_status!=='dropped');
function rebind(){appById=Object.fromEntries(APPS.map(a=>[a.job_id,a]));}
// Follow-up tracking is lane-agnostic. Gating these on a single lane hides every
// overdue row outside it — which is how 25 live overdue follow-ups read as zero.
const OPEN_ST=new Set(['pending','applied','shortlisted','interviewing','referral-pending']);
const isOpen=a=>OPEN_ST.has(a.status);
const isOverdue=a=>isOpen(a)&&a.follow_up_by&&a.follow_up_by<TODAY;
const isDue=a=>isOpen(a)&&a.follow_up_by===TODAY;
const scoreClass=s=>s==null?'lo':(s>=80?'hi':(s>=60?'mid':'lo'));
// Transport priority: claude.ai MCP capability > legacy Cowork connector > offline tray.
// MCP resolves asynchronously, so initChrome() runs again once boot() knows.
const CONNECTOR=!!(window.cowork&&typeof window.cowork.callMcpTool==='function');
const HIDDEN_STATUSES=['dropped','rejected','expired'];  // kept out of the active pipeline; reachable via the Dropped chip

function initChrome(){
  const p=$('#livepill'), live=!!MCP||CONNECTOR;
  if(live){p.className='livepill on';$('#livetxt').textContent=MCP?'live · via '+esc(MCP_SERVER):'live · via connector';
    $('#srcnote').innerHTML='<b>Live mode.</b> Changing a Status / Outreach dropdown or hitting Flip writes straight to Supabase ('+esc(PROJECT_ID)+') '+(MCP?'through your Supabase connector — you approve the connection once, not once per edit.':'through the Cowork connector, which asks for approval on every edit.');}
  else{p.className='livepill off';$('#livetxt').textContent='snapshot (offline)';
    $('#srcnote').innerHTML='<b>Snapshot mode.</b> No live transport is available here, so edits cannot reach Supabase. Changes are staged as <span class="mono">UPDATE</span> SQL in the tray below to copy.';}
}

/* toasts */
function toast(msg,kind,sub){
  const el=document.createElement('div');el.className='toast '+(kind||'ok');
  el.innerHTML=`<b>${esc(msg)}</b>${sub?`<div class="sub">${esc(sub)}</div>`:''}`;
  $('#toasts').appendChild(el);setTimeout(()=>{el.style.opacity='0';el.style.transition='opacity .3s';setTimeout(()=>el.remove(),300);},kind==='err'?4200:2200);
}

/* tabs */
$$('.tab').forEach(t=>t.onclick=()=>{$$('.tab').forEach(x=>x.setAttribute('aria-selected','false'));$$('.panel').forEach(x=>x.classList.remove('active'));t.setAttribute('aria-selected','true');$('#'+t.dataset.tab).classList.add('active');});
function gotoTab(id){$$('.tab').forEach(x=>x.setAttribute('aria-selected',x.dataset.tab===id));$$('.panel').forEach(x=>x.classList.toggle('active',x.id===id));}

/* offline tray */
const pending=[];
function addChange(sql){pending.push(sql);renderTray();}
function renderTray(){const tray=$('#tray');$('#tray-count').textContent=pending.length?`(${pending.length})`:'';
  if(!pending.length){tray.classList.remove('show');$('#tray-list').innerHTML='';return;}
  tray.classList.add('show');
  $('#tray-list').innerHTML=pending.map((s,i)=>`<div class="chg"><div class="sql">${esc(s)}</div><button class="cp" data-i="${i}">Copy</button></div>`).join('');
  $$('.chg .cp').forEach(b=>b.onclick=()=>{navigator.clipboard.writeText(pending[b.dataset.i]);b.textContent='Copied';b.classList.add('copied');setTimeout(()=>{b.textContent='Copy';b.classList.remove('copied');},1200);});}
$('#tray-x').onclick=()=>{pending.length=0;renderTray();};
$('#copyall').onclick=()=>{navigator.clipboard.writeText(pending.join('\n'));const b=$('#copyall');b.textContent='Copied!';setTimeout(()=>b.textContent='Copy all SQL',1200);};

/* ---- live write ---- */
// Transport, in priority order:
//   1. claude.ai MCP capability  — the connector is declared in the artifact's manifest,
//      so the viewer consents ONCE at the grant instead of once per edit.
//   2. legacy Cowork connector   — ad-hoc tool call; the host prompts on every call.
//   3. offline SQL tray.
// There is deliberately no direct Supabase REST path: the artifact sandbox CSP blocks
// every external host, so that fetch could never succeed — it only ever threw and fell
// through to (2), which is what produced a consent dialog on every single flip.
const MCP_TOOL='execute_sql', MCP_SERVER_FALLBACK='Supabase';
let MCP=null, MCP_SERVER=null;
// null from use() means this view cannot run the capability — not served, not granted,
// or failed to load; indistinguishable by design. Branch on it, never probe window.claude.
async function initMcp(){
  try{MCP=(window.claude&&typeof window.claude.use==='function')?await window.claude.use('mcp'):null;}
  catch(e){MCP=null;}
  if(!MCP)return false;
  // callTool addresses connectors by DISPLAY NAME; resolve it from what the viewer
  // actually has rather than hard-coding a guess.
  try{const r=await MCP.listTools();
      const hit=(r&&r.servers||[]).find(s=>(s.tools||[]).some(t=>t.name===MCP_TOOL));
      MCP_SERVER=hit?hit.server:MCP_SERVER_FALLBACK;}
  catch(e){MCP_SERVER=MCP_SERVER_FALLBACK;}
  return true;
}
// Distinct copy per failure code. A single catch-all banner hides the one action that
// would actually fix the page (reconnect / add / choose / wait). [title, sub, ambiguous]
function mcpFail(e){
  switch((e&&e.code)||''){
    case 'needs_reauth':         return ['Supabase needs reconnecting','claude.ai Settings → Connectors → reconnect Supabase',false];
    case 'server_not_connected': return ['No Supabase connector','Add Supabase in claude.ai Settings → Connectors',false];
    case 'selection_required':   return ['Pick a Supabase connector','You have more than one — choose it when prompted, then retry',false];
    case 'server_not_found':     return ['Supabase connector is gone','It no longer exists upstream — re-add it in Settings → Connectors',false];
    case 'not_in_manifest':      return ['Not permitted','This page may only call Supabase '+MCP_TOOL+' — republish to widen the manifest',false];
    case 'blocked_by_policy':    return ['Blocked by policy','Your org blocks this connector tool',false];
    case 'approval_required':    return ['Needs per-call approval','Artifacts cannot grant that — edits will stage as SQL below',false];
    case 'tool_error':           return ['Supabase rejected the write',(e.message||'').slice(0,120),false];
    case 'bad_request':
    case 'transform_error':      return ['Bad request',(e.message||'').slice(0,120),false];
    case 'not_granted':
    case 'capability_disabled':
    case 'capability_removed':   return ['Live writes unavailable here','Edits will stage as SQL below',false];
    // AMBIGUOUS for a write: a rejection is NOT proof the UPDATE did not run.
    case 'server_unavailable':
    case 'upstream_error':
    case 'cancelled':
    case 'rate_limited':         return ['Supabase did not answer','This edit may or may not have saved — reload to confirm',true];
    default:                     return ['Save failed',(e&&e.message||'').slice(0,120),true];
  }
}
async function mcpSQL(sql){await MCP.callTool(MCP_SERVER,MCP_TOOL,{project_id:PROJECT_ID,query:sql});}
// Legacy Cowork path. Its tool id changes per session/reconnect, so discover it at
// runtime instead of trusting the baked-in constant (which silently no-ops if stale).
function coworkToolNames(){const c=window.cowork||{};let out=[];
  try{const cands=[c.tools,c.mcpTools,c.availableTools,
      (typeof c.listMcpTools==='function'?c.listMcpTools():null),
      (typeof c.getMcpTools==='function'?c.getMcpTools():null)];
    for(const l of cands){if(Array.isArray(l))out=out.concat(l.map(t=>typeof t==='string'?t:(t&&(t.name||t.id||t.tool))));}
  }catch(e){}
  return out.filter(Boolean);}
function resolveSupaTool(){const names=coworkToolNames();
  if(!names.length||names.includes(SUPA_TOOL))return SUPA_TOOL;
  return names.find(n=>/__execute_sql$/.test(n))||names.find(n=>/execute_sql/i.test(n))||SUPA_TOOL;}
async function connectorSQL(sql){
  const r=await window.cowork.callMcpTool(resolveSupaTool(),{project_id:PROJECT_ID,query:sql});
  if(r&&r.isError){const m=(r.content&&r.content[0]&&r.content[0].text)||'database error';throw new Error(m);}
}
// Persist one edit. Never retries a write unattended — an ambiguous failure is reported
// to the user with a reload prompt instead of being silently re-fired.
async function applyOps(sql){
  if(MCP){await mcpSQL(sql);return {live:true,via:'mcp'};}
  if(CONNECTOR){await connectorSQL(sql);return {live:true,via:'connector'};}
  addChange(sql);return {live:false,via:'staged'};
}
// Row count out of the execute_sql envelope. Anchored on the column name: the wrapper
// text around the JSON contains digits of its own, so a bare \d+ match is wrong.
// The rows usually arrive as an ESCAPED JSON string inside the payload
// ({"result":"...[{\\"n\\":282}]..."}), so unescape before matching or nothing hits.
function probeCount(r){
  const p=r&&r.payload;
  let txt=typeof p==='string'?p:JSON.stringify(p!==undefined?p:(r&&r.content)||'');
  txt=txt.replace(/\\+"/g,'"');
  const m=txt.match(/"n"\s*:\s*(-?\d+)/);
  return m?parseInt(m[1],10):null;
}
// Codes where the connector genuinely cannot write, so falling back to the tray is right.
// Everything else (transient, or our own parse trouble) leaves the live path alone.
const MCP_DEAD=['not_granted','capability_disabled','capability_removed','server_not_connected',
  'needs_reauth','not_in_manifest','blocked_by_policy','approval_required','server_not_found',
  'selection_required'];
function liveOff(html,sub){
  const p=$('#livepill');if(p){p.className='livepill off';$('#livetxt').textContent='live NOT writing';}
  const sn=$('#srcnote');if(sn)sn.innerHTML=html;
  toast('Live bridge not writing','err',sub);
}
// Pull the tool's JSON out of the execute_sql envelope. The payload is wrapped in an
// <untrusted-data-ID> block, and the opening tag appears THREE times: once in the
// instructional sentence above the data, once as the real wrapper, and once in the
// trailing sentence AFTER the closing tag. So neither "first" nor "last" is right —
// anchor on the last opening tag that occurs BEFORE the closing tag.
function extractRows(r){
  const p=r&&r.payload;
  if(Array.isArray(p))return p;                       // structured output — nothing to unwrap
  // payload is normally the parsed JSON or the raw text; content blocks are the
  // fallback for a shell that did not populate it.
  const firstText=()=>{const b=((r&&r.content)||[]).filter(x=>x&&x.type==='text')[0];
    return b?String(b.text||''):'';};
  let txt=(typeof p==='string')?p
    :(p&&typeof p==='object'&&typeof p.result==='string')?p.result
    :(p===undefined||p===null)?firstText()
    :JSON.stringify(p);
  const close=txt.indexOf('</untrusted-data');
  const re=/<untrusted-data-[0-9a-f-]+>/g;
  let m,start=-1;
  while((m=re.exec(txt))!==null){
    if(close>=0&&m.index>close)break;                 // past the payload — trailing mention
    start=m.index+m[0].length;
  }
  if(start>=0)txt=txt.slice(start,close<0?undefined:close);
  return JSON.parse(txt.trim());
}
// Only the columns the UI reads — created_at/updated_at are never rendered and this
// payload is already ~half a megabyte.
const LIVE_SQL=`select json_build_object(
 'apps',(select coalesce(json_agg(a),'[]'::json) from (select job_id,company,role,location,lane,score,
   track,resume,job_url,req_id,found_date,referral_state,status,applied_date,follow_up_by,top_contact,
   legit_flags,notes from applications order by found_date desc, job_id desc) a),
 'contacts',(select coalesce(json_agg(c),'[]'::json) from (select id,name,title,company,application_id,
   persona,focus_area,hook_signal,channel,linkedin_url,email,is_alum,outreach_status,last_touch,
   next_action,notes from contacts order by id) c))::text as data;`;
// Re-read the database at load so the page shows the DB, not the day it was published.
// Pure enhancement: every failure path leaves the baked snapshot on screen.
async function hydrate(){
  if(!MCP)return false;
  try{
    const rows=extractRows(await MCP.callTool(MCP_SERVER,MCP_TOOL,
      {project_id:PROJECT_ID,query:LIVE_SQL},{cache:false}));
    const raw=rows&&rows[0]&&rows[0].data;
    const d=(typeof raw==='string')?JSON.parse(raw):raw;
    if(!d||!Array.isArray(d.apps)||!Array.isArray(d.contacts))throw new Error('unexpected shape');
    if(!d.apps.length)throw new Error('live read returned zero applications — refusing to blank the page');
    APPS=d.apps;CONTACTS=d.contacts;HYDRATED=true;rebind();
    renderPipeDates();renderAppsTools();renderNetTools();rerenderData();
    const st=$('#today-date');if(st)st.textContent=TODAY;
    // A successful read IS the liveness proof, so verifyLive's separate count probe is
    // skipped — one connector call at load instead of two.
    const p=$('#livepill');if(p){p.className='livepill on';
      $('#livetxt').textContent=`live · ${d.apps.length} rows (${esc(MCP_SERVER)})`;}
    const sn=$('#srcnote');
    if(sn)sn.innerHTML+=` <span class="mono" style="font-size:11px;color:var(--faint)">`
      +`· live read: ${APPS.length} applications, ${CONTACTS.length} contacts</span>`;
    return true;
  }catch(e){
    // Keep the snapshot and say so plainly rather than pretending the page is current.
    const st=$('#today-date');if(st)st.textContent=SNAPSHOT_DATE+' (snapshot)';
    const sn=$('#srcnote');
    if(sn)sn.innerHTML+=` <span class="mono" style="font-size:11px;color:var(--due)">`
      +`· showing the ${esc(SNAPSHOT_DATE)} snapshot — live read failed: `
      +esc(((e&&e.code)||'')+' '+((e&&e.message)||'').slice(0,100))+`</span>`;
    return false;
  }
}
// One-shot probe: confirm the live path actually reaches THIS project & table.
// Catches the "green pill but writes vanish" case (wrong/empty project).
async function verifyLive(){
  if(MCP){
    try{
      const n=probeCount(await MCP.callTool(MCP_SERVER,MCP_TOOL,
        {project_id:PROJECT_ID,query:'SELECT count(*)::int AS n FROM applications;'}));
      if(n===0)throw new Error('reached an EMPTY applications table — wrong Supabase project?');
      const p=$('#livepill');if(p){p.className='livepill on';
        // The call answering at all proves the connector is reachable and in-manifest.
        // A count we could not parse is cosmetic — never downgrade the write path for it.
        $('#livetxt').textContent=n===null?`live · connected (${esc(MCP_SERVER)})`:`live · ${n} rows (${esc(MCP_SERVER)})`;}
      return;
    }catch(e){
      const [t,sub]=mcpFail(e);
      if(MCP_DEAD.indexOf((e&&e.code)||'')<0){
        // Reachable-but-odd (transient upstream, or the empty-table warning). Keep the write
        // path; a real edit will surface its own error with the right fix copy.
        const p=$('#livepill');if(p){p.className='livepill on';$('#livetxt').textContent='live · '+esc(MCP_SERVER)+' (unverified)';}
        toast('Could not verify the connection','info',((e&&e.message)||'').slice(0,120)+' — edits will still be attempted');
        return;
      }
      liveOff('<b style="color:#b02a37">'+esc(t)+'.</b> '+esc(sub)+' Edits will stage as SQL below until this is fixed.'
        +'<br><span class="mono" style="font-size:11px">probe: '+esc(((e&&e.code)||'')+' '+((e&&e.message)||'').slice(0,120))+'</span>',sub);
      MCP=null;
      return;
    }
  }
  if(CONNECTOR){
    try{
      const r=await window.cowork.callMcpTool(resolveSupaTool(),{project_id:PROJECT_ID,query:'SELECT count(*)::int AS n FROM applications;'});
      const txt=(r&&r.content&&r.content[0]&&r.content[0].text)||'';
      const m=txt.match(/"n"\s*:\s*(-?\d+)/); const n=m?parseInt(m[1],10):null;
      if(r&&r.isError||n===null)throw new Error((r&&r.content&&r.content[0]&&r.content[0].text)||'probe failed');
      if(n===0)throw new Error('connector reached an EMPTY applications table — likely bound to the wrong Supabase project');
      const p=$('#livepill');if(p){p.className='livepill on';$('#livetxt').textContent=`live · ${n} rows (connector)`;}
    }catch(e){
      liveOff('<b style="color:#b02a37">Live bridge connected but writes are not reaching Supabase.</b> The connector is stale or bound to a different project ('+esc(PROJECT_ID)+'). Edits will stage as SQL below until fixed.<br><span class="mono" style="font-size:11px">probe: '+esc((e&&e.message||'').slice(0,140))+'</span>','edits will stage until the connector is fixed');
    }
  }
}
function rerenderData(){renderKPIs();renderDist();renderRecent();renderPipeDates();if(!$('#pipe-day').classList.contains('hide')){renderList();renderDetail();}renderAppsTable();renderNetTable();renderTriage();}
async function commit(sql,optimistic,okMsg,sel,prev){
  try{const {live,via}=await applyOps(sql);optimistic();rerenderData();
    toast(live?okMsg+' — saved':okMsg+' — staged',live?'ok':'info',live?'via '+via:'stage clears on next refresh');
  }catch(e){
    const [t,sub,ambiguous]=mcpFail(e);
    toast(t,ambiguous?'info':'err',sub);
    // Ambiguous outcome: leave the optimistic value alone and let the user reload,
    // rather than showing a revert that may contradict what Supabase actually stored.
    if(!ambiguous&&sel&&prev!=null)sel.value=prev;
  }
}
function doStatus(id,ns,sel,prev){
  const sql=`UPDATE applications SET status='${ns}'`+(ns==='applied'?`, applied_date='${TODAY}'`:'')+` WHERE job_id='${id}';`;
  commit(sql,()=>{const a=appById[id];a.status=ns;if(ns==='applied'&&!a.applied_date)a.applied_date=TODAY;},`${id} → ${ns}`,sel,prev);
}
function doFlip(id){
  const sql=`UPDATE applications SET lane='direct-apply', referral_state='direct-apply', status='pending' WHERE job_id='${id}';`;
  commit(sql,()=>{const a=appById[id];a.lane='direct-apply';a.referral_state='direct-apply';a.status='pending';},`${id} flipped to direct-apply`);
}
function doNote(id,txt){
  const sql=`UPDATE applications SET notes='${(txt||'').replace(/'/g,"''")}' WHERE job_id='${id}';`;
  commit(sql,()=>{appById[id].notes=txt;},`${id} note saved`);
}
function doOutreach(c,ns,sel,prev){
  let sql=`UPDATE contacts SET outreach_status='${ns}', last_touch='${TODAY}' WHERE name='${(c.name||'').replace(/'/g,"''")}' AND company='${(c.company||'').replace(/'/g,"''")}';`;
  const also=(ns==='referral_secured'&&c.application_id);
  if(also){sql+=`\nUPDATE applications SET referral_state='referred' WHERE job_id='${c.application_id}';`;}
  commit(sql,()=>{c.outreach_status=ns;c.last_touch=TODAY;if(also&&appById[c.application_id])appById[c.application_id].referral_state='referred';},`${c.name} → ${ns}`,sel,prev);
}

/* ---- Dashboard ---- */
// Two funnels, not one. The referral-lane cards (Referral Found/Applied/Pending, Overdue
// Follow-ups) were removed 2026-08-22 — the lane is retired and three of them read zero.
function renderKPIs(){
  const st=s=>APPS.filter(a=>a.status===s).length;
  const cs=s=>CONTACTS.filter(c=>c.outreach_status===s).length;
  // A reply is any contact who answered; referrals are the subset that converted.
  const REPLIED=['replied','positive','meeting_scheduled','negative','referral_asked','referral_secured'];
  const replied=CONTACTS.filter(c=>REPLIED.indexOf(c.outreach_status)>=0).length;
  // Everyone who got past the invite: accepted, or any later state.
  const ACCEPTED=['accepted'].concat(REPLIED);
  const accepted=CONTACTS.filter(c=>ACCEPTED.indexOf(c.outreach_status)>=0).length;
  const groups=[
    ['Job Applications',[
      {n:APPS.length,l:'Sourced'},
      {n:st('applied'),l:'Applied',cls:'accent'},
      {n:st('shortlisted'),l:'Shortlisted'},
      {n:st('interviewing')+st('offer'),l:'Interviews'},
      {n:st('rejected'),l:'Rejected'}]],
    ['Networking',[
      {n:CONTACTS.length,l:'Sourced'},
      {n:cs('sent'),l:'Sent',cls:'accent'},
      {n:accepted,l:'Accepted'},
      {n:replied,l:'Replied'},
      {n:cs('referral_secured'),l:'Referrals Found'}]]];
  $('#kpis').innerHTML=groups.map(([title,cards])=>
    `<div class="kpigroup"><h4>${title}</h4><div class="kpirow" style="--cols:${cards.length}">`
    +cards.map(c=>`<div class="kpi ${c.cls||''}"><div class="n">${c.n}</div><div class="l">${esc(c.l)}</div></div>`).join('')
    +`</div></div>`).join('');
}
function renderDist(){
  const laneColor={referral:'var(--referral)','direct-apply':'var(--direct)',staffing:'var(--staffing)',outreach:'var(--outreach)'};
  const stColor={'referral-pending':'var(--due)','pending':'#3c4b57','applied':'var(--pos)','interviewing':'var(--accent)'};
  const trackColor={T1:'#08417a',T2:'#3c4b57',T3:'#6f5416'};
  const tot=APPS.length||1,count=f=>APPS.filter(f).length;
  // Data-driven: only render lanes/tracks that actually exist, so retired values
  // (old referral lane, retired T3) vanish once the data no longer carries them.
  const distinct=k=>[...new Set(APPS.map(a=>a[k]).filter(Boolean))];
  const bar=(lab,val,color)=>`<div class="drow"><span class="lab">${lab}</span><span class="track"><i style="width:${(val/tot)*100}%;background:${color}"></i></span><span class="val">${val}</span></div>`;
  let h='<div class="grp-lab">By lane</div>';distinct('lane').forEach(l=>h+=bar(l,count(a=>a.lane===l),laneColor[l]||'var(--drop)'));
  h+='<div class="grp-lab">By status</div>';['pending','applied','shortlisted','interviewing'].forEach(s=>h+=bar(s,count(a=>a.status===s),stColor[s]||'var(--drop)'));
  h+='<div class="grp-lab">By track</div>';distinct('track').sort().forEach(t=>h+=bar(t,count(a=>a.track===t),trackColor[t]||'var(--drop)'));
  $('#dist').innerHTML=h;}
function renderRecent(){const rows=[...APPS].sort((a,b)=>(b.found_date||'').localeCompare(a.found_date||'')).slice(0,8);
  $('#recent').innerHTML=rows.map(a=>`<div class="recent-row" data-id="${esc(a.job_id)}"><span class="recent-date">${esc((a.found_date||'').slice(5))}</span>
    <span class="recent-title">${esc(a.company)} <span style="color:var(--faint);font-weight:500">· ${esc(a.role)}</span></span>
    <span class="recent-n"><span class="stagepill st-${a.status}">${esc(a.status)}</span></span></div>`).join('');
  $$('#recent .recent-row').forEach(r=>r.onclick=()=>openPipelineDate(appById[r.dataset.id].found_date,r.dataset.id));}

/* ---- Pipeline ---- */
let selApp=null, pipeDate=null;
function datesList(){const m={};APPS.forEach(a=>{const d=a.found_date||'(no date)';(m[d]=m[d]||[]).push(a);});
  return Object.keys(m).sort((a,b)=>b.localeCompare(a)).map(d=>({date:d,apps:m[d]}));}
function renderPipeDates(){const groups=datesList();
  const activeAll=APPS.filter(a=>!HIDDEN_STATUSES.includes(a.status)).length, dropAll=APPS.length-activeAll;
  const allRow=`<div class="recent-row" data-date="__ALL__"><span class="recent-date">ALL</span><span class="recent-title"><b>All applications</b></span><span class="recent-n">${activeAll} apps${dropAll?` · ${dropAll} dropped`:''}</span></div>`;
  $('#pipe-dates').innerHTML=`<div class="pipe-count">Pick a day (found date) or view all</div><div class="card block" style="padding:6px 16px">`+allRow+groups.map(g=>{
    const act=g.apps.filter(a=>!HIDDEN_STATUSES.includes(a.status));
    const ref=act.filter(a=>a.lane==='referral').length,dir=act.filter(a=>a.lane==='direct-apply').length,od=act.filter(isOverdue).length,drp=g.apps.length-act.length;
    return `<div class="recent-row" data-date="${esc(g.date)}"><span class="recent-date">${esc(g.date.slice(5))}</span><span class="recent-title">${esc(g.date)}</span>
      <span class="recent-n">${act.length} apps · ${ref} ref / ${dir} direct${drp?` · ${drp} dropped`:''}${od?` · <span class="od-tag">${od} overdue</span>`:''}</span></div>`;}).join('')+`</div>`;
  $$('#pipe-dates .recent-row').forEach(r=>r.onclick=()=>openPipelineDate(r.dataset.date));}
function openPipelineDate(date,appId){gotoTab('pipeline');pipeDate=date;selApp=appId||null;
  pf.q='';pf.lane='all';pf.track='all';pf.status='all';pf.od=false;
  $('#pipe-dates').classList.add('hide');$('#pipe-day').classList.remove('hide');renderToolbar();renderList();renderDetail();}
function backToDates(){pipeDate=null;selApp=null;$('#pipe-dates').classList.remove('hide');$('#pipe-day').classList.add('hide');}
const pf={q:'',lane:'all',track:'all',status:'all',od:false};
function renderToolbar(){
  const dV=k=>[...new Set(APPS.map(a=>a[k]).filter(Boolean))];
  const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
  const lanes=[['all','All lanes'],...dV('lane').map(l=>[l,cap(l)])];
  const tracks=[['all','All'],...dV('track').sort().map(t=>[t,t])];
  const sts=[['all','All active'],['pending','Pending'],['applied','Applied'],['shortlisted','Shortlisted'],['interviewing','Interviewing'],['dropped','Dropped']];
  const label=pipeDate==='__ALL__'?'All applications':pipeDate;
  $('#pipe-toolbar').innerHTML=`<button class="chipbtn" id="pipe-back">← All dates</button><span class="eyebrow" style="margin-right:auto">${esc(label)}</span>
    <input type="text" id="pq" placeholder="Search company, role, contact, job id…" value="${esc(pf.q)}">
    ${lanes.map(([k,l])=>`<button class="chipbtn ${pf.lane===k?'on':''}" data-lane="${k}">${l}</button>`).join('')}
    ${tracks.map(([k,l])=>`<button class="chipbtn ${pf.track===k?'on':''}" data-track="${k}">${l}</button>`).join('')}
    ${sts.map(([k,l])=>`<button class="chipbtn ${pf.status===k?'on':''}" data-status="${k}">${l}</button>`).join('')}
    <button class="chipbtn warn ${pf.od?'on':''}" id="od-btn">Overdue only</button>`;
  $('#pipe-back').onclick=backToDates;$('#pq').oninput=e=>{pf.q=e.target.value;renderList();};
  $$('[data-lane]').forEach(b=>b.onclick=()=>{pf.lane=b.dataset.lane;renderToolbar();renderList();});
  $$('[data-track]').forEach(b=>b.onclick=()=>{pf.track=b.dataset.track;renderToolbar();renderList();});
  $$('[data-status]').forEach(b=>b.onclick=()=>{pf.status=b.dataset.status;renderToolbar();renderList();});
  $('#od-btn').onclick=()=>{pf.od=!pf.od;renderToolbar();renderList();};}
function pipeFiltered(){const q=pf.q.trim().toLowerCase();
  let rows=APPS.filter(a=>{
    if(pipeDate&&pipeDate!=='__ALL__'&&(a.found_date||'(no date)')!==pipeDate)return false;
    if(pf.lane!=='all'&&a.lane!==pf.lane)return false;if(pf.track!=='all'&&a.track!==pf.track)return false;
    if(pf.status==='all'){if(HIDDEN_STATUSES.includes(a.status))return false;}else if(a.status!==pf.status)return false;
    if(pf.od&&!isOverdue(a))return false;
    if(q){const names=contactsFor(a.job_id).map(c=>c.name).join(' ');const hay=[a.company,a.role,a.location,a.job_id,a.top_contact,names].filter(Boolean).join(' ').toLowerCase();if(!hay.includes(q))return false;}
    return true;});
  rows.sort((x,y)=>{const A=x.follow_up_by||'9999',B=y.follow_up_by||'9999';if(A!==B)return A<B?-1:1;return (y.score==null?-1:y.score)-(x.score==null?-1:x.score);});return rows;}
function renderList(){const rows=pipeFiltered();$('#pipe-count').textContent=`${rows.length} application${rows.length===1?'':'s'}`;
  $('#pipe-list').innerHTML=rows.map(a=>{const od=isOverdue(a),due=isDue(a);
    return `<div class="plrow ${selApp===a.job_id?'sel':''} ${od?'od':''}" data-id="${esc(a.job_id)}"><span class="pr-date">${esc((a.found_date||'').slice(5))}</span>
      <div class="pr-main"><div class="pr-co">${esc(a.company)}</div><div class="pr-role">${esc(a.role)}</div>
        <div class="pr-meta"><span class="chip ${(a.track||'').toLowerCase()}">${esc(a.track||'—')}</span><span class="chip ${a.lane}">${esc(a.lane)}</span><span class="stagepill st-${a.status}">${esc(a.status)}</span>${od?'<span class="od-tag">OVERDUE</span>':due?'<span class="due-tag">DUE</span>':''}</div></div>
      <span class="pr-score score-pill ${scoreClass(a.score)}">${a.score==null?'—':a.score}</span></div>`;}).join('')||`<div class="empty">No applications match this filter.</div>`;
  $$('#pipe-list .plrow').forEach(r=>r.onclick=()=>{selApp=r.dataset.id;renderList();renderDetail();});}
function renderDetail(){const a=appById[selApp];
  if(!a){$('#pipe-detail').innerHTML='<div class="empty">Select an application to see its full record.</div>';return;}
  const recKw = encodeURIComponent(`"${a.company}" recruiter OR "talent acquisition"`);
  const peerRole = (a.role||'').toLowerCase().includes('process') ? 'process engineer' : (a.role||'').toLowerCase().includes('manufacturing') ? 'manufacturing engineer' : (a.role||'').toLowerCase().includes('mrb') ? 'mrb engineer' : 'quality engineer';
  const peerKw = encodeURIComponent(`"${a.company}" ${peerRole}`);
  const recUrl = `https://www.linkedin.com/search/results/people/?keywords=${recKw}&origin=GLOBAL_SEARCH_HEADER`;
  const peerUrl = `https://www.linkedin.com/search/results/people/?keywords=${peerKw}&origin=GLOBAL_SEARCH_HEADER`;

  const searchButtons = `<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
    <a href="${recUrl}" target="_blank" rel="noopener" class="chipbtn" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:6px 12px;background:var(--accent-soft);color:var(--accent-ink);border-color:var(--accent)">
      🤝 Search Recruiters on LinkedIn ↗
    </a>
    <a href="${peerUrl}" target="_blank" rel="noopener" class="chipbtn" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:6px 12px;background:#e2f2e8;color:var(--pos);border-color:#bce0c9">
      👥 Search Team Leads (${peerRole}) ↗
    </a>
  </div>`;

  const contactsTable = cs.length ? `<div class="tbl-scroll" style="margin-bottom:8px"><table><thead><tr><th>Contact</th><th>Persona</th><th>Hook / Notes</th><th>Outreach</th><th>Link</th></tr></thead><tbody>
    ${cs.map(c=>`<tr><td><b>${esc(c.name)}</b>${c.is_alum?' <span class="chip alum">alum</span>':''}${c.title?`<div style="color:var(--muted);font-size:11.5px;font-weight:500">${esc(c.title)}</div>`:''}</td>
      <td style="font-size:11.5px;color:var(--muted);font-weight:600">${esc(c.persona||'—')}</td>
      <td style="font-size:12px;color:var(--ink);font-weight:500;max-width:320px;line-height:1.3">${esc(c.notes||c.hook_signal||'—')}</td>
      <td><select class="mini" data-oc="${esc(c.name)}||${esc(c.company)}">${OUTREACH_STATUSES.map(s=>`<option ${s===c.outreach_status?'selected':''}>${s}</option>`).join('')}</select></td>
      <td>${c.linkedin_url?`<a href="${esc(c.linkedin_url)}" target="_blank" rel="noopener">↗</a>`:'—'}</td></tr>`).join('')}</tbody></table></div>` : '<p style="color:var(--faint);font-weight:500;margin-bottom:6px">No specific individual contacts logged in database yet.</p>';

  const contactsBlock = `<div class="dsec"><h4>Sourced contacts ${cs.length ? `(${cs.length})` : ''}</h4>${contactsTable}${searchButtons}</div>`;
  $('#pipe-detail').innerHTML=`<div class="dhead"><div class="dname">${esc(a.company)}</div><div class="drole">${esc(a.role)}${a.location?' — '+esc(a.location):''}</div>
      <div class="dmeta"><span class="chip ${(a.track||'').toLowerCase()}">${esc(a.track||'—')}</span><span class="chip ${a.lane}">${esc(a.lane)}</span>
        <span class="score-pill ${scoreClass(a.score)}">${a.score==null?'not gate-scored':'score '+a.score}</span><span class="mono" style="font-size:11.5px;color:var(--faint)">${esc(a.job_id)}</span></div></div>
    <div class="dsec"><h4>Status &amp; disposition</h4><div class="field-row"><select class="stageselect" id="st-sel">${APP_STATUSES.map(s=>`<option ${s===a.status?'selected':''}>${s}</option>`).join('')}</select>
      ${od?`<button class="flip" id="flip-btn">Flip → direct-apply</button>`:''}</div>${a.legit_flags?`<span class="flag">⚠ ${esc(a.legit_flags)}</span>`:''}</div>
    <div class="dsec"><h4>Key fields</h4><div class="kv">
      <span class="k">Referral state</span><span>${esc(a.referral_state)}</span><span class="k">Found</span><span class="mono">${esc(a.found_date)||'—'}</span>
      <span class="k">Follow-up by</span><span class="mono">${a.follow_up_by?esc(a.follow_up_by)+(od?' <span class="od-tag">OVERDUE</span>':isDue(a)?' <span class="due-tag">DUE</span>':''):'—'}</span>
      <span class="k">Applied</span><span class="mono">${esc(a.applied_date)||'—'}</span><span class="k">Top contact</span><span>${esc(a.top_contact)||'—'}</span>
      <span class="k">Resume</span><span class="mono" style="font-size:12px">${esc(a.resume)||'—'}</span></div></div>
    ${contactsBlock}
    <div class="dsec ${a.status==='dropped'?'drop':''}"><h4>${a.status==='dropped'?'Drop review — why dropped':'Notes'}</h4>
      <textarea class="notebox" id="note-box" rows="3" placeholder="Why did you drop this? What was the signal to learn from? (feeds learning_log.md)">${esc(a.notes||'')}</textarea>
      <div class="field-row" style="margin-top:8px"><button class="savebtn" id="note-save">Save note</button>
        <span class="note-hint">Saved to Supabase · synced into learning_log.md on next refresh</span></div></div>
    ${a.job_url?`<div class="dsec linkline"><h4>Posting</h4><a href="${esc(a.job_url)}" target="_blank" rel="noopener">${esc(a.req_id?('req '+a.req_id+' ↗'):'open posting ↗')}</a></div>`:''}`;
  const ss=$('#st-sel');ss.onchange=()=>{const prev=a.status;doStatus(a.job_id,ss.value,ss,prev);};
  const fb=$('#flip-btn');if(fb)fb.onclick=()=>doFlip(a.job_id);
  const nbtn=$('#note-save');if(nbtn)nbtn.onclick=()=>doNote(a.job_id,$('#note-box').value);
  $$('#pipe-detail [data-oc]').forEach(sel=>{const prev=sel.value;sel.onchange=()=>{const [nm,co]=sel.dataset.oc.split('||');const c=CONTACTS.find(x=>x.name===nm&&x.company===co);if(c)doOutreach(c,sel.value,sel,prev);};});}

/* ---- Tracker toggle ---- */
$('#tg-apps').onclick=()=>{$('#tg-apps').setAttribute('aria-pressed','true');$('#tg-net').setAttribute('aria-pressed','false');$('#trk-apps').classList.remove('hide');$('#trk-net').classList.add('hide');};
$('#tg-net').onclick=()=>{$('#tg-net').setAttribute('aria-pressed','true');$('#tg-apps').setAttribute('aria-pressed','false');$('#trk-net').classList.remove('hide');$('#trk-apps').classList.add('hide');};

/* ---- Job Applications table ---- */
const af={lane:'',track:'',status:'',co:'',smin:'',smax:'',od:false};
let appsSort={k:'follow_up_by',dir:1};
function renderAppsTools(){
  $('#apps-tools').innerHTML=`<label>Lane</label><select id="a-lane"><option value="">all</option>${[...new Set(APPS.map(a=>a.lane).filter(Boolean))].map(l=>`<option>${esc(l)}</option>`).join('')}</select>
    <label>Track</label><select id="a-track"><option value="">all</option>${[...new Set(APPS.map(a=>a.track).filter(Boolean))].sort().map(t=>`<option>${esc(t)}</option>`).join('')}</select>
    <label>Status</label><select id="a-status"><option value="">all</option>${APP_STATUSES.map(s=>`<option>${s}</option>`).join('')}</select>
    <label>Company</label><input type="text" id="a-co" placeholder="search…" value="${esc(af.co)}">
    <label>Score</label><input type="number" id="a-smin" placeholder="min"> – <input type="number" id="a-smax" placeholder="max">
    <label class="toggle"><input type="checkbox" id="a-od"> Overdue only</label><button class="chipbtn" id="a-reset">Reset</button>`;
  $('#a-lane').value=af.lane;$('#a-track').value=af.track;$('#a-status').value=af.status;$('#a-smin').value=af.smin;$('#a-smax').value=af.smax;$('#a-od').checked=af.od;
  ['a-lane','a-track','a-status','a-co','a-smin','a-smax'].forEach(id=>$('#'+id).oninput=()=>{af.lane=$('#a-lane').value;af.track=$('#a-track').value;af.status=$('#a-status').value;af.co=$('#a-co').value;af.smin=$('#a-smin').value;af.smax=$('#a-smax').value;renderAppsTable();});
  $('#a-od').onchange=()=>{af.od=$('#a-od').checked;renderAppsTable();};
  $('#a-reset').onclick=()=>{Object.assign(af,{lane:'',track:'',status:'',co:'',smin:'',smax:'',od:false});renderAppsTools();renderAppsTable();};}
function renderAppsTable(){
  let rows=APPS.filter(a=>{if(af.lane&&a.lane!==af.lane)return false;if(af.track&&a.track!==af.track)return false;if(af.status&&a.status!==af.status)return false;
    if(af.co&&!(a.company||'').toLowerCase().includes(af.co.toLowerCase()))return false;
    if(af.smin!==''&&(a.score==null||a.score<+af.smin))return false;if(af.smax!==''&&(a.score==null||a.score>+af.smax))return false;
    if(af.od&&!isOverdue(a))return false;return true;});
  const {k,dir}=appsSort;
  rows.sort((x,y)=>{let A=x[k],B=y[k];if(k==='follow_up_by'||k==='found_date'||k==='applied_date'){A=A||'9999';B=B||'9999';}if(k==='score'){A=A==null?-1:A;B=B==null?-1:B;}if(A<B)return -dir;if(A>B)return dir;return (y.score==null?-1:y.score)-(x.score==null?-1:x.score);});
  $('#apps-count').textContent=`${rows.length} application${rows.length===1?'':'s'}`;
  const cols=[['job_id','Job ID'],['found_date','Found'],['company','Company'],['role','Role'],['location','Loc'],['lane','Lane'],['score','Score'],['track','Track'],['referral_state','Ref state'],['status','Status'],['follow_up_by','Follow-up'],['applied_date','Applied'],['top_contact','Top contact'],['resume','Resume'],['job_url','URL'],['notes','Notes']];
  $('#apps-table').innerHTML=`<thead><tr>${cols.map(([k,l])=>`<th data-k="${k}">${l}</th>`).join('')}</tr></thead><tbody>`+
    rows.map(a=>{const od=isOverdue(a),due=isDue(a);
      return `<tr class="${od?'od':''}"><td class="mono" style="font-size:11.5px">${esc(a.job_id)}</td>
        <td class="mono" style="white-space:nowrap;font-size:12px">${esc(a.found_date)||'—'}</td><td style="font-weight:700">${esc(a.company)}</td>
        <td style="min-width:170px">${esc(a.role)}</td><td style="font-size:12px">${esc(a.location)||'—'}</td>
        <td><span class="chip ${a.lane}">${esc(a.lane)}</span></td><td class="score-pill ${scoreClass(a.score)}">${a.score==null?'—':a.score}</td>
        <td>${a.track?`<span class="chip ${a.track.toLowerCase()}">${esc(a.track)}</span>`:'—'}</td>
        <td style="font-size:12px;color:var(--muted);font-weight:600">${esc(a.referral_state)}</td>
        <td><select class="mini" data-st="${esc(a.job_id)}">${APP_STATUSES.map(s=>`<option ${s===a.status?'selected':''}>${s}</option>`).join('')}</select></td>
        <td class="mono" style="white-space:nowrap;font-size:12px">${a.follow_up_by?esc(a.follow_up_by)+(od?' <span class="od-tag">OD</span>':due?' <span class="due-tag">DUE</span>':''):'—'}</td>
        <td class="mono" style="font-size:12px">${esc(a.applied_date)||'—'}</td><td style="font-size:11.5px;color:var(--muted);max-width:150px">${esc(a.top_contact)||'—'}</td>
        <td class="mono" style="font-size:11px;max-width:150px" title="${esc(a.resume)}">${a.resume?esc(a.resume):'—'}</td>
        <td>${a.job_url?`<a href="${esc(a.job_url)}" target="_blank" rel="noopener">↗</a>`:'—'}</td>
        <td style="font-size:11.5px;color:var(--muted);max-width:220px;font-weight:500">${esc(a.notes)||'—'}</td></tr>`;}).join('')+`</tbody>`;
  $$('#apps-table [data-st]').forEach(sel=>{const prev=sel.value;sel.onchange=()=>doStatus(sel.dataset.st,sel.value,sel,prev);});
  $$('#apps-table th[data-k]').forEach(t=>t.onclick=()=>{const k=t.dataset.k;appsSort.dir=(appsSort.k===k?-appsSort.dir:1);appsSort.k=k;renderAppsTable();});}

/* ---- Networking table ---- */
const nf={co:'',st:'',persona:'',post:'',alum:false,q:''};
let netSort={k:'name',dir:1};
function renderNetTools(){
  const cos=[...new Set(CONTACTS.map(c=>c.company).filter(Boolean))].sort();
  const pers=[...new Set(CONTACTS.map(c=>c.persona).filter(Boolean))].sort();
  const posts=[...new Set(CONTACTS.map(c=>c.application_id).filter(Boolean))].sort();
  $('#net-tools').innerHTML=`<label>Company</label><select id="n-co"><option value="">all</option>${cos.map(c=>`<option ${nf.co===c?'selected':''}>${esc(c)}</option>`).join('')}</select>
    <label>Outreach</label><select id="n-st"><option value="">all</option>${OUTREACH_STATUSES.map(s=>`<option ${nf.st===s?'selected':''}>${s}</option>`).join('')}</select>
    <label>Persona</label><select id="n-pe"><option value="">all</option>${pers.map(p=>`<option ${nf.persona===p?'selected':''}>${esc(p)}</option>`).join('')}</select>
    <label>Posting</label><select id="n-po"><option value="">all</option>${posts.map(p=>`<option value="${esc(p)}" ${nf.post===p?'selected':''}>${esc(p)}</option>`).join('')}</select>
    <label class="toggle"><input type="checkbox" id="n-al" ${nf.alum?'checked':''}> alumni only</label><input type="text" id="n-q" placeholder="name…" value="${esc(nf.q)}"><button class="chipbtn" id="n-reset">Reset</button>`;
  $('#n-co').onchange=e=>{nf.co=e.target.value;renderNetTable();};$('#n-st').onchange=e=>{nf.st=e.target.value;renderNetTable();};
  $('#n-pe').onchange=e=>{nf.persona=e.target.value;renderNetTable();};$('#n-po').onchange=e=>{nf.post=e.target.value;renderNetTable();};
  $('#n-al').onchange=e=>{nf.alum=e.target.checked;renderNetTable();};$('#n-q').oninput=e=>{nf.q=e.target.value;renderNetTable();};
  $('#n-reset').onclick=()=>{Object.assign(nf,{co:'',st:'',persona:'',post:'',alum:false,q:''});renderNetTools();renderNetTable();};}
function renderNetTable(){const q=nf.q.trim().toLowerCase();
  let rows=CONTACTS.filter(c=>{if(c.outreach_status==='dropped')return false;if(nf.co&&c.company!==nf.co)return false;if(nf.st&&c.outreach_status!==nf.st)return false;if(nf.persona&&c.persona!==nf.persona)return false;if(nf.post&&c.application_id!==nf.post)return false;if(nf.alum&&!c.is_alum)return false;if(q&&!(c.name||'').toLowerCase().includes(q))return false;return true;});
  const {k,dir}=netSort;rows.sort((x,y)=>{let A=(x[k]==null?'':x[k]),B=(y[k]==null?'':y[k]);if(A<B)return -dir;if(A>B)return dir;return 0;});
  $('#net-count').textContent=`${rows.length} contact${rows.length===1?'':'s'}`;
  const cols=[['name','Name'],['title','Title'],['company','Company'],['application_id','Posting'],['persona','Persona'],['focus_area','Focus'],['hook_signal','Hook'],['channel','Channel'],['outreach_status','Outreach'],['is_alum','Alum'],['linkedin_url','LinkedIn'],['email','Email'],['notes','Notes']];
  $('#net-table').innerHTML=`<thead><tr>${cols.map(([k,l])=>`<th data-k="${k}">${l}</th>`).join('')}</tr></thead><tbody>`+
    rows.map(c=>`<tr><td style="font-weight:700">${esc(c.name)}</td><td style="font-size:12px;color:var(--muted);max-width:180px;font-weight:500">${esc(c.title)||'—'}</td>
      <td>${esc(c.company)||'—'}</td><td class="mono" style="font-size:11px">${c.application_id?esc(c.application_id):'—'}</td>
      <td style="font-size:11.5px;color:var(--muted);font-weight:600">${esc(c.persona)||'—'}</td><td style="font-size:11.5px;color:var(--muted)">${esc(c.focus_area)||'—'}</td>
      <td style="font-size:11.5px;color:var(--muted);max-width:200px;font-weight:500">${esc(c.hook_signal)||'—'}</td><td style="font-size:11.5px">${esc(c.channel)||'—'}</td>
      <td><select class="mini" data-oc="${esc(c.name)}||${esc(c.company)}">${OUTREACH_STATUSES.map(s=>`<option ${s===c.outreach_status?'selected':''}>${s}</option>`).join('')}</select></td>
      <td>${c.is_alum?'<span class="chip alum">alum</span>':'<span style="color:var(--faint)">—</span>'}</td>
      <td>${c.linkedin_url?`<a href="${esc(c.linkedin_url)}" target="_blank" rel="noopener">↗</a>`:'—'}</td>
      <td style="font-size:11px;max-width:150px;word-break:break-all">${c.email?`<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>`:'—'}</td>
      <td style="font-size:11px;color:var(--muted);max-width:200px;font-weight:500">${esc(c.notes)||'—'}</td></tr>`).join('')+`</tbody>`;
  $$('#net-table [data-oc]').forEach(sel=>{const prev=sel.value;sel.onchange=()=>{const [nm,co]=sel.dataset.oc.split('||');const c=CONTACTS.find(x=>x.name===nm&&x.company===co);if(c)doOutreach(c,sel.value,sel,prev);};});
  $$('#net-table th[data-k]').forEach(t=>t.onclick=()=>{const k=t.dataset.k;netSort.dir=(netSort.k===k?-netSort.dir:1);netSort.k=k;renderNetTable();});}

/* ---- Triage ---- */
// Follow-up queue. Was keyed on applications.status='referral-pending', which the
// retired referral lane left at zero rows — three permanently empty sections. It now
// tracks the thing that actually goes stale: contacts you've reached out to.
const NUDGE_DAYS=7;
function daysSince(d){if(!d)return null;const t=Date.parse(d+'T00:00:00Z');
  if(isNaN(t))return null;return Math.floor((Date.parse(TODAY+'T00:00:00Z')-t)/86400000);}
// next_action is a manual snooze: set it to park a card until that date.
const snoozed=c=>!!c.next_action&&c.next_action>TODAY;
const liveApp=a=>!!a&&HIDDEN_STATUSES.indexOf(a.status)<0;
function renderTriage(){
  const live=CONTACTS.filter(c=>c.outreach_status!=='dropped'&&!snoozed(c));
  // 'accepted' = connected but no conversation yet — the case that most needs a nudge.
  // 'not_accepted' is deliberately absent: an unaccepted invite can only be withdrawn.
  const NUDGEABLE=['sent','accepted'];
  const nudge=live.filter(c=>NUDGEABLE.indexOf(c.outreach_status)>=0&&(daysSince(c.last_touch)==null||daysSince(c.last_touch)>=NUDGE_DAYS))
    .sort((a,b)=>(a.last_touch||'').localeCompare(b.last_touch||''));
  const OWED=['replied','positive','meeting_scheduled','referral_asked'];
  const owe=live.filter(c=>OWED.indexOf(c.outreach_status)>=0)
    .sort((a,b)=>(a.last_touch||'').localeCompare(b.last_touch||''));
  // Sourced but never contacted, and only where the role is still worth the outreach.
  const cold=live.filter(c=>c.outreach_status==='sourced'&&(a=>liveApp(a)&&(a.score||0)>70)(appById[c.application_id]))
    .sort((a,b)=>((appById[b.application_id]||{}).score||0)-((appById[a.application_id]||{}).score||0));

  const card=(c,cls,badge,col)=>{const a=appById[c.application_id];
    const age=daysSince(c.last_touch);
    const role=a?`${esc(a.company)} — ${esc(a.role)}`:esc(c.company||'no linked role');
    const who=c.linkedin_url?`<a href="${esc(c.linkedin_url)}" target="_blank" rel="noopener">${esc(c.name)}</a>`:esc(c.name);
    // The profile URL is always shown, not just wrapped around the name: this queue is where
    // you verifies who each contact actually is before setting a status, and a bare name is
    // not verifiable. The 13 contacts with no URL say so explicitly — that absence is itself
    // the signal to drop them.
    const link=c.linkedin_url
      ? `<a class="plink" href="${esc(c.linkedin_url)}" target="_blank" rel="noopener" title="${esc(c.linkedin_url)}">${esc(String(c.linkedin_url).replace(/^https?:\/\/(www\.)?/,'').replace(/\/$/,''))}</a>`
      : `<span class="plink none">no profile URL — can't verify</span>`;
    return `<div class="tcard ${cls}"><div>
      <div class="h">${who} <span class="mono" style="color:var(--faint);font-size:11.5px;font-weight:600">${esc(c.persona||'')}</span></div>
      <div class="meta">${esc(c.title||'')}${c.title&&a?' · ':''}${role}${a&&a.score!=null?' · score '+a.score:''}</div>
      <div class="plinkrow">${link}</div>
      <div class="wait">${badge} ${age==null?'never touched':age+' day'+(age===1?'':'s')+' since last touch'}. ${esc(c.notes||'')}</div></div>
      <div class="act"><div class="fu" style="color:${col}">${esc(c.last_touch||'—')}</div>
        <select class="mini" data-oc="${esc(c.name||'')}||${esc(c.company||'')}">${OUTREACH_STATUSES.map(s=>`<option ${s===c.outreach_status?'selected':''}>${s}</option>`).join('')}</select>
        <button class="flip" data-snooze="${esc(c.name||'')}||${esc(c.company||'')}">Snooze 7d</button></div></div>`;};

  const sec=(title,note,list,cls,badge,col,empty)=>`<div class="tsec"><h3>${title} <span class="c">${note} (${list.length})</span></h3>`
    +(list.length?list.map(c=>card(c,cls,badge,col)).join(''):`<div class="empty">${empty}</div>`)+'</div>';
  $('#triage-body').innerHTML=
     sec('Nudge due',`sent or accepted, no reply, ${NUDGE_DAYS}+ days cold`,nudge,'od','COLD ·','var(--danger)','Nobody is waiting on a nudge.')
    +sec('Owe them a reply','they answered, or an ask is pending',owe,'due','OPEN ·','var(--due)','No open threads.')
    +sec('Never contacted','sourced on a live role above 70',cold,'','SOURCED ·','var(--muted)','Every sourced contact has been actioned.');

  $$('#triage-body [data-oc]').forEach(sel=>{const prev=sel.value;
    sel.onchange=()=>{const [nm,co]=sel.dataset.oc.split('||');
      const c=CONTACTS.find(x=>(x.name||'')===nm&&(x.company||'')===co);
      if(c)doOutreach(c,sel.value,sel,prev);};});
  $$('#triage-body [data-snooze]').forEach(b=>b.onclick=()=>{const [nm,co]=b.dataset.snooze.split('||');
    const c=CONTACTS.find(x=>(x.name||'')===nm&&(x.company||'')===co);if(c)doSnooze(c,NUDGE_DAYS);});
}
// Park a card for n days by writing next_action — the column existed but nothing ever
// set it, so the follow-up queue had no way to say "not yet".
function doSnooze(c,days){
  const d=new Date(Date.parse(TODAY+'T00:00:00Z')+days*86400000).toISOString().slice(0,10);
  const sql=`UPDATE contacts SET next_action='${d}' WHERE name='${(c.name||'').replace(/'/g,"''")}' AND company='${(c.company||'').replace(/'/g,"''")}';`;
  commit(sql,()=>{c.next_action=d;},`${c.name} snoozed to ${d}`);
}

// Render the static page first, then resolve the transport and correct the live pill.
initChrome();renderKPIs();renderDist();renderRecent();renderPipeDates();renderAppsTools();renderAppsTable();renderNetTools();renderNetTable();renderTriage();
(async()=>{await initMcp();initChrome();
  // hydrate() both refreshes the data and proves the write path; fall back to the
  // lighter count probe only when it did not run or did not succeed.
  if(!await hydrate())await verifyLive();})();
</script></body></html>
"""

if __name__ == "__main__":
    main()
