import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const origin = process.env.RADHOUSE_BROWSER_ORIGIN || 'http://127.0.0.1:8934';
const output = process.env.RADHOUSE_ECHO_OUTPUT || '/tmp/radhouse-echo-checks';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));

try {
  await page.addInitScript(() => {
    // Repeatable shuffle and a three-second rest, with real video playback.
    Math.random = () => .25;
    document.addEventListener('DOMContentLoaded', () => {
      window.echoTransitions = [];
      const host = document.querySelector('[data-echo-avatar]');
      new MutationObserver(records => {
        if (!records.some(record => record.attributeName === 'data-echo-phase')) return;
        window.echoTransitions.push({ phase: host.dataset.echoPhase, clip: host.dataset.echoClip,
          wait: Number(host.dataset.echoWait), time: performance.now(),
          hidden: host.querySelector('video').hidden });
      }).observe(host, { attributes: true });
    });
  });
  await page.goto(`${origin}/#characters`);
  await page.waitForFunction(() => window.echoTransitions?.filter(item => item.phase === 'playing').length >= 3,
    null, { timeout: 45000 });
  await page.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'waiting');
  const transitions = await page.evaluate(() => window.echoTransitions);
  const playing = transitions.filter(item => item.phase === 'playing');
  assert.equal(new Set(playing.slice(0, 3).map(item => item.clip)).size, 3, 'Each shuffled group must contain A/B/C');
  for (let i = 1; i < playing.length; i++) assert.notEqual(playing[i].clip, playing[i - 1].clip);
  for (const item of playing) {
    const rest = transitions.findLast(entry => entry.phase === 'waiting' && entry.time < item.time);
    assert.ok(rest && rest.hidden, 'Neutral photograph must be visible during the rest');
    assert.ok(rest.wait >= 2000 && rest.wait <= 6000);
    assert.ok(item.time - rest.time >= rest.wait - 150, 'Playback must wait for the entire neutral rest');
    assert.equal(item.hidden, false);
  }
  assert.deepEqual(await page.locator('[data-echo-avatar] video').evaluate(video => ({
    muted: video.muted, inline: video.playsInline, loop: video.loop, hidden: video.hidden
  })), { muted: true, inline: true, loop: false, hidden: true });
  await page.screenshot({ path: `${output}/echo-card-desktop.png` });

  await page.getByRole('button', { name: 'Pause Echo', exact: true }).click();
  assert.equal(await page.locator('[data-echo-avatar]').getAttribute('data-echo-phase'), 'neutral');
  await page.getByRole('button', { name: 'Play Echo', exact: true }).click();
  await page.getByRole('link', { name: 'Explore Signal Station characters', exact: true }).click();
  assert.equal(await page.locator('[data-echo-avatar]').getAttribute('data-echo-phase'), 'neutral');
  await page.getByRole('button', { name: 'Preview Echo', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.gallery-portrait-frame').dataset.echoPhase === 'playing');
  await page.screenshot({ path: `${output}/echo-gallery-desktop.png` });
  assert.equal(await page.locator('#gallery-portrait').getAttribute('src'), '/characters/echo-neutral.png');
  await page.getByRole('button', { name: 'Next character', exact: true }).click();
  assert.equal(await page.locator('.gallery-portrait-frame video').count(), 0, 'Leaving Echo must destroy its player');
  assert.equal(await page.locator('#gallery-character-name').innerText(), 'Orbit');
  await page.locator('#gallery-close').press('Escape');
  await page.waitForFunction(() => document.querySelectorAll('#character-gallery video').length === 0);
  assert.equal(await page.locator('#character-gallery video').count(), 0, 'Closing must release all gallery players');
  assert.equal(await page.getByRole('link', { name: 'Explore Signal Station characters', exact: true }).evaluate(link => link === document.activeElement), true);

  for (const width of [320, 390, 700, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole('link', { name: 'Explore Signal Station characters', exact: true }).click();
    await page.getByRole('button', { name: 'Preview Echo', exact: true }).click();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.ok(await page.locator('#character-gallery').evaluate(dialog => dialog.scrollWidth <= dialog.clientWidth));
    if (width === 390) await page.screenshot({ path: `${output}/echo-gallery-mobile.png` });
    await page.locator('#gallery-close').press('Escape');
  }

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('link', { name: 'Explore Signal Station characters', exact: true }).click();
  await page.getByRole('button', { name: 'Preview Echo', exact: true }).click();
  assert.ok(await page.locator('.echo-avatar').evaluateAll(hosts => hosts.every(host =>
    host.dataset.echoPhase === 'neutral' && host.querySelector('video').paused && host.querySelector('video').hidden)));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.waitForFunction(() => document.querySelector('.gallery-portrait-frame').dataset.echoPhase === 'waiting');
  await page.locator('#gallery-close').press('Escape');
  await page.locator('#top').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'neutral');
  assert.deepEqual(errors, []);

  for (const random of [0, .999999]) {
    const boundary = await context.newPage();
    await boundary.addInitScript(value => { Math.random = () => value; }, random);
    await boundary.goto(`${origin}/#characters`);
    await boundary.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'waiting');
    const wait = Number(await boundary.locator('[data-echo-avatar]').getAttribute('data-echo-wait'));
    assert.ok(Math.abs(wait - (2000 + random * 4000)) < .01);
    await boundary.close();
  }

  const unavailable = await context.newPage();
  await unavailable.route('**/characters/echo-*.webm', route => route.abort());
  await unavailable.route('**/characters/echo-*.mp4', route => route.abort());
  await unavailable.goto(`${origin}/#characters`);
  await unavailable.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'unavailable');
  assert.equal(await unavailable.locator('[data-echo-avatar] video').evaluate(video => video.hidden), true);
  assert.ok(await unavailable.locator('[data-echo-avatar] img').evaluate(image => image.complete && image.naturalWidth > 0));
  await unavailable.close();

  const denied = await context.newPage();
  await denied.addInitScript(() => { HTMLMediaElement.prototype.play = () => Promise.reject(new Error('Autoplay denied')); });
  await denied.goto(`${origin}/#characters`);
  await denied.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'unavailable');
  assert.equal(await denied.locator('[data-echo-avatar] video').evaluate(video => video.hidden), true);
  await denied.close();

  const staticContext = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await staticContext.newPage();
  await staticPage.goto(origin);
  await staticPage.locator('#collection-signal summary').click();
  assert.ok(await staticPage.locator('#collection-signal img[alt="Echo"]').evaluate(image => image.complete && image.naturalWidth === 256));
  await staticContext.close();
  console.log(JSON.stringify({ passed: true, clips: playing.map(item => item.clip),
    restMilliseconds: transitions.filter(item => item.phase === 'waiting').map(item => item.wait),
    checks: ['real playback', 'neutral rests', 'shuffle', 'pause/resume', 'gallery cleanup', 'focus return',
      'responsive layouts', 'reduced motion', 'offscreen suspension', 'wait boundaries', 'failed media',
      'autoplay rejection', 'no JavaScript'], errors, output }));
} finally {
  await context.close();
  await browser.close();
}
