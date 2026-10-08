// Real browser journey using explicit synthetic HTTP data; no deployed claims.
import {readFile, mkdir} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import {createServer} from "node:http";
import {cover, closeBrowser} from "./browser-coverage.mjs";

const moduleUrl = process.env.RADHOUSE_PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs", import.meta.url).href;
const {chromium, expect: baseExpect} = await import(moduleUrl);
const expect = baseExpect.configure({timeout: 10000});
const staticRoot = new URL("../src/radhouse/chat/static/", import.meta.url);
const artifacts = process.env.RADHOUSE_LIBRARY_SCREENSHOTS;
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=", "base64");
const wav = Buffer.alloc(76); wav.write("RIFF", 0); wav.writeUInt32LE(68, 4); wav.write("WAVEfmt ", 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(8000, 24);
wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(32, 40);
const olderId = "00000000-0000-4000-8000-000000000010", staleId = "00000000-0000-4000-8000-000000000020", recentId = "00000000-0000-4000-8000-000000000040";
const originals = new Map();
function file(number, name, kind, source = "user", requestId = olderId) {
  const id = `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
  const data = kind === "image" ? png : kind === "audio" ? wav : Buffer.from(`Original bytes of ${name}.`);
  originals.set(id, data);
  return {id: "file:" + id, file_id: id, name, kind, source, request_id: requestId,
    size: data.length, media_type: kind === "image" ? "image/png" : kind === "audio" ? "audio/wav" : "application/octet-stream",
    download_url: "/chat/files/" + id + "/content", created_at: "2026-10-08T12:00:00Z"};
}
const files = [file(1, "guide.pdf", "document"), file(2, "plan.docx", "document"), file(3, "budget.xlsx", "document"),
  file(4, "slides.pptx", "document"), file(5, "diagram.png", "image"), file(6, "voice.wav", "audio"),
  file(7, "summary.txt", "text", "assistant", recentId)];
const olderFile = file(8, "archive.txt", "text", "user", null);
const recent = {seq: 40, request_id: recentId, text: "A recent question", output: "A recent answer", status: "completed", attachments: [], shared_files: [files[6]]};
const older = {seq: 1, request_id: olderId, text: "The older question about the PDF", output: "The older answer with its document", status: "completed",
  attachments: [{...files[0], position: 0, reading_state: "available"}], shared_files: []};
let historyTurn = recent;
let active = true, authRequests = 0, historyRequests = 0, browserRequests = 0, frameRequests = 0, messageRequests = 0;
let denyLibrary = false, holdLibrary = false, finishLibrary = null, logoutCsrf = null;
let holdMessage = false, finishMessage = null;
const libraryRequests = [], contentRequests = [];
const session = () => ({username: "alice", csrf_token: "synthetic-csrf", management: {read: true, write: false}, features: {browser: true, documents: true}});
// Chromium downloads need an actual HTTP body rather than interception alone.
const binaryServer = createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1"), path = url.pathname;
  const id = path.includes("/attachments/") ? older.attachments[0].file_id : path.split("/")[3];
  const saved = [...files, olderFile].find(item => item.file_id === id);
  if (request.method !== "GET" || !saved || (!path.endsWith("/content") && !path.includes("/attachments/"))) { response.writeHead(404); response.end(); return; }
  contentRequests.push({name: saved.name, download: url.searchParams.has("download")});
  const data = originals.get(id), headers = {"Content-Type": saved.media_type, "Content-Length": String(data.length), "Cache-Control": "no-store"};
  if (url.searchParams.has("download")) headers["Content-Disposition"] = `attachment; filename="${saved.name}"`;
  response.writeHead(200, headers); response.end(data);
});
await new Promise((resolve, reject) => { binaryServer.once("error", reject); binaryServer.listen(0, "127.0.0.1", resolve); });
const origin = `http://127.0.0.1:${binaryServer.address().port}`;
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1280, height: 900}});
const page = await context.newPage(), errors = [];
await cover(page); page.on("pageerror", error => errors.push(error.message));
await context.route(`${origin}/**`, async route => {
  const url = new URL(route.request().url()), path = url.pathname;
  const json = data => ({status: 200, contentType: "application/json", body: JSON.stringify(data)});
  if (path === "/auth/session") {
    authRequests++; await route.fulfill(active ? json(session()) : {status: 401, contentType: "application/json", body: '{"error":"authentication_required"}'}); return;
  }
  if (path === "/auth/login") { active = true; await route.fulfill(json(session())); return; }
  if (path === "/auth/logout") {
    logoutCsrf = route.request().headers()["x-radhouse-csrf"]; active = false; await route.fulfill({status: 204}); return;
  }
  if (path === "/chat/history") { historyRequests++; await route.fulfill(json({turns: [historyTurn], older_before: 40})); return; }
  if (path === "/chat/reply") { await route.fulfill(json({turns: [historyTurn], older_before: 40})); return; }
  if (path.startsWith("/chat/messages/") && !path.includes("/attachments/")) {
    messageRequests++;
    if (holdMessage) { holdMessage = false; await new Promise(resolve => { finishMessage = resolve; }); }
    await route.fulfill(json({turn: path.endsWith(staleId) ? {...older, seq: 2, request_id: staleId, text: "A stale association that must not refocus Chat"} : older})); return;
  }
  if (path === "/chat/library") {
    libraryRequests.push({query: url.searchParams.get("query"), source: url.searchParams.get("source"), before: url.searchParams.get("before")});
    if (denyLibrary) { denyLibrary = false; active = false; await route.fulfill({status: 401, contentType: "application/json", body: '{"error":"authentication_required"}'}); return; }
    const query = (url.searchParams.get("query") || "").toLowerCase(), source = url.searchParams.get("source");
    const all = [...files, olderFile].filter(item => (!query || item.name.toLowerCase().includes(query)) && (!source || source === "all" || item.source === source));
    const before = url.searchParams.get("before");
    const response = json({files: before ? all.slice(7) : all.slice(0, 7), next_cursor: !before && all.length > 7 ? "fixture-older" : null});
    if (holdLibrary) { holdLibrary = false; await new Promise(resolve => { finishLibrary = resolve; }); }
    try { await route.fulfill(response); } catch (_) { /* A page deliberately cancels stale requests. */ }
    return;
  }
  if (path === "/chat/browser") { browserRequests++; await route.fulfill(json({state: "idle", run_id: null, generation: null, url: null})); return; }
  if (path === "/chat/browser/frame") { frameRequests++; await route.fulfill({status: 409}); return; }
  if (path.startsWith("/chat/files/") && path.endsWith("/content") || path.includes("/attachments/")) {
    await route.continue(); return;
  }
  const filename = ["/", "/library", "/browser"].includes(path) ? "index.html"
    : ["/chat.css", "/chat.js", "/format.js", "/browser-view.js", "/browser-view.css", "/navigation.js", "/navigation.css", "/library.js"].includes(path) ? path.slice(1)
    : /^\/icons\/(pdf|word|excel|powerpoint)\.svg$/.test(path) ? path.slice(1) : null;
  if (!filename) { await route.fulfill({status: 404}); return; }
  await route.fulfill({status: 200, contentType: filename.endsWith(".js") ? "text/javascript" : filename.endsWith(".css") ? "text/css" : filename.endsWith(".svg") ? "image/svg+xml" : "text/html",
    body: await readFile(new URL(filename, staticRoot), "utf8"), headers: {"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; base-uri 'none'", "Cache-Control": "no-store"}});
});
async function navigate(name) {
  if (await page.locator("#navigation-panel").isHidden()) { await page.locator("#navigation-toggle").click(); }
  await page.getByRole("navigation").getByRole("link", {name, exact: true}).click();
}
async function savedOriginals() {
  return page.evaluate(async () => {
    await draftWrites;
    const db = await new Promise((resolve, reject) => { const request = indexedDB.open("radhouse-chat-drafts", 1); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
    try {
      const saved = await new Promise((resolve, reject) => { const request = db.transaction("drafts").objectStore("drafts").get("radhouse-chat-draft:alice"); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      return {text: saved.text, files: await Promise.all(saved.attachments.map(async item => ({name: item.name, bytes: [...new Uint8Array(await item.blob.arrayBuffer())]})))};
    } finally { db.close(); }
  });
}
async function screenshot(name) {
  if (artifacts) { await mkdir(artifacts, {recursive: true}); await page.screenshot({path: `${artifacts}/${name}.png`, fullPage: true}); }
}
async function noOverflow() { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); }
async function login() {
  await page.locator("#username").fill("alice"); await page.locator("#password").fill("fixture-password"); await page.locator("#totp").fill("123456");
  await page.getByRole("button", {name: "Sign in", exact: true}).click();
}
try {
  await page.goto(`${origin}/`); await expect(page.locator("#chat-view")).toBeVisible();
  await expect(page.locator(".pending")).toHaveCount(0);
  await page.locator("#message").fill("An unsent draft stays here while I use Library and Browser.");
  const draftText = "The retained original draft bytes.";
  await page.locator("#file-picker").setInputFiles([{name: "draft-note.txt", mimeType: "text/plain", buffer: Buffer.from(draftText)}, {name: "draft-image.png", mimeType: "image/png", buffer: png}]);
  await expect(page.locator("#draft-files .attachment")).toHaveCount(2);
  const saved = await savedOriginals(); expect(saved.files[0].bytes).toEqual([...Buffer.from(draftText)]); expect(saved.files[1].bytes).toEqual([...png]);

  // Sharing a file before answer text must preserve the actual reply state.
  const fileReply = page.locator(`.turn[data-request-id='${recentId}']`);
  for (const [status, error, message] of [
    ["running", null, "Radhouse is replying…"],
    ["failed", "reply_failed", "The assistant couldn’t finish this reply. You can send another message."],
    ["cancelled", "reply_cancelled", "Reply stopped. You can send another message."],
    ["interrupted", "reply_interrupted", "The reply was interrupted. You can send another message."],
    ["completed", null, null],
  ]) {
    historyTurn = {...recent, output: "", status, error};
    await page.reload(); await expect(page.locator("#chat-view")).toBeVisible();
    await expect(fileReply.locator(".assistant .attachment")).toHaveCount(1);
    await expect(fileReply.getByRole("link", {name: "summary.txt", exact: true})).toHaveAttribute("href", recent.shared_files[0].download_url + "?download=true");
    if (message) {
      await expect(fileReply.locator(error ? ".turn-error" : ".pending")).toHaveText(message);
      await expect(fileReply.locator(error ? ".pending" : ".turn-error")).toHaveCount(0);
    } else { await expect(fileReply.locator(".pending,.turn-error")).toHaveCount(0); }
    await expect(fileReply.getByRole("button", {name: "Copy answer", exact: true})).toBeHidden();
    expect(await savedOriginals()).toEqual(saved);
  }
  const sharedDownload = page.waitForEvent("download"); await fileReply.getByRole("link", {name: "summary.txt", exact: true}).click();
  expect(await readFile(await (await sharedDownload).path())).toEqual(originals.get(recent.shared_files[0].file_id));
  historyTurn = recent; await page.reload(); await expect(page.locator("#chat-view")).toBeVisible();
  const originalAuthRequests = authRequests, originalHistoryRequests = historyRequests;
  await navigate("Library"); await expect(page.locator("#library-view")).toBeVisible(); await expect(page.locator("#library-files .library-file")).toHaveCount(7);
  await expect(page.locator("#chat-view")).toBeHidden(); await expect(page.locator("#library-link")).toHaveAttribute("aria-current", "page");
  for (const [name, icon] of [["guide.pdf", "pdf"], ["plan.docx", "word"], ["budget.xlsx", "excel"], ["slides.pptx", "powerpoint"]]) {
    await expect(page.locator(".library-file").filter({has: page.getByRole("link", {name, exact: true})}).locator(".document-icon")).toHaveAttribute("src", `/icons/${icon}.svg`);
  }
  const image = page.locator("#library-files .image-preview"); await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate(node => node.complete && node.naturalWidth > 0)).toBe(true);
  await expect(page.locator("#library-files")).toContainText("Uploaded by you"); await expect(page.locator("#library-files")).toContainText("Shared by Radhouse");
  const audio = page.locator("#library-files audio"); await expect(audio).toHaveAttribute("preload", "none"); await expect(audio).not.toHaveAttribute("autoplay");
  expect(contentRequests.some(item => item.name === "voice.wav")).toBe(false);
  await screenshot("library-desktop");
  for (const name of ["guide.pdf", "voice.wav"]) {
    const savedFile = files.find(item => item.name === name);
    await expect(page.locator("#library-files").getByRole("link", {name, exact: true})).toHaveAttribute("href", savedFile.download_url + "?download=true");
    const downloadEvent = page.waitForEvent("download"); await page.locator("#library-files").getByRole("link", {name, exact: true}).click();
    const download = await downloadEvent; expect(download.suggestedFilename()).toBe(name);
    expect(await readFile(await download.path())).toEqual(originals.get(files.find(item => item.name === name).file_id));
  }
  await page.locator("#library-files summary").filter({hasText: "Play audio"}).click(); await expect(audio).toBeVisible();
  expect(await audio.evaluate(node => node.paused)).toBe(true);

  await navigate("Browser"); await expect(page.locator("#browser-page")).toBeVisible();
  await expect(page.locator(".browser-view-status")).toHaveText("Browser is idle"); await expect(page.locator("#browser-idle-hint")).toBeVisible();
  expect(browserRequests).toBeGreaterThan(0); expect(frameRequests).toBe(0);
  await screenshot("browser-idle-desktop");
  await page.goBack(); await expect(page.locator("#library-view")).toBeVisible();
  await page.goForward(); await expect(page.locator("#browser-page")).toBeVisible();
  await navigate("Chat"); await expect(page.locator("#message")).toHaveValue(saved.text); await expect(page.locator("#draft-files .attachment")).toHaveCount(2);
  expect(authRequests).toBe(originalAuthRequests); expect(historyRequests).toBe(originalHistoryRequests); expect(await savedOriginals()).toEqual(saved);
  await navigate("Library"); await page.reload(); await expect(page.locator("#library-view")).toBeVisible(); await expect(page.locator("#library-files .library-file")).toHaveCount(7);
  expect(await savedOriginals()).toEqual(saved); await navigate("Chat"); await expect(page.locator("#message")).toHaveValue(saved.text); await navigate("Library");

  const beforeSearch = libraryRequests.length;
  await page.locator("#library-search").fill("budget"); await expect(page.locator("#library-files .library-file")).toHaveCount(1);
  expect(libraryRequests.length).toBeGreaterThan(beforeSearch); expect(libraryRequests.at(-1)).toEqual({query: "budget", source: "all", before: null});
  await page.locator("#library-search").fill("no-such-file"); await expect(page.locator("#library-status")).toHaveText("No files match this search.");
  await page.locator("#library-search").fill(""); await page.locator("#library-source").selectOption("assistant");
  await expect(page.locator("#library-files .library-file")).toHaveCount(1); await expect(page.locator("#library-files")).toContainText("summary.txt");
  expect(libraryRequests.at(-1)).toEqual({query: "", source: "assistant", before: null});
  await page.locator("#library-source").selectOption("user"); await expect(page.locator("#library-files .library-file")).toHaveCount(7);
  await expect(page.locator("#library-files")).not.toContainText("summary.txt");
  await page.locator("#library-source").selectOption("all"); await expect(page.locator("#library-more")).toBeVisible();
  await page.locator("#library-more").click(); await expect(page.locator("#library-files .library-file")).toHaveCount(8); await expect(page.locator("#library-more")).toBeHidden();
  expect(libraryRequests.at(-1)).toEqual({query: "", source: "all", before: "fixture-older"});
  files.unshift(file(9, "freshly-added.pdf", "document", "user", staleId));
  await page.locator("#library-refresh").click(); await expect(page.locator("#library-files")).toContainText("freshly-added.pdf");
  await expect(page.locator("#library-files .library-file")).toHaveCount(7); await expect(page.locator("#library-more")).toBeVisible();

  const olderCard = page.locator("#library-files .library-file").filter({has: page.getByRole("link", {name: "guide.pdf", exact: true})});
  await olderCard.getByRole("link", {name: "Open in Chat", exact: true}).click();
  await expect(page.locator(`.turn[data-request-id='${olderId}']`)).toBeFocused(); await expect(page.locator("#messages")).toContainText(older.text);
  expect(new URL(page.url()).searchParams.get("message")).toBe(olderId); expect(messageRequests).toBe(1);
  await expect(page.locator("#message")).toHaveValue(saved.text); expect(await savedOriginals()).toEqual(saved);
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goBack(); await expect(page.locator("#library-view")).toBeVisible();
    await page.goForward(); await expect(page.locator(`.turn[data-request-id='${olderId}']`)).toBeFocused();
    expect(new URL(page.url()).searchParams.get("message")).toBe(olderId);
  }
  expect(messageRequests).toBe(1);
  await page.reload(); await expect(page.locator(`.turn[data-request-id='${olderId}']`)).toBeFocused(); expect(messageRequests).toBe(2);

  // A delayed association reply cannot refocus a workspace the owner has left.
  await navigate("Library"); await expect(page.locator("#library-files")).toContainText("freshly-added.pdf");
  holdMessage = true;
  await page.locator("#library-files .library-file").filter({has: page.getByRole("link", {name: "freshly-added.pdf", exact: true})}).getByRole("link", {name: "Open in Chat", exact: true}).click();
  await expect.poll(() => typeof finishMessage).toBe("function");
  await navigate("Browser"); await expect(page.locator("#browser-title")).toBeFocused();
  const staleResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(staleId));
  finishMessage(); await (await staleResponse).finished(); await page.evaluate(() => Promise.resolve());
  await expect(page.locator("#browser-title")).toBeFocused(); await expect(page.locator("#browser-page")).toBeVisible();
  await expect(page.locator(`.turn[data-request-id='${staleId}']`)).toHaveCount(0);

  await page.setViewportSize({width: 390, height: 844}); await expect(page.locator("#navigation-panel")).toBeHidden(); await navigate("Library");
  await expect(page.locator("#library-view")).toBeVisible(); await expect(page.locator("#library-title")).toBeFocused();
  await expect(page.locator("#library-files .library-file")).toHaveCount(7); await noOverflow(); await screenshot("library-mobile");
  await page.locator("#navigation-toggle").click(); await expect(page.locator("#navigation-panel")).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape"); await expect(page.locator("#navigation-toggle")).toBeFocused();
  await navigate("Browser"); await expect(page.locator("#browser-page")).toBeVisible(); await expect(page.locator(".browser-view-status")).toHaveText("Browser is idle"); await noOverflow(); await screenshot("browser-idle-mobile");
  await navigate("Chat"); await expect(page.locator("#message")).toHaveValue(saved.text); await noOverflow();
  await page.setViewportSize({width: 320, height: 600}); await navigate("Library"); await expect(page.locator("#library-files .library-file")).toHaveCount(7); await noOverflow();

  // A library 401 removes every private view while retaining unsent originals.
  denyLibrary = true; await page.locator("#library-refresh").click(); await expect(page.locator("#login-view")).toBeVisible();
  await expect(page.locator("#library-files")).toBeEmpty(); await expect(page.locator("#library-view")).toBeHidden(); await expect(page.locator("#browser-page")).toBeHidden();
  await expect(page.locator("#navigation-toggle")).toBeHidden(); expect(await savedOriginals()).toEqual(saved);
  await login(); await expect(page.locator("#library-view")).toBeVisible(); await expect(page.locator("#library-files .library-file")).toHaveCount(7);
  await navigate("Chat"); await expect(page.locator("#message")).toHaveValue(saved.text); await navigate("Library");

  // Deliberately ignore AbortSignal in this fixture to deliver a success after sign-out.
  await page.evaluate(() => {
    const originalFetch = window.fetch;
    window.fetch = (input, options) => originalFetch(input, String(input).startsWith("/chat/library") ? {...options, signal: undefined} : options);
  });
  holdLibrary = true; await page.locator("#library-refresh").click(); await expect.poll(() => typeof finishLibrary).toBe("function");
  await page.locator("#logout").click(); await expect(page.locator("#login-view")).toBeVisible();
  const lateResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/chat/library" && response.status() === 200);
  finishLibrary(); await (await lateResponse).finished(); await page.evaluate(() => Promise.resolve());
  await expect(page.locator("#library-files")).toBeEmpty(); await expect(page.locator("#library-view")).toBeHidden(); await expect(page.locator("#navigation-toggle")).toBeHidden();
  expect(logoutCsrf).toBe("synthetic-csrf"); expect(await savedOriginals()).toEqual(saved); expect(errors).toEqual([]);
  console.log("Library browser checks passed: file-only reply progress/errors/completion, independent navigation, exact original downloads, file visuals, manual audio, search/source/pagination/refresh, older Chat links, draft continuity, mobile access, session expiry and stale success after logout.");
} finally {
  try { await closeBrowser(browser); }
  finally { await new Promise((resolve, reject) => binaryServer.close(error => error ? reject(error) : resolve())); }
}
