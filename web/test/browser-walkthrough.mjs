import assert from "node:assert/strict";

const { chromium } = await import(process.env.RADHOUSE_PLAYWRIGHT_MODULE);
const browser = await chromium.launch({ headless: true,
  ...(process.env.RADHOUSE_BROWSER_CHANNEL ? { channel: process.env.RADHOUSE_BROWSER_CHANNEL } : {}) });
const origin = process.env.RADHOUSE_BROWSER_ORIGIN;
const context = await browser.newContext();
const web = await context.newPage();
try {
  await web.goto(`${origin}/app/`);
  await web.getByLabel("Username", { exact: true }).fill("alice");
  await web.getByLabel("Password", { exact: true }).fill(process.env.RADHOUSE_TEST_PASSWORD);
  await web.getByLabel("Authenticator code", { exact: true }).fill(process.env.RADHOUSE_TEST_TOTP);
  await web.getByRole("button", { name: "Sign in", exact: true }).click();
  await web.getByLabel("Assignment", { exact: true }).fill("Read these figures and give a short report");
  // A real file chooser can remain open beyond the ten-second refresh. Keep
  // its original input connected so macOS/WebKit can deliver the selection.
  const fileInput = web.getByLabel("Reference files", { exact: false });
  const originalInput = await fileInput.elementHandle();
  const [chooser] = await Promise.all([web.waitForEvent("filechooser"), fileInput.click()]);
  await new Promise((resolve) => setTimeout(resolve, 11_000));
  assert.equal(await originalInput.evaluate((input) => input.isConnected), true,
    "Background refresh detached the active file chooser input");
  await chooser.setFiles({ name: "figures.txt", mimeType: "text/plain", buffer: Buffer.from("Revenue 42\nCosts 12") });
  await web.getByText("figures.txt", { exact: true }).waitFor();
  await new Promise((resolve) => setTimeout(resolve, 11_000));
  assert.equal(await originalInput.evaluate((input) => input.isConnected), false,
    "Background refresh did not resume after the file selection");
  await web.getByText("figures.txt", { exact: true }).waitFor();
  await web.getByRole("button", { name: "Send assignment" }).click();
  await web.getByRole("button", { name: "Review result", exact: true }).waitFor({ timeout: 20000 });
  const taskId = await web.locator("[data-task-id]").getAttribute("data-task-id");
  assert.ok(taskId);

  // Protected review stays in a second ordinary web tab.
  const review = await context.newPage();
  await review.goto(`${origin}/app/`);
  await review.locator(`[data-task-id="${taskId}"]`).waitFor();
  await review.getByRole("button", { name: "Review result", exact: true }).click();
  await review.getByRole("button", { name: "Review selected audience" }).click();
  await review.getByText("Artifact SHA-256:", { exact: false }).waitFor();
  await review.getByRole("button", { name: "Approve and publish", exact: true }).click();
  await review.getByText("Published to alice.", { exact: true }).waitFor();
  await web.reload();
  await web.getByText("Published to alice.", { exact: true }).waitFor();
  await web.getByRole("button", { name: "Start a follow-up", exact: true }).click();
  await web.getByText("The previous result is included as reference material.", { exact: true }).waitFor();
  await web.getByLabel("Assignment", { exact: true }).fill("Explain the previous report in three sentences");
  await web.getByRole("button", { name: "Send assignment" }).click();
  await web.locator("[data-task-id]").nth(1).waitFor();
  await web.screenshot({ path: process.env.RADHOUSE_SCREENSHOT, fullPage: true });
  console.log("Browser walkthrough passed: selected input → task → web review → publication → web reconnect → follow-up.");
} finally {
  await browser.close();
}
