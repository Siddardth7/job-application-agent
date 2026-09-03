#!/usr/bin/env node
// @ts-check
/**
 * liveness_check.mjs — zero-token "is this posting still open?" check.
 *
 * Wraps career-ops's checkLivenessViaApi (santifer/career-ops, MIT — imported
 * from the clone). Hits the posting's ATS per-job API (Greenhouse/Lever = 200
 * means live, 404/410 = gone; Ashby = confirmed against its board). Non-ATS URLs
 * (LinkedIn, Workday, company sites) return null → we annotate 'unknown' and
 * NEVER drop on unknown (conservative — a false 'expired' costs us a real job).
 *
 * Purpose: run on hold-referral candidates BEFORE Step 6 referral discovery so we
 * don't spend Serper + outreach energy on a posting that's already been filled
 * (the June ghost-job waste). expired → drop from the referral pass; active/unknown → proceed.
 *
 * Usage:
 *   cat candidates.json | node tools/liveness_check.mjs -     # stdin
 *   node tools/liveness_check.mjs candidates.json             # file
 *   node tools/liveness_check.mjs --self-test                 # offline asserts
 * Input rows: any objects with applyUrl | link | job_url. Output: same rows + `liveness`.
 */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const CONCURRENCY = 5;
const { checkLivenessViaApi, resolveAtsApi } = await import(pathToFileURL(join(HERE, 'lib', 'liveness-api.mjs')).href);

export function urlOf(row) {
  return row.applyUrl || row.companyApplyUrl || row.link || row.job_url || '';
}

async function annotate(row) {
  const url = urlOf(row);
  let liveness = 'unknown';
  try {
    const res = url ? await checkLivenessViaApi(url) : null;
    if (res && (res.result === 'active' || res.result === 'expired')) liveness = res.result;
  } catch { /* inconclusive → unknown */ }
  return { ...row, liveness };
}

async function mapPool(items, n, fn) {
  const out = [];
  let i = 0;
  const worker = async () => { while (i < items.length) { const idx = i++; out[idx] = await fn(items[idx]); } };
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, worker));
  return out;
}

function selfTest() {
  // resolveAtsApi is pure (no network) — test URL classification without hitting anything.
  let pass = 0, total = 0;
  const check = (n, c) => { total++; if (c) pass++; else console.error('FAIL:', n); };
  check('greenhouse per-job URL resolves to ATS', resolveAtsApi('https://boards.greenhouse.io/acme/jobs/123') !== null);
  check('lever URL resolves to ATS', resolveAtsApi('https://jobs.lever.co/acme/abc-123') !== null);
  check('LinkedIn URL → not ATS (→ unknown)', resolveAtsApi('https://www.linkedin.com/jobs/view/123') === null);
  check('Workday URL → not ATS (→ unknown)', resolveAtsApi('https://gm.wd5.myworkdayjobs.com/x/job/y') === null);
  check('malformed URL → not ATS', resolveAtsApi('not a url') === null);
  check('urlOf precedence applyUrl>link', urlOf({ applyUrl: 'A', link: 'B' }) === 'A');
  check('urlOf falls back to link', urlOf({ link: 'B' }) === 'B');
  console.error(`liveness_check self-test: ${pass}/${total} passed`);
  process.exit(pass === total ? 0 : 1);
}

const arg = process.argv[2];
if (arg === '--self-test') selfTest();

const raw = arg && arg !== '-' ? readFileSync(arg, 'utf8') : readFileSync(0, 'utf8');
const data = JSON.parse(raw);
const rows = Array.isArray(data) ? data : (data.items || data.rows || [data]);
const out = await mapPool(rows, CONCURRENCY, annotate);
const n = { active: 0, expired: 0, unknown: 0 };
for (const r of out) n[r.liveness]++;
console.error(`liveness_check: ${n.active} active, ${n.expired} expired, ${n.unknown} unknown (unknown never dropped)`);
process.stdout.write(JSON.stringify(out, null, 2) + '\n');
