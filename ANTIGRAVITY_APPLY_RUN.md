# Running `/apply-run` in Google Antigravity — Setup & Teaching Doc

Last updated: 2026-08-10. Cockpit root: `/Users/sid/Documents/Claude/Projects/Job_Applications`.

> ⚠️ **2026-09-12: everything below about the tracker (Cowork artifact, `index.html`, `job_tracker.artifact.html`, `tracker_data.json`, `./refresh.sh --fetch` as a deploy step, the `Artifact` tool) is OBSOLETE.** The tracker is now `job_tracker.html`, a standalone page that reads Supabase live on every open; Stage 4 only writes rows. See `DAILY_RUN.md` Stage 4.
>
> ⚠️ **SUPERSEDED FOR THE FORTIFY SPRINT.** The current source of truth is **`AGENTS.md`** + **`DAILY_RUN.md`** (dual-track automated fetch, global scope, contacts auto-persisted). This file is the older 2026-08-13 hand-picked-JD / single-lane / "networking is Sid's" playbook — kept for reference. Where the two disagree, follow AGENTS.md. Specifically, two rules below are **OVERRIDDEN**: the GEO GATE (search is now global — US + Europe + Australia; see `fetch_jobs.py --pass=4`) and "Networking is Sid's / never source a contact" (recruiter + team-lead people-search **links** now auto-persist to the Supabase `contacts` table via Stage 4 — Sid still does every outreach/send).

---

## 0. The one thing to understand first

Your pipeline is **not** Claude Code code. It's a stack of **plain-markdown instructions**:

- `DAILY_RUN.md` — the authoritative step-by-step sequence (Steps 1–10).
- `.claude/agents/{fetcher,ranker,customiser,contact-finder}.md` — four role specs.
- `.claude/commands/apply-run.md` — the orchestrator that runs the four roles in order and stops at two human gates.
- `playbook/P1_03…` and `P1_06…` — the resume rules and the scoring rubric.

None of that is Claude-specific logic. The only Claude-specific parts are the **wrappers**: the `Skill`/slash-command mechanism and the `Task` subagent-spawning tool. Antigravity has equivalents for both. So porting = **reuse every `.md` file as-is**, re-point the two MCP tools, and drive the sequence with an Antigravity Workflow instead of a Claude slash command.

You do **not** rewrite the pipeline. You give the same docs to an Antigravity agent and wire up the same tools.

---

## 1. What the pipeline actually does (30-second recap)

```
fetch ──▶ rank ──▶ 🧑 GATE A ──▶ customise ──▶ contact-find ──▶ consolidate ──▶ feed artifact ──▶ 🧑 GATE B
(Apify)   (score)   (shortlist)   (resumes)     (referrals)      daily_run/<today>.md   (Supabase→tracker)
```

- **Fetch** (`fetcher`): free ATS scan + 3 Apify LinkedIn passes (≤ $0.50 total) → dedup vs `seen_jobs.csv` → keyword/seniority screen → `.pipeline/fetched.md`.
- **Rank** (`ranker`): read Sid's hand-picked `JDs/<today>/*.md` (no fetch) → hard gates (visa/experience/salary) → 0–100 per-track score → single-lane routing (**≥50 genuine-QE = Apply / <50 or off-discipline = Drop / ≥60 = flag `networking: recommended`**) → `.pipeline/ranked.md`. *(Referral lane retired 2026-08-13.)*
- **🧑 GATE A** — Sid approves the shortlist and picks which direct-apply rows to pursue.
- **Customise** (`customiser`): tailor the track base `.tex` per P1_03 → `.pipeline/tailored.md`.
- **Contact-Find** (`contact-finder`, referral rows only): drive the `nag` networking runner to discover + rank contacts → `.pipeline/contacts.md`. **No drafts unless Sid asks.**
- **Consolidate**: write `daily_run/<today>.md`; append/update `seen_jobs.csv` + `Lane2_Tracker.md`.
- **Feed artifact**: insert into Supabase → rebuild `tracker_data.json` → `python3 refresh.py`.
- **🧑 GATE B** — report exact next human action. **Claude never applies, never sends.**

---

