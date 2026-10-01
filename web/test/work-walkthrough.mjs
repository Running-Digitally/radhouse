import assert from "node:assert/strict";
const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
try {
  const page = await browser.newPage();
  await page.goto(`${process.env.RADHOUSE_BROWSER_ORIGIN}/app/`);
  await page.getByLabel("Username", { exact: true }).fill("alice");
  await page.getByLabel("Password", { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.getByLabel("Authenticator code", { exact: true }).fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Assignment", { exact: true }).fill("Create a useful report");
  await page.getByRole("button", { name: "Create artifact", exact: true }).click();
  await page.locator(".recent-activity > summary").waitFor();
  await page.locator(".recent-activity > summary").click();
  await page.getByRole("button", { name: "Open artifact", exact: true }).click();
  await page.locator(".result-viewer__preview h1", { hasText: "Useful report" }).waitFor();
  assert.equal(await page.locator(".result-viewer__preview script").count(),0);
  assert.equal(await page.evaluate(() => window.unsafe),undefined);
  await page.getByLabel("Assignment", { exact: true }).fill("Create a report with a blocked dependency");
  await page.getByRole("button", { name: "Create artifact", exact: true }).click();
  await page.getByText("A dependency prevented completion.", { exact: true }).waitFor();
  const blocked = page.locator(".task-card").filter({hasText:"A dependency prevented completion."});
  assert.equal(await blocked.locator(".phase").textContent(),"Waiting");
  assert.equal(await blocked.isVisible(),true,"Unfinished work must stay in the visible current group");
  await page.getByText("1 assignment is waiting. Your work is retained; there is no decision for you right now.", {exact:true}).waitFor();
  await page.reload();
  await page.getByText("A dependency prevented completion.", { exact: true }).waitFor();
  assert.equal(await page.locator(".task-card").filter({hasText:"A dependency prevented completion."}).isVisible(),true);
  if (process.env.RADHOUSE_SCREENSHOT) await page.screenshot({ path: process.env.RADHOUSE_SCREENSHOT, fullPage: true });
  console.log("PASS: two outcomes, safe artifact, unfinished terminal run stays visible after reload, truthful attention summary");
} finally { await browser.close(); }
