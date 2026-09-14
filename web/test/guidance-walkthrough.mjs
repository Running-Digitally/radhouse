import assert from "node:assert/strict";
const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
const context = await browser.newContext();
const page = await context.newPage();
const origin = process.env.RADHOUSE_BROWSER_ORIGIN;
try {
  await page.clock.install();
  await page.goto(`${origin}/app/`);
  await page.getByLabel("Username", { exact: true }).fill("alice");
  await page.getByLabel("Password", { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.getByLabel("Authenticator code", { exact: true }).fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const guidance = page.getByLabel("Guide the current assignment", { exact: true });
  await guidance.focus();
  const original = await guidance.elementHandle();
  await page.clock.fastForward(11_000);
  assert.equal(await original.evaluate(node => node.isConnected && node === document.activeElement), true,
    "Polling detached the empty focused guidance control");
  await guidance.fill("  Emphasize cost.\n");
  await page.getByRole("button", { name: "Show progress", exact: true }).click();
  assert.equal(await guidance.inputValue(), "  Emphasize cost.\n", "Explicit refresh lost the guidance draft");
  await page.getByRole("button", { name: "Send guidance", exact: true }).click();
  await page.getByText("Queued for this run’s next tool checkpoint.", { exact: false }).waitFor();
  assert.equal(await page.getByText("Used in a completed model response.", { exact: false }).count(), 0);
  await page.reload();
  await page.getByText("Queued for this run’s next tool checkpoint.", { exact: false }).waitFor();
  await page.request.post(`${origin}/_fixture/finish-guided-response`);
  await page.reload();
  await page.getByText("Used in a completed model response. Review the result", { exact: false }).waitFor();
  await page.getByText("The synthetic result follows the cost emphasis.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Send guidance", exact: true }).count(), 0);
  await page.reload();
  await page.getByText("Used in a completed model response. Review the result", { exact: false }).waitFor();
  assert.equal(await page.getByText("Used in a completed model response. Review the result", { exact: false }).count(), 1);
  console.log("PASS: focused empty input, draft retention, queued/applied distinction, reconnect, no publication");
} finally { await context.close(); await browser.close(); }