## 2. Claude Code → Antigravity concept map

Antigravity is the Windsurf team's agent IDE (fork of VS Code, Gemini-3-first, also runs Claude Sonnet). The mechanisms line up almost one-to-one:

| Claude Code thing | Antigravity equivalent | How to port it |
|---|---|---|
| Slash command (`/apply-run`) | **Workflow** (markdown, invoked `/apply-run`) | Paste `apply-run.md` body into a Workflow. |
| Subagents via `Task` tool | **Agents in the Agent Manager** (spawn one per stage) *or* just role-context read by one agent | Simplest: one agent reads each role `.md` and executes it inline, in order. |
| `CLAUDE.md` / memory | **Rules** (always-on or glob-scoped) | Put the hard guardrails in a Rules file. |
| MCP servers (`.mcp.json`, `~/.claude.json`) | **MCP servers** (Antigravity MCP config / plugin panel) | Re-add Apify (hosted, OAuth) + Supabase (HTTP). |
| Bash/Read/Write/Edit tools | Built-in terminal + file tools | Same local machine, same paths — nothing to change. |
| `Artifact` tool | Not used here anyway | Tracker deploys via file-write (Cowork), never the tool. |

**Key simplification:** Claude Code spawns four separate subagents. In Antigravity you can do that (Agent Manager supports parallel/multiple agents), but the pipeline's **guardrail #8 forbids parallel agents anyway** — stages must run one at a time. So the *least* fragile port is **a single Antigravity agent** that walks the workflow, reading each role `.md` as its instructions for that stage. Fewer moving parts, same behavior.

---

## 3. Prerequisites

### Already present on this machine (verified 2026-08-10)
- Node `v26`, Python `3.9.6`, `pdflatex` at `/Library/TeX/texbin/pdflatex` ✅
- Networking runner `nag`: `~/.claude/plugins/cache/networking-agent/networking-agent/1.0.0/bin/nag` (+ dev clone) ✅
- All local tools: `tools/{ats_scan,trust_check,liveness_check,legitimacy}.mjs`, `tools/portals.json` ✅
- Repo, playbooks, `DAILY_RUN.md`, `profile.md`, `seen_jobs.csv`, `refresh.py` ✅
- `networking_sheet.py` + **`openpyxl`** (installed 2026-08-22) — the Step 11 Excel handoff ✅
- `.env` with a working `SUPABASE_KEY` ✅ (so `./refresh.sh --fetch` is the sanctioned rebuild)
- Networking template at `~/Documents/Professional/JobSearch/JDs/Job_Applications - Networking Template.xlsx` ✅

### You must reconnect in Antigravity
1. **Apify MCP** — hosted server at `https://mcp.apify.com/` (OAuth). Provides `call-actor`, `get-dataset-items`, `fetch-actor-details`. Used by the fetcher (actor `curious_coder/linkedin-jobs-scraper`) and ranker.
2. **Supabase MCP** — HTTP server `https://mcp.supabase.com/mcp` (project `chsrkysjongzgdbwqhlu`). Used only at the "feed artifact" step.
3. **`SUPABASE_KEY` in `.env`** — present and working since 2026-08-13. `./refresh.sh --fetch` is now the *required* rebuild path; the manual `tracker_data.json` → `refresh.py` route is a fallback only.

> ⚠️ **Two steps Antigravity structurally cannot do.** Publishing the claude.ai tracker artifact
> (`DAILY_RUN.md` 10·E) needs the `Artifact` tool, which is Claude-Code-only. And the Follow-ups tab's
> live writes run through Sid's browser, not the agent. Neither blocks the run — see **§10** for
> exactly what to do about it.

> ⚠️ The `nag` networking runner is a Claude Code **plugin**. Antigravity can't install Claude plugins, but that doesn't matter — the runner is a self-contained CLI that bootstraps its own venv. The contact-finder just shells out to the `nag` path above. Nothing to reinstall.

---

## 4. Setup steps in Antigravity

### Step 1 — Open the workspace
Open `/Users/sid/Documents/Claude/Projects/Job_Applications` as the Antigravity workspace. Same machine, same absolute paths hardcoded throughout the docs — so everything resolves unchanged.

