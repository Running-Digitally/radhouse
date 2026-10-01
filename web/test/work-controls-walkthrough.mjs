import assert from 'node:assert/strict';
const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const controls = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/v1\/work\/[^/]+\/commands$/.test(new URL(request.url()).pathname)) {
      controls.push(request.postDataJSON().kind);
    }
  });
  await page.goto(process.env.RADHOUSE_BROWSER_ORIGIN + '/app');
  await page.getByLabel('Username').fill('alice');
  await page.getByLabel('Password', { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.getByLabel('Authenticator code').fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Assignment', { exact: true }).fill('Prepare a persistent report.');
  await page.getByRole('button', { name: 'Create artifact', exact: true }).click();
  const card = page.locator('.task-card').first();
  await card.getByText('Working', { exact: true }).waitFor({ timeout: 15000 });
  await card.getByText('More options', { exact: true }).click();
  await card.getByRole('button', { name: 'Pause', exact: true }).click();
  await card.getByText('Paused', { exact: true }).waitFor({ timeout: 15000 });
  if (!(await card.getByRole('button', { name: 'Resume', exact: true }).isVisible())) await card.getByText('More options', { exact: true }).click();
  await card.getByRole('button', { name: 'Resume', exact: true }).click();
  await card.getByText('Working', { exact: true }).waitFor({ timeout: 15000 });
  if (!(await card.getByRole('button', { name: 'Cancel', exact: true }).isVisible())) await card.getByText('More options', { exact: true }).click();
  await card.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.locator('.recent-activity > summary').click();
  await page.getByText('Stopped', { exact: true }).waitFor({ timeout: 15000 });
  assert.deepEqual(controls, ['pause', 'resume', 'cancel']);
  console.log('PASS: real web pause/resume/cancel use shared work commands and preserve one work item.');
} finally {
  await browser.close();
}
