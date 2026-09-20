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
  const task = web.locator(`[data-task-id="${taskId}"]`);
  await task.getByRole("heading", { name: "Useful financial report", exact: true }).waitFor();
  assert.equal(await task.locator("script").count(), 0);
  await task.getByRole("button", { name: "View result", exact: true }).click();
  await task.locator(".result-viewer__preview h1", { hasText: "Useful financial report" }).waitFor();
  assert.equal(await task.locator('.result-viewer__preview script').count(), 0);
  assert.equal(await task.locator('.result-viewer__preview a[href^="javascript:"]').count(), 0);
  assert.equal(await task.locator('.result-viewer__preview img').count(), 0);
  await task.getByRole("tab", { name: "Preview", exact: true }).press("ArrowRight");
  assert.equal(await task.getByRole("tab", { name: "Source", exact: true }).getAttribute("aria-selected"), "true");
  await task.locator('.result-viewer__source').getByText("<script>window.radhouseUnsafe = true</script>", { exact: false }).waitFor();
  await task.getByRole("button", { name: "Edit title", exact: true }).click();
  await task.getByLabel("Task title", { exact: true }).fill("September planning figures");
  await task.getByRole("button", { name: "Save title", exact: true }).click();
  await task.getByRole("heading", { name: "September planning figures", exact: true }).waitFor();
  await task.getByRole("button", { name: "Send to Beacon for review", exact: true }).click();
  await web.getByText("Beacon received the exact completed result and has started the next assignment.", { exact: true }).waitFor();
  await web.locator("[data-task-id]").nth(1).waitFor();

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
  await task.getByRole("button", { name: "Start a follow-up", exact: true }).click();
  await web.getByText("The previous result is included as reference material.", { exact: true }).waitFor();
  await web.getByLabel("Assignment", { exact: true }).fill("Explain the previous report in three sentences");
  await web.getByRole("button", { name: "Send assignment" }).click();
  await web.locator("[data-task-id]").nth(2).waitFor();
  await web.screenshot({ path: process.env.RADHOUSE_SCREENSHOT, fullPage: true });
  console.log("Browser walkthrough passed: selected input → task → one-click handoff → web review → publication → web reconnect → follow-up.");
} finally {
  await browser.close();
}