### Step 2 — Add the two MCP servers
Open Antigravity's **MCP / Plugins panel** (Settings → MCP Servers, or the "Manage plugins" surface in Agent Manager) and add:

**Apify** (hosted, OAuth — click connect and authenticate with your Apify account):
```json
{
  "mcpServers": {
    "apify": { "serverUrl": "https://mcp.apify.com/" }
  }
}
```

**Supabase** (HTTP — same URL your `.mcp.json` already uses):
```json
{
  "mcpServers": {
    "supabase": {
      "serverUrl": "https://mcp.supabase.com/mcp?features=database,development,functions,docs"
    }
  }
}
```
> Antigravity's config UI may phrase the URL key as `serverUrl`/`url` and may write to its own settings file — let the UI write it. After adding, confirm the tools show up (you should see `apify` and `supabase` tool groups available to the agent).

### Step 3 — Create the guardrails Rule
In **Customizations → Rules**, add a workspace rule (always-on) with the non-negotiables. This is your `CLAUDE.md`-equivalent safety net so the agent can't drift regardless of which stage it's in:

```
# apply-run guardrails (ALWAYS ON)
- NEVER apply to a job. NEVER send a LinkedIn message/InMail/connection/email. NEVER log in. Sid does every apply and every send.
- Run stages ONE AT A TIME, never in parallel (DAILY_RUN guardrail #8).
- Apify spend ceiling = $0.50/run (T1 0.20 / T2 0.10 / T3 0.15). Never exceed. Report running spend.
- Never pull descriptionText for all rows — screen on compact fields; JD pull is Rank-stage, survivors only.
- Live-state stores (seen_jobs.csv, Lane2_Tracker.md, ~/.networking-agent/state.db) are APPEND/UPDATE only, never rewrite.
- Stop at GATE A (shortlist) and GATE B (final report). Do not proceed past a gate without Sid.
- Contact drafts are OFF by default — find + rank only, unless Sid explicitly asks for drafts.
- Tracker destinations: Supabase = truth. The Cowork index.html deploys by file-write — never call a
  publish tool on it. The claude.ai artifact needs an explicit Artifact publish, which Antigravity
  CANNOT do — finish through the rebuild, then tell Sid it needs a Claude Code republish (§10).
- Networking outreach is Sid's — never draft or send anything, never log in. **BUT** recruiter +
  team-lead people-search **links** are now sourced automatically into the Supabase `contacts` table
  (Stage 4 / `tools/log_and_refresh.py`; ad-hoc `python3 networking_sheet.py add <json>`). That is the
  one "source contacts place" — see DAILY_RUN.md → "Source Contacts Place". Still export the Step 11
  sheet for the manual round-trip (gate: score >70 AND status not dropped/rejected/expired), then STOP
  before any outreach.
- Never edit or strip the `[ja-MMDD-NN]` job_id suffix in a networking sheet's "Target Role" line —
  it is the only anchor tying a block back to its application on import.
- ALWAYS `--dry-run` a networking import first and show Sid the parsed rows before committing.
- NO FABRICATED HANDOFFS. A handoff (ranked.md / tailored.md / etc.) may only claim work that
  actually changed a file. Copy Company/Location/URL verbatim from the JD's `**Source:**` header —
  never synthesize them. If a step was skipped, write `SKIPPED: <reason>`; never describe intended
  work as done. (Root cause of the 2026-08-10 v1 failures — see daily_run/REVIEW_2026-08-10.md.)
- CUSTOMISE MUST pass its Hard Self-Check Gate before writing tailored.md: every output .tex has a
  unique md5, is NON-empty-diff vs its base template, NEVER names the specific company anywhere it is not already in the base track (industry-level phrasing per P1_03), keeps experience blocks
  unchanged, and 1 page. An output identical to its base is NOT tailored — reject it.
- GEO GATE **(OVERRIDDEN — global scope):** search is now worldwide (US + Europe + Australia + beyond;
  `fetch_jobs.py --pass=4` is the curated international pass). Do **not** geo-block non-US roles. Only
  drop a role for eligibility reasons the ranker already checks (verbatim ITAR / no-sponsorship clauses).
```

