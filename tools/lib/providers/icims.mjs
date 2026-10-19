// @ts-check
// iCIMS careers-portal provider (Joby). The portal has no JSON API, so this reads the public
// search pages (`/jobs/search?ss=1&in_iframe=1&pr=N`) and each posting's schema.org JSON-LD for the JD.
// iCIMS publishes no real posted date (its datePosted is synthetic), so rows carry no postedAt and the
// seen-ledger decides what is new.

const MAX_PAGES = 40;
const strip = (s) => s.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&ndash;/g, '-').replace(/&#39;/g, "'").replace(/\s+/g, ' ').trim();

/** Pure: job cards from one search page. */
export function parseIcimsList(html) {
  const out = [];
  for (const card of html.split('iCIMS_JobCardItem').slice(1)) {
    const a = card.match(/href="(https:\/\/[^"]+\/jobs\/(\d+)\/[^"]*?\/job)[^"]*"[^>]*>[\s\S]*?<h3[^>]*>([\s\S]*?)<\/h3>/);
    if (!a) continue;
    const loc = card.match(/Job Locations<\/span>\s*<span[^>]*>([\s\S]*?)<\/span>/);
    const id = card.match(/>ID<\/dt>\s*<dd[^>]*><span[^>]*>([\s\S]*?)<\/span>/);
    out.push({ url: a[1], title: strip(a[3]), location: loc ? strip(loc[1]).split('|').map(l => l.trim().replace(/^US-([A-Z]{2})-(.+)$/, '$2, $1, United States')).join('; ') : '', reqId: id ? strip(id[1]) : '' });
  }
  return out;
}

/** Pure: description text from the JSON-LD block on a posting page. */
export function parseIcimsDetail(html) {
  const m = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  if (!m) return '';
  try { return strip(String(JSON.parse(m[1]).description || '').replace(/<\/(p|li|h\d)>/g, '\n')); } catch { return ''; }
}

/** @type {import('./_types.js').Provider} */
export default {
  id: 'icims',
  detect() { return null; },
  async fetch(entry, ctx) {
    const origin = new URL(entry.careers_url).origin;
    const jobs = [];
    for (let pr = 0; pr < MAX_PAGES; pr++) {
      const res = await fetch(`${origin}/jobs/search?ss=1&in_iframe=1&pr=${pr}`, { headers: { 'user-agent': 'Mozilla/5.0 (compatible; JobSearchPipeline/1.0)' } });
      if (!res.ok) throw new Error(`HTTP ${res.status} on page ${pr}`);
      const rows = parseIcimsList(await res.text());
      if (!rows.length) break;
      jobs.push(...rows);
    }
    const uniq = [...new Map(jobs.map(j => [j.url, j])).values()];
    for (let i = 0; i < uniq.length; i += 6) {   // small batches: one tenant, be polite
      await Promise.all(uniq.slice(i, i + 6).map(async (j) => {
        try {
          const r = await fetch(j.url + '?in_iframe=1', { headers: { 'user-agent': 'Mozilla/5.0 (compatible; JobSearchPipeline/1.0)' } });
          if (r.ok) j.description = parseIcimsDetail(await r.text());
        } catch { /* a row without a JD is still a lead */ }
      }));
    }
    return uniq.map(j => ({ ...j, company: entry.name }));
  },
};
