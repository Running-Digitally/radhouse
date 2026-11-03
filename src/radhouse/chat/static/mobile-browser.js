"use strict";
// Trusted same-origin canvas only. Native owns all navigation and control UI.
// Remote websites execute in the isolated browser and contribute pixels only.
(() => {
  const tab = new URL(location.href).searchParams.get('tab');
  if (!/^[a-f0-9-]{36}$/.test(tab || '')) return;
  const canvas = document.getElementById('canvas');
  let presentation = 'preview', state = null, csrf = '', busy = false, reading = false;
  let frame = null, streamKey = '', playback = 'connecting', inputReady = false;
  let epoch = 0, uncertain = false, notice = '', lastActivity = 0, lastHeartbeat = 0;
  let timer = null, connectTimer = null, authenticated = false, searchEngine = null;
  const post = value => window.ReactNativeWebView?.postMessage(JSON.stringify({schema:'radhouse.mobile-browser.v1', ...value}));
  const human = () => state?.state === 'live' && state.control?.mode === 'human'
    && typeof state.control.lease_id === 'string' && state.control.lease_expires_at > Date.now()/1000;
  const zoomed = () => presentation === 'full' && canvas.dataset.zoom === 'true';
  const readOnly = () => presentation === 'preview' || !human() || uncertain || zoomed();
  function syncInput() { if (frame) frame.inert = readOnly(); }
  const binding = () => ({generation:state.generation, revision:state.control.revision, lease_id:state.control.lease_id || null});
  const previewVisible = () => state?.state === 'live' && state.agent_active === true && state.control?.mode === 'agent';
  function publish(event = 'state') {
    const hidden = presentation === 'preview' && !previewVisible();
    post({event, authenticated, state:state?.state || 'unavailable',
      active:previewVisible(), mode:state?.control?.mode || 'paused', human:human(),
      observing:human() && state.control.observation_mode === 'observe',
      canTake:state?.control?.can_take === true || state?.control?.mode === 'human' && !human(),
      canReturn:human() && state?.can_return === true,
      title:hidden ? '' : String(state?.title || '').slice(0,512),
      url:hidden ? '' : String(state?.url || '').slice(0,4096),
      busy, uncertain, playback, inputReady:human() && inputReady && !uncertain && !zoomed(),
      notice, previousDownloadsUnavailable:state?.downloads?.previous_unavailable === true});
  }
  function clearFrame() {
    clearTimeout(connectTimer);
    try { frame?.contentWindow?.radhouseInput?.hide(); } catch { /* A replaced document has no input authority. */ }
    frame?.remove(); frame = null; streamKey = ''; inputReady = false; playback = 'connecting';
  }
  function mount() {
    const stream = state?.stream;
    const allowed = authenticated && !document.hidden && state?.state === 'live'
      && (presentation === 'full' || previewVisible());
    if (!allowed || stream?.path !== '/chat/browser/stream/index.html'
        || !/^[A-Za-z0-9_-]{32,128}$/.test(stream?.token || '')) { clearFrame(); return; }
    canvas.classList.toggle('preview', presentation === 'preview');
    canvas.classList.toggle('zoom', zoomed());
    syncInput();
    const key = state.generation + ':' + stream.token;
    if (frame && key === streamKey) return;
    clearFrame(); streamKey = key;
    frame = document.createElement('iframe');
    frame.title = 'Live remote browser'; frame.allow = 'autoplay'; frame.tabIndex = -1;
    frame.inert = readOnly();
    frame.src = stream.path + '?connection=' + crypto.randomUUID() + '#token=' + stream.token;
    canvas.append(frame);
    connectTimer = setTimeout(() => { if (frame && playback === 'connecting') { playback = 'stalled'; publish(); } },15000);
  }
  async function request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(),15000);
    try {
      const response = await fetch(path, {method:body === undefined ? 'GET' : 'POST',
        credentials:'same-origin', cache:'no-store', redirect:'error', signal:controller.signal,
        headers:{'Content-Type':'application/json','X-Radhouse-Browser-Tab':tab,
          ...(body === undefined ? {} : {'X-Radhouse-CSRF':csrf})},
        ...(body === undefined ? {} : {body:JSON.stringify(body)})});
      if ([401,403].includes(response.status)) { authenticated = false; clearFrame(); publish('expired'); throw new Error('expired'); }
      if (!response.ok || !response.headers.get('content-type')?.startsWith('application/json')) throw new Error('unavailable');
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  function accept(value) {
    if (!value || !['live','idle','starting','unavailable'].includes(value.state)) throw new Error('invalid');
    if (state?.generation === value.generation && state?.control?.revision > value.control?.revision) return false;
    state = value;
    mount();
    if (frame) frame.inert = readOnly();
    publish();
    return true;
  }
  async function refresh(reconcile = false) {
    // Native keeps an inactive preview hidden until status says the agent is
    // browsing. Reading status must work there; stream mounting and every
    // mutation remain visibility-gated. Native destroys us in background.
    if (!authenticated || document.hidden && presentation === 'full' || reading || busy) return;
    reading = true; const expected = epoch;
    try {
      const value = await request('/chat/browser');
      if (expected === epoch) {
        if (accept(value) && reconcile) {
          uncertain = false;
          notice = '';
          syncInput();
          publish();
        }
      }
    }
    catch { if (expected === epoch) { clearFrame(); notice = 'Connection lost. Check the browser before continuing.'; publish(); } }
    finally { reading = false; }
  }
  async function act(path, body, returning = false) {
    if (busy || !authenticated || document.hidden || uncertain) return;
    busy = true; notice = ''; const expected = ++epoch; lastActivity = Date.now(); publish();
    try {
      const value = await request(path,body);
      if (expected !== epoch) return;
      if (returning) { clearFrame(); state = null; publish('returned'); }
      else accept(value);
    } catch {
      if (expected === epoch && authenticated) {
        uncertain = true; inputReady = false;
        if (frame) frame.inert = true;
        notice = 'That action could not be confirmed. It was not retried. Refresh to check the current state.';
      }
    } finally { busy = false; publish(); }
  }
  async function input(method, value) {
    if (presentation !== 'full' || document.hidden || !human() || busy || uncertain || zoomed() || !inputReady) return;
    lastActivity = Date.now(); busy = true; notice = ''; publish();
    try {
      const helper = frame?.contentWindow?.radhouseInput;
      if (typeof helper?.[method] !== 'function' || await helper[method](value) === false) throw new Error('input_unavailable');
    } catch { notice = 'Input could not be confirmed. Check the page before trying again.'; }
    finally { busy = false; publish(); }
  }
  function address(value) {
    if (typeof value !== 'string' || value.length > 2048) return null;
    const text = value.trim();
    try {
      const explicit = /^https?:\/\//i.test(text);
      const hostname = /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9-]+(?::\d+)?(?:[/?#].*)?$/i.test(text);
      if (explicit || hostname) {
        const url = new URL(explicit ? text : 'https://' + text);
        return ['http:','https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
      }
      if (!text || /^[a-z][a-z0-9+.-]*:/i.test(text) || text.startsWith('//')) return null;
      if (!searchEngine) return null;
      const url = new URL(searchEngine === 'duckduckgo' ? 'https://duckduckgo.com/' : 'https://www.google.com/search');
      url.searchParams.set('q',text); return url.href;
    } catch { return null; }
  }
  function present(message) {
    if (!['preview','full'].includes(message.mode)) return;
    presentation = message.mode;
    if (presentation === 'preview') hideInput();
    mount(); syncInput(); publish();
  }
  function hideInput() {
    try { frame?.contentWindow?.radhouseInput?.hide(); } catch { /* No live document. */ }
  }
  function zoom(message) {
    if (typeof message.enabled !== 'boolean') return;
    canvas.dataset.zoom = String(message.enabled);
    if (message.enabled) hideInput();
    mount(); publish();
  }
  function navigate(message) {
    const url = address(message.value);
    if (url) return input('navigate',url);
    else { notice = 'Enter a web address without login details, or a search.'; publish(); }
  }
  function humanCommand(message) {
    const {action} = message;
    if (action === 'visibility' && ['private','observe'].includes(message.mode)) return act('/chat/browser/control/visibility',{...binding(),mode:message.mode});
    if (action === 'return' && state.can_return === true) return act('/chat/browser/return',{...binding(),request_id:crypto.randomUUID()},true);
    if (action === 'keyboard') return input('show',true);
    if (action === 'hideKeyboard') return input('hide');
    if (action === 'key' && ['tab','enter','escape','backspace','back','reload'].includes(message.key)) return input('press',message.key);
    if (action === 'address') return navigate(message);
  }
  function controlCommand(message) {
    const {action} = message;
    if (action === 'zoom') return zoom(message);
    if (action === 'take' && (state.control.can_take || state.control.mode === 'human' && !human()))
      return act('/chat/browser/control/take',{...binding(),request_id:crypto.randomUUID(),...(state.control.mode === 'human' ? {move_here:true} : {})});
    if (action === 'close' && (human() || state.control.mode !== 'human')) return act('/chat/browser/control/close',binding());
    if (human()) return humanCommand(message);
  }
  const presentationActions = new Map([
    ['present',present],
    ['refresh',() => { if (!busy) return refresh(true); }],
    ['reconnect',() => { clearFrame(); mount(); publish(); }],
  ]);
  function command(message) {
    if (!message || typeof message !== 'object' || typeof message.action !== 'string') return;
    const handler = presentationActions.get(message.action);
    if (handler) return handler(message);
    if (presentation !== 'full' || !authenticated || busy || uncertain) return;
    if (message.action === 'open' && state?.state === 'idle') return act('/chat/browser/open',{});
    if (state?.control && state.state === 'live') return controlCommand(message);
  }
  window.RadhouseMobileBrowser = Object.freeze({command});
  window.addEventListener('message',event => {
    if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
    const value = event.data;
    if (value?.type === 'mobileInputStatus' && typeof value.ready === 'boolean') inputReady = value.ready;
    if (value?.type === 'framePresented') { playback = 'live'; clearTimeout(connectTimer); }
    if (value?.type === 'browserPlaybackStatus' && ['tap_required','unavailable'].includes(value.state)) playback = value.state;
    if (value?.type === 'browserActivity' && presentation === 'full' && human()) lastActivity = Date.now();
    publish();
  });
  async function tick() {
    await refresh();
    if (authenticated && presentation === 'full' && human() && !busy && !uncertain
        && !document.hidden && Date.now()-lastActivity < 120000 && Date.now()-lastHeartbeat > 15000) {
      lastHeartbeat = Date.now();
      const expected = epoch;
      try { const value = await request('/chat/browser/control/heartbeat',binding()); if (expected === epoch && !busy) accept(value); }
      catch { /* Presence never replays input or grants control. */ }
    }
    timer = setTimeout(tick,2000);
  }
  document.addEventListener('visibilitychange',() => { if (document.hidden) { epoch++; clearFrame(); publish(); } else void refresh(); });
  window.addEventListener('pagehide',() => { epoch++; clearTimeout(timer); clearFrame(); });
  (async () => {
    try {
      const session = await request('/auth/session');
      if (!/^[A-Za-z0-9_-]{40,200}$/.test(session.csrf_token || '') || session.features?.browser_streaming !== true) throw new Error('unsupported');
      csrf = session.csrf_token; authenticated = true;
      try {
        const preferences = await request('/chat/browser/preferences');
        if (['google','duckduckgo'].includes(preferences?.search_engine)) searchEngine = preferences.search_engine;
      } catch { /* Direct addresses still work; search waits for a known preference. */ }
      await tick();
    } catch { notice = 'The browser connection is unavailable.'; publish(); }
  })();
})();
