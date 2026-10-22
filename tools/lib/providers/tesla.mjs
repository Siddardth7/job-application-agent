// @ts-check
// Tesla careers provider. tesla.com sits behind Akamai bot protection: plain fetch and headless
// Chrome get 403, so this drives the system Chrome in a visible window (moved off-screen) with a
// saved profile, then calls the site's own JSON from inside the page:
//   /cua-api/apps/careers/state      every listing worldwide (~8k rows: id, title, dept, location id, type)
//   /cua-api/careers/job/{id}        one posting with its full description
// Needs `npm install` in the repo (playwright-core) and Google Chrome. No posted date is published,
// so the seen-ledger decides what is new. Only unseen ids are returned, with their JD, max_jd per run;
// the remainder arrives on later runs (first run: Tesla's whole US backlog spread over a few days).
//
// portals.json entry:
//   { "name": "Tesla", "provider": "tesla", "all_postings": true, "country": "US",
//     "title_include": ["technician", "quality", ...], "title_exclude": ["senior", ...],
//     "types": [1], "max_jd": 150 }
// types: 1 fulltime, 2 parttime, 3 intern, 4 seasonal.

import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const PROFILE_DIR = join(homedir(), '.cache', 'job-pipeline', 'tesla-chrome-profile');   // ponytail: outside the repo, holds Akamai cookies
const SEARCH_URL = 'https://www.tesla.com/careers/search/?site=US';

const strip = (s) => String(s || '').replace(/<\/(p|li|h\d)>/g, '\n').replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&')
  .replace(/&nbsp;/g, ' ').replace(/&#39;|&rsquo;/g, "'").replace(/[ \t]+/g, ' ').replace(/\n\s*/g, '\n').trim();
const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/** Pure: pick listings from the state payload. */
export function selectListings(state, { country = 'US', types = [1], include = [], exclude = [] } = {}) {
  const ids = new Set();
  for (const region of state.geo || []) for (const site of region.sites || [])
    if (site.id === country) for (const st of site.states || []) for (const arr of Object.values(st.cities || {})) arr.forEach((i) => ids.add(String(i)));
  const has = (t, list) => list.some((k) => t.includes(k.toLowerCase()));
  return (state.listings || [])
    .filter((x) => ids.has(String(x.l)) && types.includes(x.y))
    .filter((x) => { const t = String(x.t).toLowerCase(); return (!include.length || has(t, include)) && !has(t, exclude); })
    .map((x) => ({
      title: String(x.t).trim(),
      url: `https://www.tesla.com/careers/search/job/${slug(x.t)}-${x.id}`,
      location: state.lookup?.locations?.[x.l] || '',
      reqId: `TESLA-${x.id}`,
      id: String(x.id),
      department: state.lookup?.departments?.[x.dp] || '',
    }));
}

/** Pure: description text from one job payload. */
export function jobText(job) {
  return [job.jobDescription, job.jobResponsibilities, job.jobRequirements, job.jobCompensationAndBenefits, job.description]
    .map(strip).filter(Boolean).join('\n\n');
}

function seenReqIds() {
  const p = join(ROOT, 'seen_jobs.csv');
  if (!existsSync(p)) return new Set();
  return new Set(readFileSync(p, 'utf8').split('\n').map((l) => l.split(',').pop()?.trim()).filter((r) => r && r.startsWith('TESLA-')));
}

/** @type {import('./_types.js').Provider} */
export default {
  id: 'tesla',
  detect() { return null; },
  async fetch(entry) {
    let chromium;
    try { ({ chromium } = await import('playwright-core')); }
    catch { throw new Error('playwright-core missing: run `npm install` in the repo root'); }
    const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
      channel: 'chrome', headless: false, locale: 'en-US',
      args: ['--disable-blink-features=AutomationControlled', '--window-position=-2400,-2400', '--window-size=1200,800'],
    });
    try {
      const page = ctx.pages()[0] || await ctx.newPage();
      await page.goto(SEARCH_URL, { waitUntil: 'load', timeout: 60_000 });
      await page.waitForTimeout(4000);
      const [status, state] = await page.evaluate(async () => {
        const r = await fetch('/cua-api/apps/careers/state');
        return [r.status, r.ok ? await r.json() : null];
      });
      if (!state) throw new Error(`careers feed HTTP ${status} (Akamai); try again later`);
      const rows = selectListings(state, {
        country: entry.country || 'US', types: entry.types || [1],
        include: entry.title_include || [], exclude: entry.title_exclude || [],
      });
      const seen = seenReqIds();
      const todo = rows.filter((r) => !seen.has(r.reqId)).slice(0, entry.max_jd ?? 150);
      for (const r of todo) {
        const job = await page.evaluate(async (id) => {
          const x = await fetch(`/cua-api/careers/job/${id}`);
          return x.ok ? x.json() : null;
        }, r.id);
        if (job) r.description = jobText(job);
        await page.waitForTimeout(400);   // ponytail: fixed polite delay; back off on 429s if Akamai starts throttling
      }
      console.error(`  Tesla: ${state.listings.length} worldwide -> ${rows.length} match -> ${todo.length} JDs fetched (${seen.size} seen before, rest wait for the next run)`);
      // only rows with a fetched JD go downstream; the rest stay unseen and come through on a later run
      return todo.map(({ id, department, ...j }) => ({ ...j, company: entry.name }));
    } finally {
      await ctx.close();
    }
  },
};

if (process.argv[1] === fileURLToPath(import.meta.url) && process.argv[2] === '--self-test') {
  const state = {
    lookup: { locations: { 10: 'Austin, Texas', 20: 'Berlin' }, departments: { 8: 'Manufacturing' } },
    geo: [{ sites: [{ id: 'US', states: [{ cities: { Austin: ['10'] } }] }, { id: 'DE', states: [{ cities: { Berlin: ['20'] } }] }] }],
    listings: [
      { id: '1', t: 'Process Technician, Cell', dp: '8', l: '10', y: 1 },
      { id: '2', t: 'Senior Process Technician', dp: '8', l: '10', y: 1 },
      { id: '3', t: 'Quality Technician', dp: '8', l: '20', y: 1 },
      { id: '4', t: 'Process Technician Intern', dp: '8', l: '10', y: 3 },
      { id: '5', t: 'Sales Advisor', dp: '8', l: '10', y: 1 },
    ],
  };
  const got = selectListings(state, { include: ['technician'], exclude: ['senior'] });
  const ok = [
    ['US full-time match kept', got.length === 1 && got[0].reqId === 'TESLA-1'],
    ['url is slug-id', got[0]?.url === 'https://www.tesla.com/careers/search/job/process-technician-cell-1'],
    ['location looked up', got[0]?.location === 'Austin, Texas'],
    ['jd text joins parts', jobText({ jobDescription: '<p>A &amp; B</p>', jobRequirements: '<ul><li>x</li></ul>' }) === 'A & B\n\nx'],
  ];
  for (const [n, o] of ok) console.log(`  ${o ? 'PASS' : 'FAIL'}  ${n}`);
  console.log(ok.every(([, o]) => o) ? 'ALL PASS' : 'FAILED');
  process.exit(ok.every(([, o]) => o) ? 0 : 1);
}
