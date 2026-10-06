// Public ingestion configuration shared with sati.sh and Running Digitally.
// This is a browser ingestion token, never a personal API credential.
export const TOKEN = 'phc_BkdUdNEyEGwC5U9w7Zu3mtoMcEgzvur9iXYvvxv3cjf2';
export const HOST = 'https://posthog.sati.sh';
export const SITE = 'radhouse.runningdigitally.com';
export const PREFERENCE_KEY = 'radhouse-analytics-disabled';
const campaigns = new Set(['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term']);
export function environment(hostname, preview) {
  if (hostname === SITE) return 'production';
  if (['localhost', '127.0.0.1', '[::1]'].includes(hostname) && preview) return 'preview';
  return null;
}
export function privacyRequested(nav, dnt) {
  return nav.globalPrivacyControl === true || nav.doNotTrack === '1' || dnt === '1';
}
export function safeUrl(value, base = `https://${SITE}`) {
  if (!value || value === '$direct') return value || '';
  try {
    const url = new URL(value, base);
    if (!['http:', 'https:'].includes(url.protocol)) return '';
    url.username = ''; url.password = ''; url.hash = '';
    for (const key of Array.from(url.searchParams.keys())) if (!campaigns.has(key)) url.searchParams.delete(key);
    return url.toString();
  } catch { return ''; }
}
export function redact(value, key = '') {
  if (Array.isArray(value)) return value.map(item => redact(item));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([name]) => !/^(?:email|password|token|authorization|cookie|access_token|refresh_token|code|state)$/i.test(name))
    .map(([name, item]) => [/^https?:\/\//.test(name) ? safeUrl(name) : name, redact(item, name)]));
  if (typeof value === 'string' && /(?:url|href|src|referrer)$/i.test(key)) return safeUrl(value);
  return value;
}
export function eventProperties(properties, label, path) {
  return { ...redact(properties), token: TOKEN, site: SITE, environment: label, page_path: path };
}
