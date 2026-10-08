"use strict";
const $ = id => document.getElementById(id);
const infrastructure = location.pathname === "/infrastructure";
let session = null, generation = 0, controller;
const componentNames = {web: "Web app", assistant: "Assistant", documents: "Document reader", storage: "Storage"};
const statusNames = {healthy: "Healthy", unavailable: "Unavailable", unverified: "Unverified"};
function element(tag, text, className) {
  const node = document.createElement(tag); if (text !== undefined) { node.textContent = text; }
  if (className) { node.className = className; } return node;
}
function section(title, rows) {
  const node = element("section", undefined, "admin-section"), list = element("dl");
  node.append(element("h2", title));
  for (const [label, value] of rows) { list.append(element("dt", label), element("dd", value)); }
  node.append(list); return node;
}
function duration(seconds) {
  if (seconds % 86400 === 0) { return `${seconds / 86400} days`; }
  if (seconds % 3600 === 0) { return `${seconds / 3600} hours`; }
  return `${Math.round(seconds / 60)} minutes`;
}
function bytes(value) {
  if (value === null) { return "Unverified"; }
  if (value < 1024) { return `${value} B`; }
  if (value < 1024 * 1024) { return `${(value / 1024).toFixed(1)} KB`; }
  if (value < 1024 * 1024 * 1024) { return `${(value / 1024 / 1024).toFixed(1)} MB`; }
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}
function renderSettings(data) {
  $("content").append(
    section("Sign-in", [["Methods", "Password and authenticator code"],
      ["Idle session", duration(data.authentication.idle_timeout_seconds)],
      ["Session duration", duration(data.authentication.maximum_session_seconds)],
      ["Remembered browser", duration(data.authentication.remembered_session_seconds)]]),
    section("Files and messages", [["Upload size", data.files.upload_size_limit_bytes === null ? "No configured limit" : bytes(data.files.upload_size_limit_bytes)],
      ["Files per message", data.files.upload_count_limit === null ? "No configured limit" : String(data.files.upload_count_limit)],
      ["Original files", "Retained with your conversation"], ["Document formats", "Text, PDF, Word, Excel and PowerPoint"],
      ["Audio transcription", data.files.audio_transcription_enabled ? "Connected" : "Not connected"],
      ["Selective document reads", data.documents.selective_access_enabled ? "Enabled; check Infrastructure for current availability" : "Not connected"],
      ["Agent browser", data.browser?.enabled ? (data.browser.mode === "owner_session"
        ? "Open Browser to browse or take control" : "Enabled with a live view in Chat") : "Not connected"],
      ["Message text", `${data.messages.character_limit.toLocaleString()} characters`]]),
    element("p", "These are the current app settings. Settings are read only in this version.", "admin-note"));
}
function infrastructureComponent(component) {
  const node = element("section", undefined, "admin-section"), heading = element("div", undefined, "component-heading");
  const state = statusNames[component.state] ? component.state : "unverified";
  const badge = element("span", statusNames[state], "status"); badge.dataset.state = state;
  heading.append(element("h2", componentNames[component.id] || "Component"), badge);
  node.append(heading, element("p", component.detail, "component-detail"));
  if (component.id === "storage") {
    const list = element("dl");
    for (const [label, value] of [["Conversation database", bytes(component.database_bytes)], ["Available storage", bytes(component.free_bytes)], ["Schema", component.schema_version === null ? "Unverified" : String(component.schema_version)]]) { list.append(element("dt", label), element("dd", value)); }
    node.append(list);
  } else if (component.version) { node.append(element("p", `Version ${component.version}`, "versions")); }
  return node;
}
function renderInfrastructure(data) {
  for (const component of data.components) {
    $("content").append(infrastructureComponent(component));
  }
  const policy = data.browser_network_policy;
  if (policy) {
    $("content").append(section("Browser network", [["Policy evidence", policy.verified ? "Verified snapshot" : "Unverified"],
      ["Source", policy.source || "Unavailable"],
      ["Verified", policy.verified_at ? new Date(policy.verified_at).toLocaleString() : "Unavailable"],
      ["Permitted", policy.allowed.length ? policy.allowed.join("; ") : "No verified summary"],
      ["Blocked", policy.denied.length ? policy.denied.join("; ") : "No verified summary"]]),
      element("p", "Browsing follows the VM network policy. A reachable application still needs your permission before the agent changes it.", "admin-note"));
  }
  const build = section("Versions", [["Deployed source", data.versions.release_commit || "Unverified"],
    ["App package", data.versions.package || "Unverified"], ["Python", data.versions.python || "Unverified"]]);
  build.querySelector("dd").classList.add("release-id"); $("content").append(build);
}
function failureText(code) {
  if (code === "authentication_required") return "Sign in to open this page.";
  if (["management_access_required", "owner_access_required"].includes(code)) return "This account does not have access to this page.";
  return "This page could not be checked. Try refreshing.";
}
function failed(code) {
  if (code === "authentication_required") { session = null; $("logout").hidden = true; }
  window.RadhouseNavigation?.update(session);
  $("content").replaceChildren(); $("content").hidden = true; $("loading").hidden = true;
  $("checked-at").textContent = ""; $("notice").hidden = false;
  $("notice-text").textContent = failureText(code);
  $("refresh").hidden = ["authentication_required", "management_access_required", "owner_access_required"].includes(code);
}
async function request(path, signal, body) {
  const response = await fetch(path, {signal, method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : {"Content-Type": "application/json", "X-Radhouse-CSRF": session.csrf_token},
    body: body === undefined ? undefined : JSON.stringify(body)});
  let data; try { data = response.status === 204 ? null : await response.json(); } catch (_) { throw new Error("service_unavailable"); }
  if (!response.ok) { throw new Error(data?.error || "service_unavailable"); }
  return data;
}
async function load() {
  const current = ++generation; controller?.abort(); controller = new AbortController();
  const signal = controller.signal; $("refresh").disabled = true; $("notice").hidden = true;
  $("content").replaceChildren(); $("content").hidden = true; $("checked-at").textContent = "";
  $("loading").hidden = false; $("loading").textContent = "Checking current settings…";
  try {
    const next = await request("/auth/session", signal);
    if (current !== generation) { return; }
    session = next;
    window.RadhouseNavigation?.update(session);
    if (session.management?.read !== true) { throw new Error("management_access_required"); }
    $("logout").hidden = false;
    $("loading").textContent = infrastructure ? "Checking the instance…" : "Checking current settings…";
    const data = await request(infrastructure ? "/admin/infrastructure" : "/admin/settings", signal);
    if (current !== generation) { return; }
    infrastructure ? renderInfrastructure(data) : renderSettings(data);
    $("content").hidden = false; $("loading").hidden = true; $("refresh").hidden = false;
    $("checked-at").textContent = `Checked ${new Date(data.checked_at).toLocaleString()}`;
  } catch (error) { if (current === generation && error.name !== "AbortError") { failed(error.message); } }
  finally { if (current === generation) { $("refresh").disabled = false; } }
}
$("page-title").textContent = infrastructure ? "Infrastructure" : "Settings";
document.title = `${infrastructure ? "Infrastructure" : "Settings"} · Radhouse`;
$("page-intro").textContent = infrastructure ? "Current checks for this Radhouse instance." : "How this Radhouse instance is configured.";
$(infrastructure ? "infrastructure-link" : "settings-link").setAttribute("aria-current", "page");
$("refresh").addEventListener("click", load);
$("logout").addEventListener("click", async () => {
  ++generation; controller?.abort(); $("content").replaceChildren(); $("content").hidden = true;
  $("checked-at").textContent = ""; $("logout").disabled = true;
  try { await request("/auth/logout", undefined, {}); location.assign("/"); }
  catch (error) { failed(error.message); $("logout").disabled = false; }
});
load();