### Step 4 — Create the orchestrator Workflow
In **Customizations → Workflows**, create a workflow named `apply-run`. Body = the orchestrator logic, adapted so it reads each role `.md` instead of spawning a subagent:

```
# /apply-run — Team Lead orchestrator (rewired 2026-08-13: hand-picked JDs, single lane, no agent networking)
You are the Team Lead for the Job_Applications daily run. Root:
/Users/sid/Documents/Claude/Projects/Job_Applications
Run the pipeline in order, one stage at a time, confirming each .pipeline/*.md handoff exists
before the next stage. Sid is the final gate. If input contains "dry-run", disable all
apply / send / DB writes. NEVER apply, send, log in, or run a networking/contact agent — Sid
does every apply and all networking himself.

0. PREP: `rm -rf .pipeline && mkdir .pipeline`; read profile.md; TODAY=$(date +%F).
   Confirm JDs/<today>/ (JDs/MM:DD/) has the .md files Sid hand-picked. If empty, STOP and ask.
1. RANK: read .claude/agents/ranker.md and execute it against JDs/<today>/*.md (NO fetch — the
   JDs are on disk). Route per P1_06 §5: ≥50 genuine-QE = Apply, <50/off-discipline = Drop,
   ≥60 = also flag `networking: recommended`. Wait for .pipeline/ranked.md.
   🧑 GATE A: show Sid the scored shortlist, highest score first. STOP and ask which Apply rows
   to customise. Do not proceed until Sid approves.
2. CUSTOMISE: read .claude/agents/customiser.md; tailor ONLY Sid's approved rows. Enforce the
   self-check gate (diff > summary-only + Skills reordered to the JD; LaTeX-safety scan, no bare
   &/%/_/#/$; every row produces a real .pdf). Wait for .pipeline/tailored.md.
3. WRITE + REBUILD (skip DB writes on dry-run): INSERT today's apps into Supabase (project
   chsrkysjongzgdbwqhlu, include every job_url), then guard-check that no row from today has a
   null/empty job_url. Rebuild with a LIVE fetch: `./refresh.sh --fetch` (MANDATORY — .env has the
   key; never a plain refresh from stale cache). This writes THREE files: the Cowork index.html
   (auto-deploys), job_tracker.html (local mirror), and job_tracker.artifact.html (the claude.ai
   publish body — see step 5). Verify today's job_ids appear in the regenerated index.html and
   id="today-date" shows today.
   Also append/update seen_jobs.csv + Lane2_Tracker.md rows, and write daily_run/<today>.md.
4. NETWORKING SHEET (skip on dry-run): `set -a; . ./.env; set +a` then
   `python3 networking_sheet.py export --date <today>`. Report the output path
   (daily_run/networking_<today>.xlsx) and list the role blocks it contains. Gate is score >70 AND
   status not in (dropped,rejected,expired) — typically 7-10 blocks. Then STOP on networking: Sid
   sources every contact and sends every connection himself, in his own session.
5. 🧑 GATE B: report, in this order — (a) run summary; (b) which tailored resumes to apply with +
   the apply links; (c) the networking sheet path; (d) the explicit reminder that
   **the claude.ai tracker still needs a Claude Code republish** (DAILY_RUN 10·E), because this
   environment has no Artifact tool. Then STOP.

# STANDBY (do NOT run unless Sid explicitly asks): FETCH (.claude/agents/fetcher.md) and
# CONTACT-FIND (.claude/agents/contact-finder.md + the `nag` runner). Not part of the daily flow.
```

Invoke it later by typing `/apply-run` (optionally `/apply-run dry-run`) in the Antigravity agent chat.

> **If you'd rather use real Antigravity sub-agents** instead of one inline agent: in Agent Manager, create four agents named after the stages, give each the corresponding `.claude/agents/*.md` as its system prompt, and have the `apply-run` workflow dispatch them **sequentially** (wait for each handoff file). This is closer to the Claude Code design but has more failure surface — the inline single-agent version is the recommended starting point.

