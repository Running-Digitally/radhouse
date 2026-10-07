// Real browser checks with explicit synthetic HTTP fixtures; no deployed claims.
import {readFile, mkdir} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl = process.env.RADHOUSE_PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs", import.meta.url).href;
const {chromium, expect: baseExpect} = await import(moduleUrl);
const expect = baseExpect.configure({timeout: 10000});
const staticRoot = new URL("../src/radhouse/chat/static/", import.meta.url);
const artifacts = process.env.RADHOUSE_ADMIN_SCREENSHOTS;
const origin = "http://127.0.0.1:61381";
let role = "admin", active = true, probeRequests = 0, settingsRequests = 0, logoutCsrf;
let holdInfrastructure = false, finishInfrastructure;
let historyFailure = true;
const settings = {checked_at: "2026-10-07T18:30:00Z", permissions: {read: true, write: false},
  authentication: {methods: ["password", "totp"], idle_timeout_seconds: 1800, maximum_session_seconds: 43200, remembered_session_seconds: 2592000},
  messages: {character_limit: 16000}, files: {upload_size_limit_bytes: null, upload_count_limit: null,
    document_formats: ["text", "pdf", "docx", "xlsx", "pptx"], audio_transcription_enabled: false},
  documents: {selective_access_enabled: false}};
