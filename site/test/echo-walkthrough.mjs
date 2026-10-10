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
    // Repeatable shuffle with real, continuous video playback.
    Math.random = () => .25;
    document.addEventListener('DOMContentLoaded', () => {
      window.echoTransitions = [];
      window.echoEndings = [];
      const host = document.querySelector('[data-echo-avatar]');
      host.addEventListener('ended', event => {
        window.echoEndings.push({ clip: event.target.dataset.clip, time: performance.now() });
      }, true);
      new MutationObserver(records => {
        if (!records.some(record => record.attributeName === 'data-echo-phase')) return;
        window.echoTransitions.push({ phase: host.dataset.echoPhase, clip: host.dataset.echoClip,
          time: performance.now(), activeCount: host.querySelectorAll('video.is-active').length });
      }).observe(host, { attributes: true });
    });
  });
  await page.goto(`${origin}/#characters`);
  assert.equal(await page.locator('.visual-theme').count(), 3);
  assert.equal(await page.locator('#collection-paper').count(), 0);
  await page.waitForFunction(() => window.echoTransitions?.filter(item => item.phase === 'playing').length >= 4,
    null, { timeout: 30000 });
  const transitions = await page.evaluate(() => window.echoTransitions);
  const endings = await page.evaluate(() => window.echoEndings);
  const playing = transitions.filter(item => item.phase === 'playing');
  assert.equal(new Set(playing.slice(0, 3).map(item => item.clip)).size, 3, 'Each shuffled group must contain A/B/C');
  const handoffs = [];
  for (let i = 1; i < playing.length; i++) {
    assert.notEqual(playing[i].clip, playing[i - 1].clip);
    const ending = endings.findLast(item => item.time < playing[i].time);
    assert.ok(ending);
    const elapsed = playing[i].time - ending.time;
    assert.ok(elapsed < 250, `Reaction handoff took ${elapsed} ms`);
    handoffs.push(elapsed);
  }
  assert.ok(playing.every(item => item.activeCount === 1));
  assert.ok(transitions.filter(item => item.time >= playing[0].time).every(item =>
    ['starting', 'playing'].includes(item.phase) && item.activeCount === 1), 'Handoffs must retain the outgoing frame');
  assert.ok(await page.locator('[data-echo-avatar] video').evaluateAll(videos => videos.every(video =>
    video.muted && video.playsInline && !video.loop && video.readyState >= 2)));
  assert.equal(await page.locator('.signal-companion').count(), 2);
  assert.equal(await page.locator('.signal-companion video').count(), 0);
  assert.ok(await page.locator('.signal-portraits').evaluate(row => {
    const left = row.children[0].getBoundingClientRect();
    const echo = row.children[1].getBoundingClientRect();
    const right = row.children[2].getBoundingClientRect();
    return left.right < echo.left && echo.right < right.left && echo.width > left.width * 2;
  }));
  await page.screenshot({ path: `${output}/echo-card-desktop.png` });
  await page.locator('.workspace-cards').screenshot({ path: `${output}/workspace-cards.png` });

  await page.getByRole('button', { name: 'Pause Echo', exact: true }).click();
  assert.equal(await page.locator('[data-echo-avatar]').getAttribute('data-echo-phase'), 'neutral');
  await page.getByRole('button', { name: 'Play Echo', exact: true }).click();
  await page.getByRole('link', { name: 'Explore Signal Station characters', exact: true }).click();
  assert.equal(await page.locator('[data-echo-avatar]').getAttribute('data-echo-phase'), 'neutral');
  await page.getByRole('button', { name: 'Preview Echo', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.gallery-portrait-frame').dataset.echoPhase === 'playing');
  assert.equal(await page.locator('#gallery-character-name').innerText(), 'Echo', 'The centerpiece must open directly to Echo');
  assert.equal(await page.locator('.gallery-thumbnail video').count(), 0);
  assert.equal(await page.locator('.gallery-themes button').count(), 3);
  await page.screenshot({ path: `${output}/echo-gallery-desktop.png` });
  assert.equal(await page.locator('#gallery-portrait').getAttribute('src'), '/characters/echo-neutral.png');
  await page.getByRole('button', { name: 'Next character', exact: true }).click();
  assert.equal(await page.locator('.gallery-portrait-frame video').count(), 0, 'Leaving Echo must destroy its player');
  assert.equal(await page.locator('#gallery-character-name').innerText(), 'Orbit');
  await page.locator('#gallery-close').press('Escape');
  await page.waitForFunction(() => document.querySelectorAll('#character-gallery video').length === 0);
  assert.equal(await page.locator('#character-gallery video').count(), 0, 'Closing must release all gallery players');
  assert.equal(await page.getByRole('link', { name: 'Explore Signal Station characters', exact: true }).evaluate(link => link === document.activeElement), true);

  for (const width of [320, 390, 700, 1000, 1001, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator('#characters').scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.ok(await page.locator('.signal-portraits').evaluate(row => row.scrollWidth <= row.clientWidth));
    if (width > 1000) {
      assert.ok(await page.locator('.workspace-card').evaluateAll(cards => {
        const bounds = cards.map(card => card.getBoundingClientRect());
        const headings = cards.map(card => card.querySelector('h3').getBoundingClientRect());
        const labels = cards.map(card => card.querySelector('.workspace-number').getBoundingClientRect());
        return bounds.every(rect => Math.abs(rect.top - bounds[0].top) < 1 && Math.abs(rect.bottom - bounds[0].bottom) < 1)
          && headings.every(rect => Math.abs(rect.top - headings[0].top) < 1)
          && labels.every(rect => Math.abs(rect.top - labels[0].top) < 1);
      }), 'All four cards must align their edges, category labels and headings');
    }
    if (width === 390) {
      await page.locator('#characters-title').click();
      await page.screenshot({ path: `${output}/echo-card-mobile.png` });
      await page.locator('#characters').screenshot({ path: `${output}/echo-card-detail.png` });
    }
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
    host.dataset.echoPhase === 'neutral' && [...host.querySelectorAll('video')].every(video => video.paused && !video.classList.contains('is-active')))));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.waitForFunction(() => document.querySelector('.gallery-portrait-frame').dataset.echoPhase === 'playing');
  await page.locator('#gallery-close').press('Escape');
  await page.locator('#top').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'neutral');
  assert.deepEqual(errors, []);

  const unavailable = await context.newPage();
  await unavailable.route('**/characters/echo-*.webm', route => route.abort());
  await unavailable.route('**/characters/echo-*.mp4', route => route.abort());
  await unavailable.goto(`${origin}/#characters`);
  await unavailable.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'unavailable');
  assert.equal(await unavailable.locator('[data-echo-avatar] video.is-active').count(), 0);
  assert.ok(await unavailable.locator('[data-echo-avatar] img').evaluate(image => image.complete && image.naturalWidth > 0));
  await unavailable.close();

  const denied = await context.newPage();
  await denied.addInitScript(() => { HTMLMediaElement.prototype.play = () => Promise.reject(new Error('Autoplay denied')); });
  await denied.goto(`${origin}/#characters`);
  await denied.waitForFunction(() => document.querySelector('[data-echo-avatar]').dataset.echoPhase === 'unavailable');
  assert.equal(await denied.locator('[data-echo-avatar] video.is-active').count(), 0);
  await denied.close();

  const staticContext = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await staticContext.newPage();
  await staticPage.goto(origin);
  await staticPage.locator('#collection-signal summary').click();
  assert.ok(await staticPage.locator('#collection-signal img[alt="Echo"]').evaluate(image => image.complete && image.naturalWidth === 256));
  await staticContext.close();
  console.log(JSON.stringify({ passed: true, clips: playing.map(item => item.clip),
    handoffMilliseconds: handoffs,
    checks: ['real continuous playback', 'retained handoff frames', 'shuffle', 'static companions', 'pause/resume', 'gallery cleanup', 'focus return',
      'responsive layouts', 'reduced motion', 'offscreen suspension', 'failed media',
      'autoplay rejection', 'no JavaScript'], errors, output }));
} finally {
  await context.close();
  await browser.close();
}