### Step 5 — Pick the model
Set the agent model in Antigravity per stage difficulty (the `.md` files declare intended models):
- fetcher / customiser / contact-finder → a fast model (Gemini 3 Pro or Claude Sonnet) — mechanical work.
- **ranker → your strongest reasoning model** (Gemini 3 Pro "high" or Claude Opus if available) — it's the judgment stage applying P1_06.

If you run the single-agent version, just use a strong model throughout; the ranking stage is the one that matters.

---

## 5. Running it

### First run: always dry-run
```
/apply-run dry-run
```
Produces all `.pipeline/*.md` handoffs and `daily_run/<today>.md` from available/ATS-only data with **zero Apify spend, no DB writes, no sends**. Use this to confirm the agent can read the docs, resolve the `nag` runner, and write handoffs before you spend money or touch Supabase.

### Real run
```
/apply-run
```
Then:
1. Agent runs fetch → rank, stops at **GATE A**. Review the shortlist, tell it which direct-apply rows to pursue.
2. Agent runs customise → contact-find → consolidate → feed artifact, stops at **GATE B**.
3. You get the exact apply links + resumes + contacts. **You** do every apply and every send.

### Running a single stage standalone
The four commands `fetch` / `rank` / `customise` / `find-contacts` also exist as standalone Claude commands. In Antigravity, just tell the agent: *"read `.claude/agents/ranker.md` and run it against `.pipeline/fetched.md`."* Same doc, no wrapper needed.

---

## 6. Differences & gotchas vs Claude Code

| Concern | What changes | What to do |
|---|---|---|
| **Subagent isolation** | Antigravity's inline agent keeps everything in one context; Claude's subagents were isolated. | Trust the handoff files — each stage reads only its declared inputs. Keep the guardrails Rule on so context bleed can't break the sequence. |
| **Apify spend cap** | The cap lives in the fetcher doc, not the tool. A different agent could ignore it. | It's in the guardrails Rule (Step 3). Watch the running-spend line the fetcher prints; abort if it approaches $0.50. |
| **`get-dataset-items` field filtering** | Same Apify tool, same params. Make sure the agent passes `fields=...` and never reads a full dataset dump. | The ranker doc already specifies this; the guardrail reinforces it. |
| **Supabase writes** | HTTP MCP is identical. | Only the "feed artifact" step writes. Include every `job_url`. |
| **Tracker deploy** | No Artifact tool involved anyway. | `python3 refresh.py` writes `~/Documents/Claude/Artifacts/job-search-tracker/index.html`; Cowork auto-deploys on write. Don't look for a publish button. |
| **`nag` networking runner** | Not a plugin in Antigravity, but the binary still exists and self-bootstraps. | contact-finder shells to the cached `nag` path. No install. |
| **pdflatex** | Present locally. | Customiser compiles PDFs directly; if a run can't compile, it leaves `.tex` source for Overleaf (already handled in P1_03). |

---

## 7. Verification checklist (do this once, in order)

1. [ ] Workspace opens at the cockpit root; `DAILY_RUN.md` and `.claude/agents/*.md` are visible.
2. [ ] Apify MCP connected — agent can list actor `curious_coder/linkedin-jobs-scraper`.
3. [ ] Supabase MCP connected — agent can `list_tables` on project `chsrkysjongzgdbwqhlu`.
4. [ ] `node tools/ats_scan.mjs tools/portals.json` runs from the Antigravity terminal.
5. [ ] `nag` resolves: `ls ~/.claude/plugins/cache/networking-agent/networking-agent/*/bin/nag`.
6. [ ] `python3 refresh.py --help` (or a no-op) runs.
7. [ ] Guardrails Rule is always-on; `apply-run` Workflow invokes with `/apply-run`.
8. [ ] `**/apply-run dry-run**` completes end-to-end and writes `daily_run/<today>.md` with no spend.

Once #8 is green, you're ready for a real run.

---

## 9. PRIMARY FLOW — rank → customise → artifact (no fetch, no contacts)

This is the flow you'll actually run: JDs are **pre-saved**, so you skip fetch and start at rank; no referral lane, so **no contact-finder**. Sequence:

