#!/usr/bin/env node
// @ts-check
/**
 * ats_scan.mjs — free, zero-token ATS discovery for the cockpit.
 *
 * Thin runner over career-ops's provider modules (santifer/career-ops, MIT),
 * vendored under tools/lib/providers so a fresh clone needs no sibling checkout. We skip their scan.mjs
 * (1285 lines, welded to their apply-centric tracker); this runner only does the
 * one thing we want: hit each portal's public ATS JSON API and emit normalized
 * rows in OUR shape, straight into DAILY_RUN Step 2 (dedup) → the scoring gate (P1_06 §5).
 *
 * Contract (providers/_types.js): each provider default-exports
 *   { id, fetch(entry, ctx) -> Promise<Job[]> }   Job = {title,url,company,location,postedAt?}
 * ctx comes from providers/_http.mjs `makeHttpCtx()` (native fetch, SSRF-guarded per provider).
 *
 * Config: tools/portals.json
 *   { "since_days": 3,
 *     "title_filter": { "positive": ["quality","supplier quality",...], "negative": ["intern"] },
 *     "portals": [ { "name":"Example Corp", "provider":"greenhouse",
 *                    "api":"https://boards-api.greenhouse.io/v1/boards/examplecorp/jobs" }, ... ] }
 *   Workday/Ashby/Lever entries use "careers_url" instead of "api"; the provider derives the endpoint.
 *
 * Usage:
 *   node tools/ats_scan.mjs                        # daily: uses tools/portals.json (since_days=7)
 *   node tools/ats_scan.mjs --since-days 120       # one-time BACKFILL: sweep the open-role backlog
 *   node tools/ats_scan.mjs path/to/portals.json   # explicit config
 *   node tools/ats_scan.mjs --self-test            # offline asserts, exit 0/1
 * Output: JSON array of rows on stdout; per-portal errors go to stderr, never abort the run.
 */
import { readFileSync, existsSync} from 'node:fs';
import { pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PROVIDERS_DIR = join(HERE, 'lib', 'providers');
// /setup writes tools/portals.json; the .example file is the pre-setup fallback
// so a fresh clone runs instead of crashing on a missing config.
const DEFAULT_CONFIG = existsSync(join(HERE, 'portals.json'))
  ? join(HERE, 'portals.json')
  : join(HERE, 'portals.example.json');
const CONCURRENCY = 5;

/** Map a career-ops Job → our Apify-shaped row. The ATS url IS the apply url (trust-validator loves it). */
export function mapJob(job, providerId) {
  const epoch = typeof job.postedAt === 'number' ? job.postedAt : null;
  return {
    title: job.title || '',
    companyName: job.company || '',
    location: job.location || '',
    link: job.url,
    applyUrl: job.url,                       // ATS apply URL == source of truth
    postedAt: epoch ? new Date(epoch).toISOString().slice(0, 10) : '',
    postedAtEpoch: epoch,
    seniorityLevel: '',
    description: job.description || '',
    reqId: job.reqId || '',
    source: `ats:${providerId}`,
  };
}

/** Case-insensitive substring title filter. Absent/empty filter → pass all. */
export function passesTitleFilter(title, filter) {
  if (!filter) return true;
  const t = String(title || '').toLowerCase();
  const neg = (filter.negative || []).map(s => s.toLowerCase());
  if (neg.some(k => k && t.includes(k))) return false;
  const pos = (filter.positive || []).map(s => s.toLowerCase());
  if (pos.length === 0) return true;
  return pos.some(k => k && t.includes(k));
}

/** Location filter, ported verbatim from career-ops scan.mjs buildLocationFilter.
 * Order: empty location passes; always_allow wins over block; block rejects;
 * allow empty passes; else must match an allow keyword. All case-insensitive substring. */
function normKeywords(v) {
  if (v == null) return [];
  return (Array.isArray(v) ? v : [v]).filter(k => typeof k === 'string').map(k => k.toLowerCase().trim()).filter(Boolean);
}
export function passesLocationFilter(location, filter) {
  if (!filter) return true;
  if (typeof location !== 'string' || location.trim() === '') return true;
  const lower = location.toLowerCase();
  const alwaysAllow = normKeywords(filter.always_allow);
  const allow = normKeywords(filter.allow);
  const block = normKeywords(filter.block);
  if (alwaysAllow.length && alwaysAllow.some(k => lower.includes(k))) return true;
  if (block.length && block.some(k => lower.includes(k))) return false;
  if (allow.length === 0) return true;
  return allow.some(k => lower.includes(k));
}

/** Undated rows always pass (don't punish missing data); dated rows must be within the window. */
export function isFresh(row, sinceMs) {
  if (!sinceMs) return true;
  if (row.postedAtEpoch == null) return true;
  return row.postedAtEpoch >= sinceMs;
}

async function mapPool(items, n, fn) {
  const out = [];
  let i = 0;
  async function worker() {
    while (i < items.length) {
      const idx = i++;
      out[idx] = await fn(items[idx], idx);
    }
  }
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, worker));
  return out;
}

