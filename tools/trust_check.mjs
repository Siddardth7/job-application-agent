#!/usr/bin/env node
// @ts-check
/**
 * trust_check.mjs — cockpit wrapper over the vendored career-ops trust validator.
 *
 * Reads a JSON array of Apify LinkedIn rows (stdin, or a file arg), points the
 * validator at the REAL employer apply URL (applyUrl), and prints each row
 * enriched with trustScore / trustFlags / trustLevel.
 *
 * Legitimacy is a SEPARATE axis — it NEVER modifies the P1_06 match score or the
 * scoring gate (P1_06 §5). Flags surface in the shortlist so Sid can deprioritize; never auto-drop.
 *
 * Usage:
 *   cat rows.json | node tools/trust_check.mjs            # stdin
 *   node tools/trust_check.mjs rows.json                  # file
 *   node tools/trust_check.mjs --self-test                # asserts, exit 0/1
 *
 * URL precedence: applyUrl → companyApplyUrl → link (LinkedIn link is the weak
 * fallback; on Easy-Apply rows applyUrl may be absent, so trust is best-effort).
 */
import { readFileSync } from 'node:fs';
import { buildTrustValidator } from './lib/trust-validator.mjs';

const validate = buildTrustValidator({ enabled: true });

/** @param {any} row */
function enrich(row) {
  const url = row.applyUrl || row.companyApplyUrl || row.link || row.job_url || '';
  const company = row.companyName || row.company || '';
  const { score, flags, level } = validate({ url, company });
  return { ...row, trustScore: score, trustFlags: flags, trustLevel: level, trustUrl: url };
}

function selfTest() {
  const cases = [
    // real ATS apply URL → allowlisted, no mismatch → 100/high
    { in: { companyName: 'Gulfstream', applyUrl: 'https://boards.greenhouse.io/gulfstream/jobs/123' }, score: 100, level: 'high', hasFlag: null },
    // company careers domain that matches name → no mismatch → 100/high
    { in: { companyName: 'Rivian', applyUrl: 'https://careers.rivian.com/job/456' }, score: 100, level: 'high', hasFlag: null },
    // staffing repost via link shortener → suspicious_domain -25 AND mismatch -15 (bit.ly not ATS, no name match) → 60/medium
    { in: { companyName: 'Acme Corp', applyUrl: 'https://bit.ly/apply-now' }, score: 60, level: 'medium', hasFlag: 'suspicious_domain' },
    // apply URL on unrelated domain, not ATS, name absent from host → mismatch -15 → 85/medium
    { in: { companyName: 'Northwind Aerospace', applyUrl: 'https://jobs.randomstaffing.com/x' }, score: 85, level: 'medium', hasFlag: 'company_domain_mismatch' },
    // no apply url at all → missing_apply_url -40 → 60/medium
    { in: { companyName: 'Somebody', link: '' }, score: 60, level: 'medium', hasFlag: 'missing_apply_url' },
    // LinkedIn link fallback (Easy Apply, no applyUrl): company never in linkedin.com → mismatch -15 → 85
    { in: { companyName: 'Gulfstream', link: 'https://www.linkedin.com/jobs/view/123' }, score: 85, level: 'medium', hasFlag: 'company_domain_mismatch' },
  ];
  let pass = 0;
  for (const [i, c] of cases.entries()) {
    const out = enrich(c.in);
    const okScore = out.trustScore === c.score;
    const okLevel = out.trustLevel === c.level;
    const okFlag = c.hasFlag === null ? out.trustFlags.length === 0 : out.trustFlags.includes(c.hasFlag);
    if (okScore && okLevel && okFlag) { pass++; }
    else console.error(`FAIL case ${i}: got score=${out.trustScore} level=${out.trustLevel} flags=[${out.trustFlags}] — expected score=${c.score} level=${c.level} flag=${c.hasFlag}`);
  }
  console.error(`trust_check self-test: ${pass}/${cases.length} passed`);
  process.exit(pass === cases.length ? 0 : 1);
}

const arg = process.argv[2];
if (arg === '--self-test') selfTest();

const raw = arg && arg !== '-' ? readFileSync(arg, 'utf8') : readFileSync(0, 'utf8');
const data = JSON.parse(raw);
const rows = Array.isArray(data) ? data : (data.items || data.rows || [data]);
process.stdout.write(JSON.stringify(rows.map(enrich), null, 2) + '\n');
