import assert from "node:assert/strict";
const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
const origin = process.env.RADHOUSE_BROWSER_ORIGIN;
const page = await browser.newPage();
try {
  await page.goto(`${origin}/app/#review=${process.env.RADHOUSE_TEST_LOCATOR}`);
  assert.equal(await page.locator('[data-task-id]').count(), 0);
  await page.getByLabel('Username', { exact: true }).fill('alice');
  await page.getByLabel('Password', { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.getByLabel('Authenticator code', { exact: true }).fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('heading', { name: 'Review your work', exact: true }).waitFor();
  assert.equal(await page.locator('[data-task-id]').count(), 1);
  assert.equal(await page.locator('[data-task-id]').getAttribute('data-task-id'), process.env.RADHOUSE_TEST_TASK);
  assert.equal(await page.locator('.conversation-compose').count(), 0);
  await page.evaluate(async () => fetch('/_fixture/assurance-expires', { method: 'POST' }));
  await page.reload();
  await page.getByRole('heading', { name: 'Review your work', exact: true }).waitFor();
  assert.equal(await page.locator('[data-task-id]').getAttribute('data-task-id'), process.env.RADHOUSE_TEST_TASK);
  await page.getByRole('button', { name: 'Review result', exact: true }).click();
  await page.getByRole('button', { name: 'Review selected audience', exact: true }).click();
  await page.getByRole('button', { name: 'Approve and publish', exact: true }).click();
  await page.getByText('Published to alice.', { exact: true }).waitFor();
  await page.reload();
  await page.getByText('Published to alice.', { exact: true }).waitFor();
  await page.evaluate(() => { location.hash = 'review=tampered'; });
  await page.getByText('This review link is expired or no longer available to your account.', { exact: false }).waitFor();
  assert.equal(await page.locator('[data-task-id]').count(), 0);
  await page.getByRole('button', { name: 'Open work home', exact: true }).click();
  await page.getByRole('heading', { name: "Alice's work", exact: true }).waitFor();
  assert.equal(new URL(page.url()).hash, '');
  console.log('Review locator: MFA login, exact target, remembered session, publication, reconnect, tamper denial passed.');
} finally { await browser.close(); }