const providerCache = new Map();
async function loadProvider(id) {
  if (providerCache.has(id)) return providerCache.get(id);
  const mod = await import(pathToFileURL(join(PROVIDERS_DIR, `${id}.mjs`)).href);
  const provider = mod.default;
  if (!provider || typeof provider.fetch !== 'function') throw new Error(`provider "${id}" has no fetch()`);
  providerCache.set(id, provider);
  return provider;
}

async function run(configPath, sinceDaysOverride) {
  const cfg = JSON.parse(readFileSync(configPath, 'utf8'));
  const portals = (cfg.portals || []).filter(p => p.enabled !== false);
  const sinceDays = sinceDaysOverride != null ? sinceDaysOverride : cfg.since_days;
  const sinceMs = sinceDays ? Date.now() - sinceDays * 86_400_000 : null;
  const { makeHttpCtx } = await import(pathToFileURL(join(PROVIDERS_DIR, '_http.mjs')).href);
  const ctx = makeHttpCtx();
  // Providers that paginate newest-first (e.g. workday) read ctx.sinceMs to
  // early-stop once a page is past the freshness window — bounds huge tenants
  // (GM/Caterpillar/GE Vernova = 900-2200 postings) to a few pages instead of dozens.
  if (sinceMs) ctx.sinceMs = sinceMs;

  const perPortal = await mapPool(portals, CONCURRENCY, async (entry) => {
    try {
      const provider = await loadProvider(entry.provider);
      const jobs = await provider.fetch(entry, ctx);
      const rows = jobs.map(j => mapJob(j, entry.provider))
        .filter(r => passesTitleFilter(r.title, cfg.title_filter))
        .filter(r => passesLocationFilter(r.location, cfg.location_filter))
        .filter(r => isFresh(r, sinceMs));
      console.error(`  ${entry.name} [${entry.provider}]: ${jobs.length} fetched → ${rows.length} kept`);
      return rows;
    } catch (err) {
      console.error(`  ⚠️  ${entry.name} [${entry.provider}]: ${err.message}`);
      return [];
    }
  });

  const all = perPortal.flat();
  await enrichGreenhouseDescriptions(all, portals, ctx);
  await enrichWorkdayDescriptions(all, portals);
  await enrichSmartRecruitersDescriptions(all, portals);
  console.error(`ats_scan: ${all.length} rows from ${portals.length} portals`);
  process.stdout.write(JSON.stringify(all, null, 2) + '\n');
}

/**
 * Fill in `description` for Greenhouse rows.
 *
 * career-ops' greenhouse provider maps title/url/company/location/postedAt and
 * drops `content`, so every ats_direct row reaches the ranker with an empty
 * description — 44 of 163 rows on 2026-09-09. Those rows cannot be visa-gated
 * (P1_06 §3 needs the JD text) and cannot be keyword-scored, so they land in
 * `confidence: low` and never make a shortlist. That silently blanks the anchor
 * employers: 7 of our 15 portals are Greenhouse, including Lucid and Archer.
 *
 * The fix is one query parameter — `?content=true` returns the full description
 * inline, same request, no extra call, no cost. We do it here rather than in the
 * provider because career-ops is an upstream sibling clone we do not edit.
 * One extra request per Greenhouse BOARD (not per job).
 */
async function enrichGreenhouseDescriptions(rows, portals, ctx) {
  const boards = portals.filter(p => p.provider === 'greenhouse' && p.api);
  if (boards.length === 0) return;

  let filled = 0;
  await mapPool(boards, CONCURRENCY, async (entry) => {
    try {
      const url = new URL(entry.api);
      url.searchParams.set('content', 'true');
      const json = /** @type {any} */ (await ctx.fetchJson(url.toString(), { redirect: 'error' }));
      const byUrl = new Map();
      for (const j of (json?.jobs || [])) {
        if (j.absolute_url && j.content) byUrl.set(j.absolute_url, j.content);
      }
      for (const r of rows) {
        if (r.description || !byUrl.has(r.link)) continue;
        r.description = decodeGreenhouseContent(byUrl.get(r.link));
        filled++;
      }
    } catch (err) {
      // Never abort a scan over enrichment: a row with no description is still
      // a usable lead, it just cannot be scored on coverage.
      console.error(`  ⚠️  ${entry.name} [greenhouse content]: ${err.message}`);
    }
  });
  if (filled) console.error(`  greenhouse: filled ${filled} descriptions via ?content=true`);
}

