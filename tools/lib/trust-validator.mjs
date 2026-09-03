// @ts-check
/**
 * trust-validator.mjs — VENDORED from career-ops.
 * Source: santifer/career-ops @ 933c353, providers/_trust-validator.mjs (MIT).
 * Copied verbatim (logic unchanged) so the cockpit is self-contained.
 * Re-diff against upstream if career-ops updates the heuristics.
 *
 * Enriches a job {url, company} with { score 0-100, flags[], level }.
 * Never drops jobs — flag only. Pure function, zero deps.
 *
 * V1 heuristics: (1) URL structure, (2) missing apply URL,
 * (3) suspicious domain, (4) company ↔ domain mismatch (ATS allowlisted).
 */

/** @type {string[]} */
const DEFAULT_SUSPICIOUS_DOMAINS = [
  'bit.ly', 'tinyurl.com', 't.co', 'forms.gle',
  'goo.gl', 'shorturl.at', 'rebrand.ly', 'cutt.ly',
];

/** @type {string[]} */
const DEFAULT_ATS_ALLOWLIST = [
  'greenhouse.io', 'ashbyhq.com', 'lever.co', 'workday.com',
  'smartrecruiters.com', 'jobvite.com', 'myworkdayjobs.com', 'recruitee.com',
  'workable.com', 'icims.com', 'taleo.net', 'applytojob.com',
  'breezy.hr', 'jazz.co', 'bamboohr.com', 'teamtailor.com',
];

/** @type {Record<string, number>} */
const PENALTIES = {
  invalid_url: 50,
  missing_apply_url: 40,
  suspicious_domain: 25,
  company_domain_mismatch: 15,
};

/** @param {number} score @returns {'high' | 'medium' | 'low'} */
export function classifyTrustLevel(score) {
  if (score >= 90) return 'high';
  if (score >= 60) return 'medium';
  return 'low';
}

/** @param {string} url @returns {{ valid: boolean, flag?: string }} */
export function validateUrl(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return { valid: false, flag: 'invalid_url' };
    }
    return { valid: true };
  } catch {
    return { valid: false, flag: 'invalid_url' };
  }
}

/** @param {string} hostname @param {string[]} domainList @returns {boolean} */
export function matchesDomainList(hostname, domainList) {
  for (const domain of domainList) {
    if (hostname === domain || hostname.endsWith('.' + domain)) return true;
  }
  return false;
}

/** @param {string} company @param {string} hostname @returns {boolean} true if company matches hostname */
export function companyMatchesHostname(company, hostname) {
  if (!company || !hostname) return true; // can't evaluate → no flag
  const normalized = company.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
  if (!normalized) return true;
  const slug = normalized.replace(/\s+/g, '');
  if (hostname.includes(slug)) return true;
  const words = normalized.split(/\s+/).filter(w => w.length >= 3);
  for (const word of words) {
    if (hostname.includes(word)) return true;
  }
  return false;
}

/**
 * @param {object} [config]
 * @param {boolean} [config.enabled]
 * @param {string[]} [config.suspicious_domains]
 * @param {string[]} [config.ats_allowlist]
 * @returns {(job: { url?: string, company?: string }) => { score: number, flags: string[], level: 'high' | 'medium' | 'low' }}
 */
export function buildTrustValidator(config) {
  if (!config || config.enabled === false) {
    return () => ({ score: 100, flags: [], level: /** @type {const} */ ('high') });
  }
  const suspiciousDomains = (Array.isArray(config.suspicious_domains)
    ? config.suspicious_domains : DEFAULT_SUSPICIOUS_DOMAINS)
    .map(d => String(d).toLowerCase().trim()).filter(Boolean);
  const atsAllowlist = (Array.isArray(config.ats_allowlist)
    ? config.ats_allowlist : DEFAULT_ATS_ALLOWLIST)
    .map(d => String(d).toLowerCase().trim()).filter(Boolean);

  return (job) => {
    /** @type {string[]} */
    const flags = [];
    let score = 100;
    const url = typeof job.url === 'string' ? job.url.trim() : '';

    if (!url) {
      flags.push('missing_apply_url');
      score -= PENALTIES.missing_apply_url;
      const clamped = Math.max(0, score);
      return { score: clamped, flags, level: classifyTrustLevel(clamped) };
    }
    const urlCheck = validateUrl(url);
    if (!urlCheck.valid) {
      flags.push('invalid_url');
      score -= PENALTIES.invalid_url;
      const clamped = Math.max(0, score);
      return { score: clamped, flags, level: classifyTrustLevel(clamped) };
    }
    let hostname = '';
    try {
      hostname = new URL(url).hostname.toLowerCase();
    } catch {
      const clamped = Math.max(0, score);
      return { score: clamped, flags, level: classifyTrustLevel(clamped) };
    }
    if (matchesDomainList(hostname, suspiciousDomains)) {
      flags.push('suspicious_domain');
      score -= PENALTIES.suspicious_domain;
    }
    const company = typeof job.company === 'string' ? job.company.trim() : '';
    if (company && !matchesDomainList(hostname, atsAllowlist)) {
      if (!companyMatchesHostname(company, hostname)) {
        flags.push('company_domain_mismatch');
        score -= PENALTIES.company_domain_mismatch;
      }
    }
    score = Math.max(0, Math.min(100, score));
    return { score, flags, level: classifyTrustLevel(score) };
  };
}
