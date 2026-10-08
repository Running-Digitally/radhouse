import { TOKEN, HOST, SITE, PREFERENCE_KEY, environment, privacyRequested, safeUrl, eventProperties } from './analytics-policy.js';
const root = document.querySelector('[data-public-site]');
const label = environment(location.hostname, new URL(location.href).searchParams.get('analytics') === 'preview');
function allowed() {
  if (!root || !label || location.pathname !== '/' || privacyRequested(navigator, window.doNotTrack)) { return false; }
  try { return localStorage.getItem(PREFERENCE_KEY) !== 'true'; } catch { return false; }
}
function linkPlacement(link) {
  for (const [selector, placement] of [['header', 'header'], ['footer', 'footer'],
    ['.opening', 'opening'], ['#vision', 'vision'], ['#progress', 'progress']]) {
    if (link.closest(selector)) return placement;
  }
  return 'invitation';
}
async function start() {
  if (!allowed()) { if (root) { root.dataset.analyticsState = 'disabled'; } return; }
  root.dataset.analyticsState = 'loading';
  try {
    const { PostHog } = await import('./vendor/posthog-1.436.1.js');
    if (!allowed()) { return; }
    const client = new PostHog();
    client.init(TOKEN, {
      api_host: HOST, ui_host: HOST, defaults: '2026-05-30',
      persistence: 'localStorage', persistence_name: 'radhouse_public_analytics',
      cross_subdomain_cookie: false, consent_persistence_name: 'radhouse_analytics_consent',
      person_profiles: 'never', respect_dnt: true,
      disable_capture_url_hashes: true, capture_pageview: false, capture_pageleave: false,
      autocapture: { dom_event_allowlist: ['click'], element_allowlist: ['a', 'button', 'summary'], css_selector_allowlist: ['[data-public-site]'], capture_copied_text: false },
      capture_heatmaps: true, capture_dead_clicks: false, rageclick: false,
      capture_performance: { web_vitals: true, network_timing: false, web_vitals_attribution: false },
      capture_exceptions: false, enable_recording_console_log: false,
      disable_surveys: true, disable_product_tours: true, disable_web_experiments: true,
      session_recording: {
        maskAllInputs: true,
        blockSelector: '[data-private], .ph-no-capture, iframe, input[type="hidden"], input[type="file"], [contenteditable]',
        maskTextSelector: '[data-sensitive], .ph-mask',
        maskAttributeFn: (name, value) => /^(?:href|src)$/i.test(name) ? safeUrl(value, location.origin) : value,
        recordCrossOriginIframes: false, recordHeaders: false, recordBody: false,
        captureCanvas: { recordCanvas: false }, captureJsonLd: false, sampleRate: 1,
      },
      before_send: event => event && allowed() ? { ...event, properties: eventProperties(event.properties, label, location.pathname) } : null,
    });
    const capture = (name, properties = {}) => { if (allowed()) { client.capture(name, properties); } };
    client.register({ site: SITE, environment: label, page_path: '/' });
    capture('$pageview', { $current_url: safeUrl(location.href) });
    window.addEventListener('radhouse:interaction', event => {
      const permitted = new Set(['conversation_example_step_selected']);
      if (permitted.has(event.detail?.name)) { capture(event.detail.name, { step: event.detail.properties?.step, source: event.detail.properties?.source }); }
    });
    window.addEventListener('click', event => {
      if (event.defaultPrevented || !(event.target instanceof Element) || event.target.closest('[data-private], .ph-no-capture')) { return; }
      const link = event.target.closest('a');
      if (!link) { return; }
      const href = link.getAttribute('href') || '';
      const placement = linkPlacement(link);
      if (href.startsWith('#')) { capture('navigation_clicked', { section: href.slice(1), placement }); }
      else if (/^https?:/.test(href)) { capture('outbound_link_clicked', { destination: safeUrl(href), placement }); }
    });
    root.addEventListener('toggle', event => {
      if (event.target instanceof HTMLDetailsElement) { capture('project_details_toggled', { section: event.target.id, open: event.target.open }); }
    }, true);
    const seen = new Set();
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) { if (entry.isIntersecting && !seen.has(entry.target.id)) {
        seen.add(entry.target.id); capture('section_viewed', { section: entry.target.id }); observer.unobserve(entry.target);
      } }
    }, { threshold: .2 });
    document.querySelectorAll('#vision, #progress, .invitation').forEach(section => {
      if (!section.id) { section.id = 'contribute'; } observer.observe(section);
    });
    let activeSeconds = 0;
    const timer = setInterval(() => { if (document.visibilityState === 'visible') { activeSeconds += 5; } }, 5000);
    const depths = new Set(); let frame = 0;
    window.addEventListener('scroll', () => {
      if (frame) { return; }
      frame = requestAnimationFrame(() => {
        frame = 0;
        const span = document.documentElement.scrollHeight - innerHeight;
        if (span <= 0) { return; }
        const depth = 100 * scrollY / span;
        for (const percent of [25, 50, 75, 90]) { if (depth >= percent && !depths.has(percent)) {
          depths.add(percent); capture('reading_depth_reached', { percent });
        } }
      });
    }, { passive: true });
    // Keep observers across a BFCache pagehide; a restored page retains this session.
    window.addEventListener('pagehide', event => { capture('$pageleave', { active_seconds: activeSeconds }); if (!event.persisted) { clearInterval(timer); observer.disconnect(); } });
    root.dataset.analyticsState = 'ready';
  } catch { root.dataset.analyticsState = 'unavailable'; }
}
await start();