const UA = 'Mozilla/5.0 (compatible; JobSearchPipeline/1.0)';

/** Pure: pick the fields we keep from a Workday CXS job-detail response. */
export function parseWorkdayDetail(json) {
  const info = json?.jobPostingInfo || {};
  return {
    description: decodeGreenhouseContent(info.jobDescription || ''),
    reqId: info.jobReqId || '',
    postedAt: typeof info.startDate === 'string' ? info.startDate.slice(0, 10) : '',
  };
}

/**
 * Fill in `description` + `reqId` for Workday rows (audit R2).
 *
 * The listing endpoint carries no description. The per-job detail endpoint
 * `/wday/cxs/<tenant>/<site><externalPath>` does, but answers 403 without a
 * session cookie — one GET of the careers page per tenant provides it. One
 * request per job, only for rows that already passed the title/location/date
 * filters, so a 2,000-posting tenant costs a handful of calls, not thousands.
 */
async function enrichWorkdayDescriptions(rows, portals) {
  const tenants = portals.filter(p => p.provider === 'workday' && p.careers_url);
  let filled = 0;
  await mapPool(tenants, CONCURRENCY, async (entry) => {
    const m = String(entry.careers_url).match(/^https:\/\/([\w-]+)\.(wd[\w-]*)\.myworkdayjobs\.com\/(?:[a-z]{2}-[A-Z]{2}\/)?([^/?#]+)/);
    if (!m) return;
    const [, tenant, instance, site] = m;
    const origin = `https://${tenant}.${instance}.myworkdayjobs.com`;
    const jobBase = `${origin}/${site}`;
    const mine = rows.filter(r => !r.description && r.link.startsWith(jobBase + '/job/'));
    if (mine.length === 0) return;
    try {
      const first = await fetch(entry.careers_url, { headers: { 'user-agent': UA }, redirect: 'follow' });
      const cookies = (first.headers.getSetCookie?.() || []).map(c => c.split(';')[0]).join('; ');
      await mapPool(mine, CONCURRENCY, async (r) => {
        try {
          const detail = `${origin}/wday/cxs/${tenant}/${site}${r.link.slice(jobBase.length)}`;
          const res = await fetch(detail, { headers: { 'user-agent': UA, accept: 'application/json', cookie: cookies } });
          if (!res.ok) return;
          const d = parseWorkdayDetail(await res.json());
          if (d.description) { r.description = d.description; filled++; }
          if (d.reqId) r.reqId = d.reqId;
          if (!r.postedAt && d.postedAt) r.postedAt = d.postedAt;
        } catch { /* a row without a description is still a lead */ }
      });
    } catch (err) {
      console.error(`  ⚠️  ${entry.name} [workday detail]: ${err.message}`);
    }
  });
  if (filled) console.error(`  workday: filled ${filled} descriptions via job detail`);
}

/** Pure: flatten a SmartRecruiters posting-detail response. */
export function parseSmartRecruitersDetail(json) {
  const s = json?.jobAd?.sections || {};
  const text = ['jobDescription', 'qualifications', 'additionalInformation']
    .map(k => s[k]?.text || '').filter(Boolean).join('\n\n');
  return {
    description: decodeGreenhouseContent(text),
    reqId: json?.refNumber || '',
    postedAt: typeof json?.releasedDate === 'string' ? json.releasedDate.slice(0, 10) : '',
  };
}

/** Fill in `description` + `reqId` for SmartRecruiters rows via the public posting-detail API. */
async function enrichSmartRecruitersDescriptions(rows, portals) {
  const boards = portals.filter(p => p.provider === 'smartrecruiters' && p.careers_url);
  let filled = 0;
  await mapPool(boards, CONCURRENCY, async (entry) => {
    let slug;
    try { slug = new URL(entry.careers_url).pathname.split('/').filter(Boolean)[0]; } catch { return; }
    if (!slug) return;
    const mine = rows.filter(r => !r.description && /smartrecruiters\.com\/[^/]+\/(?:postings\/)?\d+/.test(r.link));
    await mapPool(mine, CONCURRENCY, async (r) => {
      const id = (r.link.match(/(\d{6,})/) || [])[1];
      if (!id) return;
      try {
        const res = await fetch(`https://api.smartrecruiters.com/v1/companies/${slug}/postings/${id}`, { headers: { 'user-agent': UA } });
        if (!res.ok) return;
        const d = parseSmartRecruitersDetail(await res.json());
        if (d.description) { r.description = d.description; filled++; }
        if (d.reqId) r.reqId = d.reqId;
        if (!r.postedAt && d.postedAt) r.postedAt = d.postedAt;
      } catch { /* leave the row as a lead without a description */ }
    });
  });
  if (filled) console.error(`  smartrecruiters: filled ${filled} descriptions via posting detail`);
}

/** Greenhouse returns HTML-escaped markup; the gates and keyword engine want text. */
export function decodeGreenhouseContent(html) {
  return String(html || '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ')
    .replace(/<\/(p|div|li|h[1-6]|tr)>/gi, '\n')
    .replace(/<li[^>]*>/gi, '- ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function selfTest() {
  let pass = 0, total = 0;
  const check = (name, cond) => { total++; if (cond) pass++; else console.error(`FAIL: ${name}`); };

  const r = mapJob({ title: 'SQE', url: 'https://boards.greenhouse.io/x/jobs/1', company: 'Example Corp', location: 'CA', postedAt: 1_700_000_000_000 }, 'greenhouse');
  check('map: link==applyUrl==url', r.link === r.applyUrl && r.link === 'https://boards.greenhouse.io/x/jobs/1');
  check('map: companyName from company', r.companyName === 'Example Corp');
  check('map: postedAt ISO date', r.postedAt === '2023-11-14');
  check('map: source tag', r.source === 'ats:greenhouse');
  const u = mapJob({ title: 'X', url: 'https://a/b', company: 'C', location: '' }, 'lever');
  check('map: undated → empty postedAt + null epoch', u.postedAt === '' && u.postedAtEpoch === null);

  const f = { positive: ['quality', 'supplier quality'], negative: ['intern', 'senior manager'] };
  check('filter: positive match', passesTitleFilter('Supplier Quality Engineer', f) === true);
  check('filter: no positive', passesTitleFilter('Software Developer', f) === false);
  check('filter: negative wins', passesTitleFilter('Quality Intern', f) === false);
  check('filter: absent → pass', passesTitleFilter('anything', null) === true);
  check('filter: empty positive → pass after neg', passesTitleFilter('anything', { positive: [], negative: ['php'] }) === true);

  const lf = { always_allow: ['united states'], block: ['india', 'germany', 'france'], allow: [] };
  check('loc: empty passes', passesLocationFilter('', lf) === true);
  check('loc: US city passes (allow empty)', passesLocationFilter('Warren, MI', lf) === true);
  check('loc: explicit US passes', passesLocationFilter('Flint, MI, United States', lf) === true);
  check('loc: blocked country fails', passesLocationFilter('Lyon, France', lf) === false);
  check('loc: always_allow beats block', passesLocationFilter('Remote - United States / India', lf) === true);
  check('loc: no filter → pass', passesLocationFilter('Anywhere', null) === true);

  const now = Date.now();
  check('fresh: undated passes', isFresh({ postedAtEpoch: null }, now - 86_400_000) === true);
  check('fresh: recent passes', isFresh({ postedAtEpoch: now }, now - 86_400_000) === true);
  check('fresh: stale fails', isFresh({ postedAtEpoch: now - 5 * 86_400_000 }, now - 3 * 86_400_000) === false);
  check('fresh: no window → pass', isFresh({ postedAtEpoch: now - 999 * 86_400_000 }, null) === true);

  const wd = parseWorkdayDetail({ jobPostingInfo: { jobDescription: '<p>Do <b>SPC</b></p><ul><li>GD&amp;T</li></ul>', jobReqId: 'JR-1', startDate: '2026-09-11' } });
  check('workday detail: description text', wd.description.includes('Do SPC') && wd.description.includes('- GD&T'));
  check('workday detail: reqId + date', wd.reqId === 'JR-1' && wd.postedAt === '2026-09-11');
  const sr = parseSmartRecruitersDetail({ refNumber: 'REF1', releasedDate: '2026-09-10T00:00:00Z', jobAd: { sections: { jobDescription: { text: '<p>A</p>' }, qualifications: { text: '<p>B</p>' } } } });
  check('smartrecruiters detail: sections joined', sr.description === 'A\n\nB' && sr.reqId === 'REF1' && sr.postedAt === '2026-09-10');

  console.error(`ats_scan self-test: ${pass}/${total} passed`);
  process.exit(pass === total ? 0 : 1);
}

const args = process.argv.slice(2);
if (args.includes('--self-test')) selfTest();
const si = args.indexOf('--since-days');
const sinceDaysOverride = si !== -1 ? Number(args[si + 1]) : null;
const configPath = args.find(a => !a.startsWith('--') && a !== String(sinceDaysOverride)) || DEFAULT_CONFIG;
run(configPath, sinceDaysOverride);