```
rank (saved JDs) ──▶ 🧑 GATE A ──▶ customise (+PDF) ──▶ write Supabase ──▶ rebuild (3 files)
                                                    ──▶ export networking sheet ──▶ 🧑 GATE B
                                                    ──▶ [Claude Code: publish artifact]
```

**What Antigravity needs for this flow (and nothing more):**
- Integrated terminal + file editing — for rank, customise, `pdflatex`, `refresh.py`. ✅ built in.
- **Supabase write path** — either the Supabase MCP (`execute_sql`) **or** `SUPABASE_KEY` in `.env`.
- **Apify MCP: NOT needed.** No fetch, and the ranker reads saved JDs from disk.
- **`nag` / networking: NOT needed.** No contact-finder.
- **`openpyxl` + `SUPABASE_KEY`** — for the Step 11 networking export. Both present.
- **Claude.app open** — so Cowork deploys the rebuilt `index.html` to its live URL.
- **A Claude Code session, afterwards** — to publish the claude.ai artifact (§10). Not needed *during*
  the run; the data is safe in Supabase either way.

### Stage 1 — RANK from saved JDs
Tell the agent:
> Read `.claude/agents/ranker.md` and `playbook/P1_06_scoring_rubric.md`. Read the pre-saved JDs in `JDs/<today>/*.md` (each has a `**Source:**` header = `job_url`) — no fetching. Score every JD 0–100 per track, apply the hard gates, and route per §5: **≥50 genuine-QE = Apply, <50/off-discipline = Drop, ≥60 = also flag `networking: recommended`.** Write `.pipeline/ranked.md` in the P1_06 §10 column shape (Networking column, no lane/referral column). Carry each row's `JD file` path.

The ranker reads JD files instead of fetching; routing is now the **single direct-apply lane** (referral lane retired 2026-08-13). Use your strongest model here — this is the judgment stage.

**🧑 GATE A:** review the scored shortlist (highest first); tell the agent which Apply rows to customise. Every approved row is a direct apply; `networking: recommended` rows are the ones worth Sid networking on manually AFTER he applies.

### Stage 2 — CUSTOMISE + compile PDF
Tell the agent:
> Read `.claude/agents/customiser.md` and `playbook/P1_03_resume_customization_rules.md`. For each approved row, copy its base `.tex` from `Resume/Final_Resumes/`, tailor per P1_03 (truth-only, one page, keyword-mirror, no em dashes), save to `Job_Applications_Resumes/<today>/src/resume_{Company}_{ShortRole}.tex`, then compile:
> `export PATH="/Library/TeX/texbin:$PATH" && pdflatex -output-directory Job_Applications_Resumes/<today> <src.tex>`
> Write `.pipeline/tailored.md` with the job→resume map + the P1_03 3-line change summary per resume.

