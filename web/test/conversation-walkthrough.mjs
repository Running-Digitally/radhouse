import assert from "node:assert/strict";

const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const page = await context.newPage();
try {
  await page.goto(`${process.env.RADHOUSE_BROWSER_ORIGIN}/app/`);
  await page.getByLabel("Username", { exact: true }).fill("alice");
  await page.getByLabel("Password", { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.getByLabel("Authenticator code", { exact: true }).fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const log = page.getByRole("log", { name: "Conversation with Researcher" });
  await log.getByText("Compare two morning routines.", { exact: true }).waitFor();
  await log.locator("article").filter({ hasText: "Compare two morning routines." }).getByRole("button", { name: "Reply", exact: true }).click();
  const brief = "Use no tools. Explain the previous result using this reference.";
  await page.getByLabel("Message Researcher", { exact: true }).fill(brief);
  await page.getByLabel("Reference files", { exact: false }).setInputFiles({ name: "routine.txt", mimeType: "text/plain", buffer: Buffer.from("A quiet walk before breakfast.") });
  await page.getByText("routine.txt", { exact: true }).waitFor();
  let interrupted = false;
  await page.route("**/conversations/*/messages", async route => {
    if (route.request().method() === "POST" && !interrupted) {
      const response = await route.fetch(); assert.equal(response.status(), 200);
      interrupted = true; await route.abort("connectionfailed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await page.getByText("The connection was interrupted.", { exact: false }).waitFor();
  assert.equal(await page.getByLabel("Message Researcher", { exact: true }).inputValue(), brief);
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await log.getByText(brief, { exact: true }).waitFor();
  await page.reload();
  await log.getByText(brief, { exact: true }).waitFor();
  assert.equal(await log.getByText(brief, { exact: true }).count(), 1);
  await log.getByText("routine.txt", { exact: true }).click();
  await log.getByText("A quiet walk before breakfast.", { exact: true }).waitFor();
  assert.equal(await page.locator("[data-task-id]").count(), 2);
  await page.screenshot({ path: process.env.RADHOUSE_SCREENSHOT, fullPage: true });
  console.log("Conversation walkthrough passed: signed Buzz message → shared web history → contextual reply with file → lost acknowledgment retry → reconnect.");
} catch (error) {
  await page.screenshot({ path: process.env.RADHOUSE_SCREENSHOT, fullPage: true });
  console.log((await page.locator("body").innerText()).slice(0, 5000));
  console.log("SCREENSHOT", process.env.RADHOUSE_SCREENSHOT);
  throw error;
} finally {
  await browser.close();
}
