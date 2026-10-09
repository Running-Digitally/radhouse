// Real Chromium checks of the shared shell and admin wiring with HTTP fixtures.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import {cover, closeBrowser} from "./browser-coverage.mjs";

const moduleUrl = process.env.RADHOUSE_PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs", import.meta.url).href;
const {chromium, expect: baseExpect} = await import(moduleUrl);
const expect = baseExpect.configure({timeout: 10000});
const root = new URL("../src/radhouse/chat/static/", import.meta.url);
const origin = "http://127.0.0.1:61392";
const fixture = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="/chat.css"><link rel="stylesheet" href="/navigation.css">
  <script src="/navigation.js" defer></script></head><body><div class="shell">
  <header><a href="/" class="brand">Radhouse</a><button id="logout">Sign out</button></header>
  <nav id="management-nav" aria-label="Main navigation" hidden><a href="/">Chat</a><a href="/library">Library</a>
  <a href="/browser">Browser</a><a href="/terminal">Terminal</a><a href="/about-you">About You</a><a href="/settings" id="settings-link" data-management>Settings</a>
  <a href="/infrastructure" id="infrastructure-link" data-management>Infrastructure</a></nav>
  <main><label for="draft">Draft</label><textarea id="draft"></textarea><button id="main-action">Keep writing</button></main>
  </div></body></html>`;
let role = "admin", authenticated = true, managementRequests = 0;
const session = () => authenticated ? {username: "alice", csrf_token: "fixture", management: {read: role !== "viewer", write: false}} : null;
const settings = {checked_at: "2026-10-08T12:00:00Z", authentication: {idle_timeout_seconds: 1800, maximum_session_seconds: 43200, remembered_session_seconds: 2592000},
  files: {upload_size_limit_bytes: null, upload_count_limit: null, audio_transcription_enabled: false},
  documents: {selective_access_enabled: true}, browser: {enabled: true}, messages: {character_limit: 16000}};
const infrastructure = {checked_at: settings.checked_at, components: [], versions: {release_commit: "fixture", package: "fixture", python: "fixture"}};
const catalog=JSON.parse(await readFile(new URL("agent-profile/catalog.json",root),"utf8"));
const profile={schema:"radhouse.agent-profile.v1",revision:0,name:"",intro:"",theme:"hearthside",portrait:"ember",accent:"fern",surface:"paper",stateMotion:true,iconMotion:true};
const browser = await chromium.launch({headless: true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
const context = await browser.newContext({viewport: {width: 1200, height: 850}});
const page = await context.newPage(), errors = [];
await cover(page); page.on("pageerror", error => errors.push(error.message));
await context.route(`${origin}/**`, async route => {
  const path = new URL(route.request().url()).pathname;
  const json = data => ({status: 200, contentType: "application/json", body: JSON.stringify(data)});
  if (path === "/auth/session") {
    await route.fulfill(authenticated ? json(session()) : {status: 401, contentType: "application/json", body: '{"error":"authentication_required"}'}); return;
  }
  if (path.startsWith("/admin/")) {
    managementRequests++; await route.fulfill(json(path === "/admin/settings" ? settings : infrastructure)); return;
  }
  if(path==="/chat/agent-profile"){
    await route.fulfill(authenticated?json(profile):{status:401,contentType:"application/json",body:'{"error":"authentication_required"}'});return;
  }
  if(path==="/workspace-assets/agent-profile/catalog.json"){await route.fulfill(json(catalog));return;}
  if (["/", "/library", "/browser"].includes(path)) {
    await route.fulfill({status: 200, contentType: "text/html", body: fixture}); return;
  }
  const filename = ["/settings", "/infrastructure"].includes(path) ? "admin.html"
    : ["/chat.css", "/admin.css", "/admin.js", "/navigation.css", "/navigation.js"].includes(path) ? path.slice(1)
    : ["/workspace-assets/agent-profile.js","/workspace-assets/agent-profile.css",...catalog.profiles.map(entry=>entry.asset)].includes(path) ? path.slice("/workspace-assets/".length) : null;
  if (!filename) { await route.fulfill({status: 404}); return; }
  await route.fulfill({status: 200, contentType: filename.endsWith(".js") ? "text/javascript" : filename.endsWith(".css") ? "text/css" : filename.endsWith(".webp")?"image/webp":"text/html",
    body: await readFile(new URL(filename, root)),
    headers: {"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'", "Cache-Control": "no-store"}});
});
const update = async value => page.evaluate(current => window.RadhouseNavigation.update(current), value);
const menu = () => page.locator("#navigation-toggle");
const panel = () => page.locator("#navigation-panel");
const link = name => page.getByRole("navigation", {name: "Main navigation"}).getByRole("link", {name, exact: true});
const noOverflow = async () => {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
};
try {
  await page.goto(`${origin}/`);
  await expect(menu()).toBeHidden(); await expect(panel()).toBeHidden();
  await update(session());
  await expect(panel()).toBeVisible(); await expect(menu()).toHaveAttribute("aria-expanded", "true");
  for (const name of ["Your Agent", "Chat", "Library", "Browser", "Terminal", "About You", "Settings", "Infrastructure"]) { await expect(link(name)).toBeVisible(); }
  await expect(link("Your Agent")).toHaveAttribute("href","/agent");
  await expect(link("Terminal").locator("svg")).toHaveAttribute("data-icon","terminal");
  await expect(link("About You").locator("svg")).toHaveAttribute("data-icon","about-you");
  await expect(link("Chat")).toHaveAttribute("aria-current", "page");
  const positions = await page.evaluate(() => {
    const nav = document.getElementById("navigation-panel").getBoundingClientRect(), main = document.querySelector("main").getBoundingClientRect();
    return {left: nav.left, right: nav.right, main: main.left, bottom: main.bottom, height: innerHeight};
  });
  expect(positions.right).toBeLessThan(positions.main); expect(positions.bottom).toBeLessThanOrEqual(positions.height);
  await page.locator("#draft").fill("Keep this draft when the menu collapses.");
  await menu().click(); await expect(panel()).toBeHidden();
  await update(session()); await expect(panel()).toBeHidden();
  await expect(page.locator("#draft")).toHaveValue("Keep this draft when the menu collapses.");
  await page.reload(); await update(session()); await expect(panel()).toBeHidden();
  await menu().click(); await expect(panel()).toBeVisible();
  role = "viewer"; await update(session());
  for (const name of ["Your Agent", "Chat", "Library", "Browser", "Terminal", "About You"]) { await expect(link(name)).toBeVisible(); }
  await expect(page.locator("#settings-link")).toBeHidden(); await expect(page.locator("#infrastructure-link")).toBeHidden();
  role = "admin"; await update(session());

  // Small screens start closed, with a modal drawer and an inert page underneath.
  await page.setViewportSize({width: 390, height: 844}); await expect(panel()).toBeHidden(); await noOverflow();
  await menu().click(); await expect(panel()).toBeVisible(); await expect(panel()).toHaveAttribute("aria-modal", "true");
  await expect(link("Your Agent")).toBeFocused();
  expect(await page.locator("main").evaluate(node => node.inert)).toBe(true);
  expect(await page.locator("header").evaluate(node => node.inert)).toBe(true);
  await link("Infrastructure").focus(); await page.keyboard.press("Tab"); await expect(page.locator("#navigation-close")).toBeFocused();
  await page.keyboard.press("Shift+Tab"); await expect(link("Infrastructure")).toBeFocused();
  await page.keyboard.press("Escape"); await expect(panel()).toBeHidden(); await expect(menu()).toBeFocused();
  expect(await page.locator("main").evaluate(node => node.inert)).toBe(false);
  await menu().click(); await page.locator(".navigation-backdrop").click({position: {x: 370, y: 400}});
  await expect(panel()).toBeHidden(); await expect(menu()).toBeFocused();
  await page.setViewportSize({width: 320, height: 600}); await noOverflow();
  await menu().click(); await noOverflow(); await page.locator("#navigation-close").click();
  await page.locator("main").evaluate(node => { node.inert = true; });
  await menu().click(); await page.keyboard.press("Escape");
  expect(await page.locator("main").evaluate(node => node.inert)).toBe(true);
  await page.locator("main").evaluate(node => { node.inert = false; });
  await menu().click(); await page.locator("#navigation-close").focus();
  await page.setViewportSize({width: 1200, height: 850}); await expect(panel()).toBeVisible();
  await expect(link("Your Agent")).toBeFocused();
  await update(null); await expect(panel()).toBeHidden(); await expect(menu()).toBeHidden();

  await page.goto(`${origin}/browser`); await update(session());
  await expect(link("Browser")).toHaveAttribute("aria-current", "page");
  await expect(link("Chat")).not.toHaveAttribute("aria-current", "page");

  // Real admin assets use the same shell and current session role.
  await page.goto(`${origin}/settings`); await expect(page.locator("#content")).toBeVisible();
  await expect(page.getByRole("heading",{name:"Appearance",exact:true})).toBeVisible();
  await expect(page.getByRole("link",{name:"Customize your agent and appearance",exact:true})).toHaveAttribute("href","/agent");
  await expect(page.getByRole("switch",{name:"Icon animation",exact:true})).toHaveCount(0);
  await expect(page.locator(".rh-header-portrait img")).toHaveAttribute("src",profile.portrait?catalog.profiles.find(entry=>entry.id===profile.portrait).asset:"");
  await page.reload();await expect(page.getByRole("link",{name:"Customize your agent and appearance",exact:true})).toBeVisible();
  await expect(link("Settings")).toHaveAttribute("aria-current", "page");
  await expect(link("Library")).toBeVisible(); await expect(link("Browser")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollHeight > innerHeight)).toBe(true);
  await page.setViewportSize({width: 390, height: 844}); await expect(panel()).toBeHidden(); await noOverflow();
  await menu().click(); await link("Infrastructure").click();
  await expect(page.locator("#content")).toBeVisible(); await expect(panel()).toBeHidden();
  await menu().click(); await expect(link("Infrastructure")).toHaveAttribute("aria-current", "page");
  await page.keyboard.press("Escape");
  role = "viewer"; const previousRequests = managementRequests;
  await page.locator("#refresh").click(); await expect(page.locator("#content")).toBeHidden();
  await expect(page.locator("#notice-text")).toHaveText("This account does not have access to this page.");
  expect(managementRequests).toBe(previousRequests);
  await menu().click(); await expect(link("Library")).toBeVisible(); await expect(page.locator("#settings-link")).toBeHidden();
  await page.keyboard.press("Escape");
  authenticated = false; await page.reload();
  await expect(menu()).toBeHidden(); await expect(panel()).toBeHidden(); await expect(page.locator("#content")).toBeEmpty();
  await expect(page.locator("#notice-text")).toHaveText("Sign in to open this page.");

  // A blocked browser storage API cannot prevent navigation.
  const deniedStorage = await browser.newContext({viewport: {width: 1000, height: 700}});
  await deniedStorage.addInitScript(() => Object.defineProperty(window, "localStorage", {get() { throw new Error("blocked"); }}));
  const deniedPage = await deniedStorage.newPage();
  await deniedPage.route(`${origin}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/") { await route.fulfill({status: 200, contentType: "text/html", body: fixture}); return; }
    await route.fulfill({status: 200, contentType: path.endsWith(".js") ? "text/javascript" : "text/css", body: await readFile(new URL(path.slice(1), root), "utf8")});
  });
  await deniedPage.goto(`${origin}/`);
  await deniedPage.evaluate(() => window.RadhouseNavigation.update({username: "alice"}));
  await expect(deniedPage.locator("#navigation-panel")).toBeVisible();
  await deniedPage.locator("#navigation-toggle").click(); await expect(deniedPage.locator("#navigation-panel")).toBeHidden();
  await deniedPage.evaluate(()=>document.querySelector("main").append(RadhouseIcons.appearanceControl()));
  await deniedPage.getByRole("switch",{name:"Icon animation",exact:true}).uncheck();
  await expect(deniedPage.locator("html")).toHaveAttribute("data-icon-animation","off");
  await expect(deniedPage.locator(".rh-appearance-note")).toContainText("storage is unavailable");
  await deniedStorage.close();
  expect(errors).toEqual([]);
  console.log("Shared navigation and admin integration browser checks passed.");
} finally { await closeBrowser(browser); }