**Tailor against the row's JD file, and run the customiser self-check gate before writing the handoff:**
- **Skills must be in the diff:** `diff` each output vs its base track must include lines inside `\section{Skills}` — reorder the Skills section to the JD (don't ship base-track aerospace skills on a non-aerospace role). This was the 2026-08-12 failure: all 10 resumes changed only the summary. (There is no Summary section as of 2026-08-18; Skills and Projects are the tailoring surface.)
- **LaTeX-safety:** `grep -nP '(?<!\\)[&%#_$]' <src.tex>`; ignore the `#1 & #2` macro line; every other hit is a bug (`EH&S`→`EH\&S`, `Blueprint & specification`→`Blueprint \& specification`).
- **PDF must exist:** after compile, `pdfinfo <pdf> | grep Pages` reads `1`. A `.tex` with `.aux/.log` but **no `.pdf`** = FAILED compile (usually an unescaped special) — fix and recompile; never report it done. (AbbVie + Hologic shipped no PDF on 2026-08-12.)

### Stage 3 — WRITE to Supabase
Project `chsrkysjongzgdbwqhlu`, table `applications`. One INSERT per approved row (from `DAILY_RUN.md` §10·B — direct-apply shape; **`job_url` required**, pull it from the JD's `**Source:**` header):

```sql
insert into applications
  (job_id, company, role, location, lane, score, track, resume, job_url, found_date, referral_state, status, notes)
values
  ('ja-MMDD-NN','<Company>','<Role>','<Location>','direct-apply',<score>,'<T?>',
   '<resume_Company_ShortRole>','<job_url from JD Source header>','<TODAY>','direct-apply','pending','Resume ready - Sid applies.')
on conflict (job_id) do nothing;
```

Run it either way:
- **With Supabase MCP:** call `execute_sql` with `project_id=chsrkysjongzgdbwqhlu` and the SQL above (idempotent — safe to re-run).
- **No MCP, key in `.env`:** `curl` POST to `https://chsrkysjongzgdbwqhlu.supabase.co/rest/v1/applications` with the `SUPABASE_KEY` header. (MCP is cleaner; use it if connected.)

**Guard check** before rebuilding (must return zero rows):
```sql
select job_id, company from applications where found_date = '<TODAY>' and (job_url is null or job_url = '');
```

### Stage 4 — REBUILD the artifact  (⚠️ `--fetch` is MANDATORY)
`.env` HAS a working `SUPABASE_KEY` (verified 2026-08-13). The rebuild MUST pull live from the DB:
```bash
./refresh.sh --fetch    # pulls live Supabase → rewrites artifact index.html + local mirror
```
**Do NOT rebuild with a plain `./refresh.sh` / `python3 refresh.py` from `tracker_data.json`.** That json is only as fresh as the last connector dump — it was frozen at 08-11 while the DB moved ahead, which is exactly why the artifact showed stale statuses ("applied"/"dropped" never appeared) for 08-10→12. `--fetch` is the only sanctioned daily rebuild. (The `tracker_data.json` → `python3 refresh.py` path is a fallback ONLY when the key is genuinely absent.)

`refresh.sh --fetch` writes **three** files:

| File | What it is | How it goes live |
|---|---|---|
| `~/Documents/Claude/Artifacts/job-search-tracker/index.html` | Cowork artifact | auto-deploys on file write (Claude.app open) — **never** call a publish tool |
| `job_tracker.html` | local full-document mirror | nothing; it's for local viewing |
| `job_tracker.artifact.html` | claude.ai publish body (wrapper + `<title>` stripped) | **requires an `Artifact` publish — Antigravity cannot do it.** See §10 |

**Verify (always):**
```bash
grep -c 'ja-MMDD' ~/Documents/Claude/Artifacts/job-search-tracker/index.html   # today's job_ids present?
grep 'id="today-date"' ~/Documents/Claude/Artifacts/job-search-tracker/index.html   # reads today?
```
If either fails, the rebuild used stale data — re-run, don't assume.

### Stage 4b — EXPORT the networking sheet, then STOP on networking

```bash
cd /Users/sid/Documents/Claude/Projects/Job_Applications
set -a; . ./.env; set +a
python3 networking_sheet.py export --date <TODAY>      # -> daily_run/networking_<TODAY>.xlsx
```

Report the path and the block list. **That is the end of the agent's involvement in networking.** Sid
sources the contacts and sends the connections himself in a separate session; he returns the filled
sheet whenever he's done, and the import (`DAILY_RUN.md` 11·B) happens then — not as part of this run.

- Gate: `score > 70` **and** status not in (`dropped`,`rejected`,`expired`). Strictly above 70.
- Don't confuse this with the ranker's `networking: recommended` flag, which is **≥60**. Different,
  looser threshold, different purpose (advisory annotation on `ranked.md`).
- The exporter re-lays the 3-block template to however many roles qualify — usually 7-10.
- If it prints "No roles scoring above 70 are live for `<date>`", that is a valid outcome, not an
  error. Say so and move on.

### Stage 5 — also update the flat records (append/update, never rewrite)
- `seen_jobs.csv` — set today's rows' status.
- `Lane2_Tracker.md` — add a row per approved job (`direct-apply (no referral)`, apply `pending`, Track + Resume + Job URL columns).
- `daily_run/<today>.md` — the run record (Part A shortlist, Part C tailored resume paths + apply links).

**🧑 GATE B:** report which tailored resumes to apply with + the apply links. **You apply. Claude never applies.**

### One-line capability summary for this flow
| Step | Antigravity capable? | Needs |
|---|---|---|
| Rank saved JDs | ✅ | terminal + file read (no Apify) |
| Customise `.tex` | ✅ | file edit |
| Compile PDF | ✅ | `pdflatex` (add texbin to PATH) |
| Write Supabase | ✅ | Supabase MCP **or** `SUPABASE_KEY` in `.env` |
| Rebuild artifact files | ✅ | `./refresh.sh --fetch` |
| Deploy Cowork artifact | ✅ via Cowork | **Claude.app must stay open** |
| Publish claude.ai artifact | ❌ **no** | Claude Code `Artifact` tool — see §10 |
| Export networking sheet | ✅ | `openpyxl` + `SUPABASE_KEY` |
| Import networking sheet | ✅ | same (run only when Sid returns the file) |

---

## 10. The claude.ai tracker — and why Antigravity no longer needs to publish it

**Read this before your first Antigravity run.** As of 2026-08-22 Sid's day-to-day tracker is a
**claude.ai artifact**, not the Cowork one:

`https://claude.ai/code/artifact/29f93df2-c9bd-40ca-a73c-feab4a5e9f02`

It moved there because the Cowork copy asked for connector permission on **every single edit** — the
page's baked-key REST write was blocked by the artifact sandbox CSP and silently fell back to an ad-hoc
connector call, one consent dialog per click. The claude.ai version declares the Supabase connector in
its published manifest, so consent happens once.

### The page updates itself

**Antigravity has always updated the Cowork artifact correctly** — `refresh.py` writes `index.html` and
Cowork auto-deploys on file-write. That is unchanged and still works.

The claude.ai artifact was briefly a gap, because publishing it needs the Claude-Code-only `Artifact`
tool. That gap is **closed**: as of 2026-08-22 the page re-reads Supabase on every load through the
`mcp` capability it already holds (`hydrate()` in `refresh.py`'s template) and replaces its baked rows
before you see them.

| | Antigravity | Result |
|---|---|---|
| Write today's rows to Supabase | ✅ | Data is correct |
| `./refresh.sh --fetch` (writes all 3 files) | ✅ | Cowork deploys; artifact body updated on disk |
| Publish to the artifact URL | ❌ | **Doesn't matter — the live page reads the DB itself** |

So an Antigravity run that completes Stage 4 is **done**. Sid opens the tracker and sees today's rows.

### When a republish IS still needed

Only when the page's **code** changes — a new column, a new tab, changed logic in `refresh.py`'s
template. Data changes never need it. In that case, from a Claude Code session, run `DAILY_RUN.md`
§10·E: publish `job_tracker.artifact.html`, **always passing
`url=https://claude.ai/code/artifact/29f93df2-c9bd-40ca-a73c-feab4a5e9f02`**, omitting `capabilities`
so the stored connector manifest carries forward, and keeping the 🎯 favicon.

### How to tell what you're looking at

The header stamp reads **today's date** when the live read succeeded. If it reads
**`<date> (snapshot)`**, the live read failed and you're seeing baked data — the source note underneath
says which error code. That fallback is deliberate: a failed or oversized read leaves the last good
snapshot on screen rather than blanking the page.

---

## 11. TL;DR

The pipeline is portable because it's already markdown. In Antigravity you: **(1)** open the repo, **(2)** reconnect Apify + Supabase MCP, **(3)** drop the guardrails into a Rule, **(4)** paste the orchestrator into a `/apply-run` Workflow that reads the four `.claude/agents/*.md` files in order, **(5)** dry-run first. The four role docs, both playbooks, and `DAILY_RUN.md` are reused **unchanged**. Everything else — local tools, `nag`, `pdflatex`, `refresh.py`, absolute paths — is the same machine and just works.

**Daily sequence, current as of 2026-08-22:**
`/apply-run` → GATE A → customise → Supabase → `./refresh.sh --fetch` → `networking_sheet.py export`
→ GATE B → *(Claude Code: republish the artifact, §10)*.

Two hand-offs leave the agent's hands: the **tailored resumes** (Sid applies) and the **networking
sheet** (Sid sources and sends, then returns it for import). The agent does neither.