const infrastructure = {checked_at: "2026-10-07T18:30:00Z", versions: {release_commit: null, package: "0.0.1", python: "3.14.4"},
  components: [{id: "web", state: "healthy", detail: "Management access checked."},
    {id: "assistant", state: "unavailable", detail: "Assistant connection could not be checked."},
    {id: "documents", state: "unverified", detail: "<script>window.adminInjected=true</script>", version: "6.19.0"},
    {id: "storage", state: "healthy", detail: "Conversation and original files are readable.", schema_version: 3, database_bytes: 32768, free_bytes: 53687091200}]};
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1200, height: 950}});
const page = await context.newPage(), errors = [];
page.on("pageerror", error => errors.push(error.message));
await context.route(`${origin}/**`, async route => {
  const path = new URL(route.request().url()).pathname;
  const json = value => ({status: 200, contentType: "application/json", body: JSON.stringify(value)});
  if (path === "/auth/session") {
    await route.fulfill(active ? json({username: "alice", csrf_token: "synthetic-csrf", management: {read: ["admin", "operator"].includes(role), write: false}})
      : {status: 401, contentType: "application/json", body: JSON.stringify({error: "authentication_required"})}); return;
  }
  if (path === "/auth/logout") {
    logoutCsrf = route.request().headers()["x-radhouse-csrf"];
    active = false; await route.fulfill({status: 204}); return;
  }
  if (path === "/chat/history") {
    await route.fulfill(historyFailure ? {status: 503, contentType: "application/json", body: JSON.stringify({error: "conversation_unavailable"})}
      : json({turns: [], older_before: null})); return;
  }
  if (path === "/admin/settings" || path === "/admin/infrastructure") {
    if (path === "/admin/settings") settingsRequests++; else probeRequests++;
    if (holdInfrastructure && path === "/admin/infrastructure") await new Promise(resolve => {finishInfrastructure = resolve;});
    try { await route.fulfill(json(path === "/admin/settings" ? settings : infrastructure)); }
    catch (_) { /* An intentional logout aborts the held request. */ }
    return;
  }
  const filename = {"/": "index.html", "/settings": "admin.html", "/infrastructure": "admin.html", "/admin.js": "admin.js", "/admin.css": "admin.css", "/chat.css": "chat.css", "/chat.js": "chat.js", "/format.js": "format.js", "/browser-view.js": "browser-view.js", "/browser-view.css": "browser-view.css"}[path];
  if (!filename) { await route.fulfill({status: 200, contentType: "text/html", body: "<title>Chat</title><p>Return to Chat</p>"}); return; }
  await route.fulfill({status: 200, contentType: filename.endsWith(".js") ? "text/javascript" : filename.endsWith(".css") ? "text/css" : "text/html",
    headers: {"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'", "Cache-Control": "no-store"},
    body: await readFile(new URL(filename, staticRoot), "utf8")});
});
try {
  await page.goto(`${origin}/`);
  await expect(page.locator("#chat-view")).toBeVisible();
  await expect(page.locator("#management-nav")).toBeVisible();
  await expect(page.locator("#notice-action")).toBeVisible();
  await page.locator("#message").fill("Keep this draft while management access changes.");
  role = "viewer"; historyFailure = false;
  await page.locator("#notice-action").click();
  await expect(page.locator("#management-nav")).toBeHidden();
  await expect(page.locator("#message")).toHaveValue("Keep this draft while management access changes.");
  role = "admin"; await page.reload();
  await expect(page.locator("#management-nav")).toBeVisible();
  await expect(page.locator("#message")).toHaveValue("Keep this draft while management access changes.");
  await page.setViewportSize({width: 390, height: 844});
  await expect.poll(() => page.locator("#message").evaluate(node => node.clientHeight >= node.scrollHeight - 1)).toBe(true);
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error("Chat management navigation overflows mobile viewport");
  for (const name of ["Chat", "Settings", "Infrastructure"]) await expect(page.getByRole("navigation").getByRole("link", {name, exact: true})).toBeVisible();
  if (artifacts) { await mkdir(artifacts, {recursive: true}); await page.screenshot({path: `${artifacts}/chat-management-mobile.png`, fullPage: true}); }
  await page.setViewportSize({width: 1200, height: 950});
  await page.getByRole("navigation").getByRole("link", {name: "Settings", exact: true}).click();
  await expect(page.getByRole("heading", {name: "Settings", exact: true})).toBeVisible();
  await expect(page.locator("#content")).toBeVisible();
  await expect(page.locator("#content")).toContainText("No configured limit");
  await expect(page.locator("#content")).toContainText("Settings are read only");
  await expect(page.locator("#settings-link")).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("textbox")).toHaveCount(0);
  if (artifacts) { await mkdir(artifacts, {recursive: true}); await page.screenshot({path: `${artifacts}/settings-desktop.png`, fullPage: true}); }
  await page.getByRole("link", {name: "Infrastructure", exact: true}).click();
  await expect(page.locator("#content")).toBeVisible();
  await expect(page.locator(".status[data-state='unavailable']")).toHaveText("Unavailable");
  await expect(page.locator(".status[data-state='unverified']")).toHaveText("Unverified");
  await expect(page.locator("#content")).toContainText("<script>window.adminInjected=true</script>");
  if (await page.evaluate(() => window.adminInjected)) throw new Error("Unsafe infrastructure rendering");
  await expect(page.locator("#content script,#content img")).toHaveCount(0);
  await expect(page.locator(".release-id")).toHaveText("Unverified");
  infrastructure.components[2].detail = "Document reader is available; full-document access is not connected.";
  await page.getByRole("button", {name: "Refresh", exact: true}).click();
  await expect(page.locator("#content")).toBeVisible();
  if (probeRequests !== 2) throw new Error("Refresh failed to repeat current checks");
  if (artifacts) await page.screenshot({path: `${artifacts}/infrastructure-desktop.png`, fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await expect(page.getByRole("navigation")).toBeVisible();
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error("Infrastructure overflows mobile viewport");
  if (artifacts) await page.screenshot({path: `${artifacts}/infrastructure-mobile.png`, fullPage: true});
  await page.getByRole("link", {name: "Settings", exact: true}).click();
  await expect(page.locator("#content")).toBeVisible();
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error("Settings overflows mobile viewport");
  if (artifacts) await page.screenshot({path: `${artifacts}/settings-mobile.png`, fullPage: true});
  // A changed role clears a previously visible page and does not call a probe.
  role = "viewer"; const previousProbes = probeRequests, previousSettings = settingsRequests;
  await page.getByRole("button", {name: "Refresh", exact: true}).click();
  await expect(page.locator("#notice-text")).toHaveText("This account does not have access to this page.");
  await expect(page.locator("#content")).toBeHidden();
  if (probeRequests !== previousProbes || settingsRequests !== previousSettings) throw new Error("Denied UI fetched management data");
  role = "operator"; await page.goto(`${origin}/infrastructure`);
  await expect(page.locator("#content")).toBeVisible();
  active = false; await page.getByRole("button", {name: "Refresh", exact: true}).click();
  await expect(page.locator("#notice-text")).toHaveText("Sign in to open this page.");
  await expect(page.locator("#content")).toBeEmpty();
  await expect(page.locator("#logout")).toBeHidden();
  // Logout erases the page, preserves CSRF checks and defeats an old in-flight reply.
  active = true; await page.reload(); await expect(page.locator("#content")).toBeVisible();
  holdInfrastructure = true; await page.getByRole("button", {name: "Refresh", exact: true}).click();
  await expect.poll(() => typeof finishInfrastructure).toBe("function");
  await page.getByRole("button", {name: "Sign out", exact: true}).click();
  finishInfrastructure(); await page.waitForURL(`${origin}/`);
  if (logoutCsrf !== "synthetic-csrf") throw new Error("Logout omitted session CSRF proof");
  // Fail original persistence, then hold a successful write to exercise both
  // full-page navigation hazards using the browser's real IndexedDB.
  await context.addInitScript(() => {
    const control = window.draftSaveControl = {fail: false, hold: false, attempts: 0, completions: []};
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (...args) {
      control.attempts++;
      if (control.fail) throw new DOMException("Synthetic storage quota", "QuotaExceededError");
      return put.apply(this, args);
    };
    const complete = Object.getOwnPropertyDescriptor(IDBTransaction.prototype, "oncomplete");
    Object.defineProperty(IDBTransaction.prototype, "oncomplete", {...complete,
      set(handler) {
        complete.set.call(this, typeof handler !== "function" ? handler : function (event) {
          const finish = () => handler.call(this, event);
          if (this.mode === "readwrite" && control.hold) control.completions.push(finish);
          else finish();
        });
      }});
  });
  active = true; role = "admin"; holdInfrastructure = false;
  await page.goto(`${origin}/`);
  await expect(page.locator("#chat-view")).toBeVisible();
  await page.locator("#message").fill("Keep originals during management navigation.");
  await page.evaluate(() => { window.draftSaveControl.fail = true; });
  await page.locator("#file-picker").setInputFiles({name: "unsaved-original.txt", mimeType: "text/plain", buffer: Buffer.from("The original must survive.")});
  await expect(page.locator("#notice-text")).toContainText("Your browser couldn’t save this draft");
  await expect(page.locator("#draft-files")).toContainText("unsaved-original.txt");
  const failedAttempts = await page.evaluate(() => window.draftSaveControl.attempts);
  await page.getByRole("navigation").getByRole("link", {name: "Settings", exact: true}).click();
  await expect.poll(() => page.evaluate(() => window.draftSaveControl.attempts)).toBeGreaterThan(failedAttempts);
  expect(page.url()).toBe(`${origin}/`);
  await expect(page.locator("#message")).toHaveValue("Keep originals during management navigation.");
  await expect(page.locator("#draft-files")).toContainText("unsaved-original.txt");
  // Once storage recovers the same retained original can safely cross pages.
  await page.evaluate(() => { window.draftSaveControl.fail = false; });
  await page.getByRole("navigation").getByRole("link", {name: "Settings", exact: true}).click();
  await expect(page.getByRole("heading", {name: "Settings", exact: true})).toBeVisible();
  await page.getByRole("navigation").getByRole("link", {name: "Chat", exact: true}).click();
  await expect(page.locator("#draft-files")).toContainText("unsaved-original.txt");
  await page.evaluate(() => { window.draftSaveControl.hold = true; });
  await page.locator("#file-picker").setInputFiles({name: "pending-original.txt", mimeType: "text/plain", buffer: Buffer.from("Save this original before leaving.")});
  await expect.poll(() => page.evaluate(() => window.draftSaveControl.completions.length)).toBe(1);
  await page.getByRole("navigation").getByRole("link", {name: "Settings", exact: true}).click();
  expect(page.url()).toBe(`${origin}/`);
  await page.locator("#message").fill("Latest edit while the original was saving.");
  await page.evaluate(() => {
    window.draftSaveControl.hold = false;
    window.draftSaveControl.completions.splice(0).forEach(finish => finish());
  });
  await expect(page.getByRole("heading", {name: "Settings", exact: true})).toBeVisible();
  await page.getByRole("navigation").getByRole("link", {name: "Chat", exact: true}).click();
  await expect(page.locator("#message")).toHaveValue("Latest edit while the original was saving.");
  await expect(page.locator("#draft-files")).toContainText("unsaved-original.txt");
  await expect(page.locator("#draft-files")).toContainText("pending-original.txt");
  const originals = await page.evaluate(async () => {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open("radhouse-chat-drafts", 1);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try {
      const saved = await new Promise((resolve, reject) => {
        const request = db.transaction("drafts").objectStore("drafts").get("radhouse-chat-draft:alice");
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      return Promise.all(saved.attachments.map(async file => [file.name, await file.blob.text()]));
    } finally { db.close(); }
  });
  expect(originals).toEqual([["unsaved-original.txt", "The original must survive."], ["pending-original.txt", "Save this original before leaving."]]);
  if (errors.length) throw new Error(`Browser errors: ${errors.join(", ")}`);
  console.log("Admin browser checks passed: Chat navigation, draft/original continuity under failed and pending writes, read-only settings, fixed health states, refresh, role/session changes, CSRF logout, stale-request cancellation, mobile layout and safe text rendering.");
} finally { await context.close(); await browser.close(); }
