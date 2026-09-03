#!/usr/bin/env node
// @ts-check
/**
 * repost_check.mjs — ghost-posting detector over our seen_jobs.csv ledger.
 *
 * Wraps career-ops's detectReposts (santifer/career-ops, MIT — imported from the
 * clone, like ats_scan). Groups our sightings by company, fuzzy-matches role
 * titles (role-matcher), and flags any company+role seen 2+ times with DIFFERENT
 * urls inside a 90-day window = the same opening re-listed = a ghost. Directly
 * targets the June waste of referral energy on stale/re-listed postings.
 *
 * seen_jobs.csv cols: first_seen_date,market,company,title_normalized,city,job_url,fingerprint,status
 * We map every row to status 'added' (each row is a genuine sighting) so the
 * detector considers all of them; it still needs 2+ DISTINCT urls to flag.
 *
 * Usage:
 *   node tools/repost_check.mjs                 # JSON clusters over seen_jobs.csv
 *   node tools/repost_check.mjs --summary       # human-readable table
 *   node tools/repost_check.mjs --window 60     # override 90-day window
 *   node tools/repost_check.mjs --self-test     # offline asserts, exit 0/1
 */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const LEDGER = join(HERE, '..', 'seen_jobs.csv');

const { detectReposts } = await import(pathToFileURL(join(HERE, 'lib', 'detect-reposts.mjs')).href);

/** Minimal RFC4180-ish line parser: handles "quoted, fields" and "" escapes. One row per line. */
export function parseCsvLine(line) {
  const out = [];
  let cur = '', inQ = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQ) {
      if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
      else cur += c;
    } else if (c === '"') inQ = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

/** Strip query + hash so the same posting seen with/without tracking params
 * (e.g. greenhouse `?gh_jid=` vs bare) collapses to one URL — a dedup hit, not a
 * ghost repost. Job identity lives in the path for our sources (greenhouse/linkedin). */
export function normalizeUrl(u) {
  const s = String(u || '').trim();
  const q = s.search(/[?#]/);
  return (q === -1 ? s : s.slice(0, q)).replace(/\/+$/, '');
}

/** seen_jobs.csv → rows shaped for detectReposts. */
export function ledgerToRows(csv) {
  const lines = csv.split('\n').filter(l => l.trim());
  const rows = [];
  for (const line of lines.slice(1)) { // skip header
    const c = parseCsvLine(line);
    if (c.length < 8) continue;
    const [first_seen, , company, title, , job_url] = c;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(first_seen)) continue;
    const date = new Date(`${first_seen}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) continue;
    const url = normalizeUrl(job_url);
    // Bare listing URLs with no job id (e.g. .../jobs/view/) can't identify a
    // posting — skip so they don't collapse unrelated rows into a fake repost.
    if (!url || /\/jobs\/view\/?$/.test(url) || !company?.trim() || !title?.trim()) continue;
    rows.push({ url, date, dateStr: first_seen.trim(), company: company.trim(), title: title.trim(), status: 'added' });
  }
  return rows;
}

function selfTest() {
  const csv = [
    'first_seen_date,market,company,title_normalized,city,job_url,fingerprint,status',
    // genuine ghost: same company+role, 2 different real URLs, 40 days apart
    '2026-05-01,US,Acme Aero,supplier quality engineer,detroit,https://boards.greenhouse.io/acme/jobs/1,fp,surfaced',
    '2026-06-10,US,Acme Aero,supplier quality engineer,detroit,https://boards.greenhouse.io/acme/jobs/2,fp,shortlisted',
    // embedded comma in company (quoted) — parser must keep 8 cols
    '2026-05-02,US,"Beta, Inc.",process engineer,akron,https://boards.greenhouse.io/beta/jobs/9,fp,surfaced',
    // distinct role, same company — must NOT cluster with the SQE ghost
    '2026-05-15,US,Acme Aero,materials engineer,detroit,https://boards.greenhouse.io/acme/jobs/3,fp,surfaced',
  ].join('\n');
  const rows = ledgerToRows(csv);
  let pass = 0, total = 0;
  const check = (n, c) => { total++; if (c) pass++; else console.error('FAIL:', n); };
  check('parser keeps 8 cols on quoted comma', parseCsvLine('a,"b, c",d,e,f,g,h,i').length === 8);
  check('normalizeUrl strips query', normalizeUrl('https://boards.greenhouse.io/vast/jobs/123?gh_jid=123') === 'https://boards.greenhouse.io/vast/jobs/123');
  check('ledger parsed 4 rows', rows.length === 4);
  const clusters = detectReposts(rows, 90);
  check('one ghost cluster flagged', clusters.length === 1);
  check('ghost is the SQE role', clusters[0] && /supplier quality/i.test(clusters[0].role));
  check('ghost repostCount == 2', clusters[0] && clusters[0].repostCount === 2);
  check('materials engineer NOT clustered', !clusters.some(c => /materials/i.test(c.role)));
  console.error(`repost_check self-test: ${pass}/${total} passed`);
  process.exit(pass === total ? 0 : 1);
}

/** Load seen_jobs.csv → repost clusters. Reused by legitimacy.mjs (no CLI side effects). */
export function loadClusters(windowDays = 90, ledgerPath = LEDGER) {
  return detectReposts(ledgerToRows(readFileSync(ledgerPath, 'utf8')), windowDays);
}

// CLI (guarded so this module is safely importable) --------------------------
const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
const args = process.argv.slice(2);
if (args.includes('--self-test')) selfTest();
const wi = args.indexOf('--window');
const windowDays = wi !== -1 ? Number(args[wi + 1]) : 90;

const rows = ledgerToRows(readFileSync(LEDGER, 'utf8'));
const clusters = detectReposts(rows, windowDays);

if (args.includes('--summary')) {
  console.log(`\nRepost / ghost-posting detector — window ${windowDays}d — ${clusters.length} cluster(s) over ${rows.length} sightings\n`);
  if (!clusters.length) console.log('  none.\n');
  for (const c of clusters) {
    console.log(`  ${c.company} — "${c.role}"  ×${c.repostCount}  (${c.firstSeen} → ${c.lastSeen}, ${c.daysSpan}d)`);
    for (const a of c.appearances) console.log(`      ${a.date}  ${a.url}`);
  }
  console.log('');
} else {
  console.log(JSON.stringify({ windowDays, totalRows: rows.length, clusters }, null, 2));
}
}
