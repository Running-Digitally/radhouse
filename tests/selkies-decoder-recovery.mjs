// Execute the actual patched, digest-qualified upstream watchdog and fallback.
// No browser, credentials, network, real clocks or private data are involved.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(process.env.RADHOUSE_SELKIES_CORE_SOURCE, 'utf8');
function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `missing upstream function ${name}`);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
const functions = ['checkVideoOutputWatchdog', 'initiateFallback'].map(functionSource).join('\n');
function fixture() {
  const events = [];
  const context = vm.createContext({
    console: {log() {}, warn() {}, error() {}},
    now: 10000, performance: {now: () => context.now},
    document: {hidden: false}, window: {isFallingBack: false, location: {origin: 'https://fixture.invalid', reload: () => events.push('reload')}, parent: {postMessage: value => events.push(value.state)}},
    isSharedMode: true, sharedVideoPaused: false, isVideoPipelineActive: true,
    softwareDecodeAttempted: false, softwareDecodeSwitchedAt: 0, softwareDecodeSince: 0,
    preferSoftwareDecode: false, codecRefusalUnanswerable: false,
    currentEncoderMode: 'h264enc', VideoDecoder: class {},
    SOFTWARE_DECODE_SETTLE_MS: 3000, NO_OUTPUT_WATCHDOG_MS: 4000, DECODER_PROBE_TIMEOUT_MS: 10000,
    firstConfigAskedAt: 0, vncStripeDecoders: {}, lastVideoChunkAt: 10000, lastVideoOutputAt: 0, noOutputStalledSince: 0,
    rememberSoftwareDecode: value => { context.preferSoftwareDecode = value; events.push(value ? 'software' : 'automatic'); },
    restartDecodersForAcceleration: () => events.push('reset-decoder'),
    codecOfEncoder: () => 'h264', WebSocket: {OPEN: 1}, websocket: {readyState: 1, close: () => events.push('close')},
    metricsIntervalId: 1, clearInterval: () => events.push('clear-metrics'),
    clearSharedStallWatchdog: () => events.push('clear-stream-watchdog'),
    stopReconnecting: () => events.push('stop-reconnect'),
    clearAllVncStripeDecoders: () => events.push('close-decoders'),
    statusDisplayElement: {textContent: '', classList: {remove() {}}},
    setTimeout: () => events.push('scheduled-reload'),
  });
  vm.runInContext(functions, context);
  return {context, events, tick(time, output = false) {
    context.now = context.lastVideoChunkAt = time;
    if (output) context.lastVideoOutputAt = time;
    vm.runInContext('checkVideoOutputWatchdog()', context);
  }};
}

// A silent decoder retries once with software, once with the engine's choice,
// then stops visibly. Later chunks cannot restart a terminal failure.
const stalled = fixture();
for (const time of [10000, 14000, 18000, 22000, 26000, 30000, 34000, 38000]) stalled.tick(time);
assert.equal(stalled.events.filter(value => value === 'reset-decoder').length, 2);
assert.equal(stalled.events.filter(value => value === 'unavailable').length, 1);
assert.equal(stalled.context.window.isFallingBack, true);
assert.ok(stalled.events.includes('close-decoders'));
assert.ok(!stalled.events.includes('reload'));
assert.ok(!stalled.events.includes('scheduled-reload'));

// A recovered decoder keeps playing rather than progressing to terminal state.
const recovered = fixture();
recovered.tick(10000); recovered.tick(14000);
for (const time of [18000, 22000, 30000]) recovered.tick(time, true);
assert.equal(recovered.events.filter(value => value === 'reset-decoder').length, 1);
assert.ok(!recovered.events.includes('unavailable'));

// Hidden, paused, quiet, unsupported and still-configuring streams must not
// be mistaken for a fed decoder that silently stopped producing frames.
for (const mode of ['hidden', 'paused', 'quiet', 'unsupported', 'configuring']) {
  const f = fixture();
  if (mode === 'hidden') f.context.document.hidden = true;
  if (mode === 'paused') f.context.sharedVideoPaused = true;
  if (mode === 'unsupported') f.context.codecRefusalUnanswerable = true;
  if (mode === 'configuring') { f.context.firstConfigAskedAt = 9000; f.context.vncStripeDecoders = {0: {decoder: {state: 'unconfigured'}}}; }
  if (mode === 'quiet') { f.context.lastVideoChunkAt = 0; vm.runInContext('checkVideoOutputWatchdog()', f.context); }
  else { f.tick(10000); f.tick(14000); }
  assert.deepEqual(f.events, [], mode);
}
console.log(JSON.stringify({passed: 7, actual_pinned_functions: true, bounded_viewer_recovery: true}));
