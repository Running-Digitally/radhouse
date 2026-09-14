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
  await web.getByLabel("Reference files", { exact: false }).setInputFiles({ name: "figures.txt", mimeType: "text/plain", buffer: Buffer.from("Revenue 42\nCosts 12") });
  await web.getByRole("button", { name: "Send assignment" }).click();
  await web.getByRole("button", { name: "Review result", exact: true }).waitFor({ timeout: 20000 });
  const taskId = await web.locator("[data-task-id]").getAttribute("data-task-id");
  assert.ok(taskId);

  // Mount the actual shared native panel surface. The test-owned bridge signs
  // real NIP-98 requests while preserving browser cookie/Origin/CSRF checks.
  const native = await context.newPage();
  await native.goto(`${origin}/_fixture/native`);
  await native.evaluate(async () => {
    const { mountWorkHome } = await import("/app/dist/app.js");
    const { operatorClient } = await import("/app/dist/api.js");
    const host = document.createElement("section");
    document.body.replaceChildren(host);
    const shadow = host.attachShadow({ mode: "open" });
    const page = document.createElement("main");
    const style = document.createElement("style");
    style.textContent = (await (await fetch("/app/styles.css")).text()).replace(":root", ":host");
    shadow.append(style, page);
    const transport = async (path, init = {}) => {
      const signed = await (await fetch("/_fixture/sign", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, method: init.method ?? "GET", body: init.body ?? "" }) })).json();
      return fetch(`/buzz${path}`, { ...init, headers: { ...Object.fromEntries(new Headers(init.headers)), ...signed } });
    };
    window.disposeNative = mountWorkHome(page, operatorClient(transport, "buzz"));
  });
  await native.locator(`[data-task-id="${taskId}"]`).waitFor();
  await native.getByRole("button", { name: "Review result", exact: true }).click();
  await native.getByRole("button", { name: "Review selected audience" }).click();
  await native.getByText("Artifact SHA-256:", { exact: false }).waitFor();
  await native.getByRole("button", { name: "Approve and publish", exact: true }).click();
  await native.getByText("Published to alice.", { exact: true }).waitFor();
  await web.reload();
  await web.getByText("Published to alice.", { exact: true }).waitFor();
  await web.getByRole("button", { name: "Start a follow-up", exact: true }).click();
  await web.getByText("The previous result is included as reference material.", { exact: true }).waitFor();
  await web.getByLabel("Assignment", { exact: true }).fill("Explain the previous report in three sentences");
  await web.getByRole("button", { name: "Send assignment" }).click();
  await web.locator("[data-task-id]").nth(1).waitFor();
  await web.screenshot({ path: process.env.RADHOUSE_SCREENSHOT, fullPage: true });
  await native.evaluate(() => window.disposeNative());
  console.log("Browser walkthrough passed: selected input → task → native review → publication → web reconnect → follow-up.");
} finally {
  await browser.close();
}
