#!/usr/bin/env node
// @ts-check
/**
 * legitimacy.mjs — the consolidated LEGITIMACY AXIS (career-ops #4 "Block G").
 *
 * Folds the three posting-legitimacy signals into ONE verdict per candidate:
 *   • trust   (trustScore/trustFlags/trustLevel — from trust_check.mjs)
 *   • liveness (active|expired|unknown — from liveness_check.mjs)
 *   • repost  (is this company+role a ghost re-list in seen_jobs.csv — computed here)
 *
 * Legitimacy is a SEPARATE axis: it NEVER modifies the P1_06 match score or the scoring gate (P1_06 §5).
 * It's the single column you read to decide whether a legit-*scoring* posting is worth
 * spending referral energy on. Levels: OK / CAUTION / DEAD (flag, never silently drop —
 * the Step 6·0 liveness gate is what actually drops `expired` from the referral pass).
 *
 * Usage (compose after trust + liveness so both fields are present):
 *   cat 85plus.json | node tools/trust_check.mjs - | node tools/liveness_check.mjs - | node tools/legitimacy.mjs -
 *   node tools/legitimacy.mjs --self-test
 * Repost membership is computed internally against seen_jobs.csv (history-dependent).
 */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

const CAUTION_TRUST_FLAGS = new Set(['suspicious_domain', 'company_domain_mismatch', 'missing_apply_url', 'invalid_url']);

/** Pure verdict from the three already-computed signals. Does NOT touch the match score. */
export function verdict({ trustFlags = [], trustLevel = 'high', liveness = 'unknown', isRepost = false } = {}) {
  if (liveness === 'expired') return { level: 'DEAD', flags: ['expired'], note: 'posting gone (ATS 404/410) — do not pursue' };
  const flags = [];
  for (const f of trustFlags) if (CAUTION_TRUST_FLAGS.has(f)) flags.push(f);
  if (trustLevel === 'low') flags.push('low_trust');
  if (isRepost) flags.push('repost');
  if (flags.length === 0) return { level: 'OK', flags: [], note: liveness === 'active' ? 'confirmed live, clean' : 'clean (liveness unknown — non-ATS)' };
  return { level: 'CAUTION', flags, note: `legit but verify: ${flags.join(', ')}` };
}

/** Short shortlist-column string. */
export function legitCell(v) {
  return v.level === 'OK' ? 'OK' : `${v.level}[${v.flags.join(',')}]`;
}

async function buildRepostMatcher(windowDays = 90) {
  const { loadClusters } = await import(pathToFileURL(join(HERE, 'repost_check.mjs')).href);
  const { roleFuzzyMatch } = await import(pathToFileURL(join(HERE, 'lib', 'role-matcher.mjs')).href);
  let clusters = [];
  try { clusters = loadClusters(windowDays); } catch { clusters = []; }
  return (company, title) => {
    const c = String(company || '').toLowerCase();
    return clusters.some(cl => cl.company.toLowerCase() === c && (cl.role.toLowerCase() === String(title || '').toLowerCase() || roleFuzzyMatch(cl.role, title)));
  };
}

function selfTest() {
  let pass = 0, total = 0;
  const check = (n, c) => { total++; if (c) pass++; else console.error('FAIL:', n); };
  check('expired → DEAD', verdict({ liveness: 'expired', trustLevel: 'high' }).level === 'DEAD');
  check('clean+active → OK', verdict({ liveness: 'active', trustLevel: 'high', trustFlags: [] }).level === 'OK');
  check('clean+unknown → OK', verdict({ liveness: 'unknown', trustLevel: 'high', trustFlags: [] }).level === 'OK');
  check('suspicious_domain → CAUTION', verdict({ trustFlags: ['suspicious_domain'], liveness: 'unknown' }).level === 'CAUTION');
  check('repost → CAUTION w/ flag', verdict({ isRepost: true, liveness: 'active' }).flags.includes('repost'));
  check('low_trust → CAUTION', verdict({ trustLevel: 'low', liveness: 'active' }).level === 'CAUTION');
  check('expired beats caution flags', verdict({ liveness: 'expired', trustFlags: ['suspicious_domain'], isRepost: true }).level === 'DEAD');
  check('company_domain_mismatch (non-caution list check)', verdict({ trustFlags: ['company_domain_mismatch'], liveness: 'active' }).flags.includes('company_domain_mismatch'));
  check('cell: OK', legitCell({ level: 'OK', flags: [] }) === 'OK');
  check('cell: CAUTION[flags]', legitCell({ level: 'CAUTION', flags: ['repost', 'low_trust'] }) === 'CAUTION[repost,low_trust]');
  console.error(`legitimacy self-test: ${pass}/${total} passed`);
  process.exit(pass === total ? 0 : 1);
}

const arg = process.argv[2];
if (arg === '--self-test') selfTest();

const raw = arg && arg !== '-' ? readFileSync(arg, 'utf8') : readFileSync(0, 'utf8');
const data = JSON.parse(raw);
const rows = Array.isArray(data) ? data : (data.items || data.rows || [data]);
const isRepostOf = await buildRepostMatcher(90);

const out = rows.map(r => {
  const isRepost = isRepostOf(r.companyName || r.company, r.title || r.role_title || r.title_normalized);
  const v = verdict({ trustFlags: r.trustFlags, trustLevel: r.trustLevel, liveness: r.liveness, isRepost });
  return { ...r, legitimacy: v, legit: legitCell(v) };
});

const n = { OK: 0, CAUTION: 0, DEAD: 0 };
for (const r of out) n[r.legitimacy.level]++;
console.error(`legitimacy: ${n.OK} OK, ${n.CAUTION} CAUTION, ${n.DEAD} DEAD`);
process.stdout.write(JSON.stringify(out, null, 2) + '\n');
