import assert from 'node:assert/strict';
const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const paths = [];
  page.on('request', request => paths.push(new URL(request.url()).pathname));
  await page.goto(`${process.env.RADHOUSE_BROWSER_ORIGIN}/app/#review=${process.env.RADHOUSE_TEST_REVIEW_TOKEN}`);
  await page.getByLabel('Username', { exact: true }).fill('alice');
  await page.getByLabel('Password', { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.getByLabel('Authenticator code', { exact: true }).fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.locator('.result-viewer__preview h1', { hasText: 'Report' }).waitFor();
  assert.equal(await page.locator('.task-card').count(), 1);
  assert.equal(await page.locator('.result-viewer__preview script').count(), 0);
  assert.equal(await page.evaluate(() => window.unsafe), undefined);
  assert(paths.some(path => /^\/v1\/work\/work-.*\/artifacts\//.test(path)));
  assert(!paths.some(path => /^\/tasks\/.*\/result$/.test(path)));
  await page.reload();
  await page.locator('.result-viewer__preview h1', { hasText: 'Report' }).waitFor();
  console.log('PASS: signed exact-artifact link survives sign-in/reload and renders sanitized bytes');
} finally { await browser.close(); }
