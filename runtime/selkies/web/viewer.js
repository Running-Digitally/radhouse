const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.replace(/^#/, "").replace(/^phone&/, ""));
const suppliedToken = fragment.get("token");
let token = suppliedToken || sessionStorage.getItem("radhouse-trial-viewer"), current = null, busy = false, streamToken = null;
let viewingOnly = false;
let inputStatus = {ready: false, touch: false, hardware: false};
let localTouch = matchMedia("(pointer: coarse)").matches;
const compact = matchMedia("(max-width: 850px)");
function layout() {
  document.body.classList.toggle("compact", compact.matches || localTouch);
  const available = window.visualViewport?.height || window.innerHeight;
  document.documentElement.style.setProperty("--available-height", available + "px");
  const top = Math.max(0, $("viewport").getBoundingClientRect().top - (window.visualViewport?.offsetTop || 0));
  document.documentElement.style.setProperty("--browser-height", Math.max(150, available - top - 46) + "px");
}
function mobileControls() {
  const touch = localTouch || inputStatus.touch;
  const canInput = !!current?.controlling && !viewingOnly;
  $("keyboard").hidden = !canInput || !touch || inputStatus.hardware;
  $("input-tools").hidden = !canInput || !touch;
  for (const button of [$("keyboard"), ...$("input-tools").querySelectorAll("button")]) button.disabled = busy || !inputStatus.ready;
  if (!canInput) $("input-tools").open = false;
  layout();
}
function hideKeyboard() { $("stream").contentWindow?.radhouseInput?.hide(); }
function inputAction(method, argument) {
  if (busy || !current?.controlling || viewingOnly) return;
  if (!$("stream").contentWindow?.radhouseInput?.[method](argument)) {
    $("notice").textContent = "Wait for the live browser input to connect, then try again.";
  }
}
compact.addEventListener("change", layout);
window.visualViewport?.addEventListener("resize", layout);
window.addEventListener("resize", layout);
window.addEventListener("touchstart", () => { localTouch = true; layout(); mobileControls(); }, {passive: true});
document.addEventListener("visibilitychange", () => { if (document.hidden) hideKeyboard(); });
layout();
history.replaceState(null, "", location.pathname);

async function api(path, body) {
  const response = await fetch("/qualification/" + path, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: {Authorization: "Bearer " + token, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const value = await response.json();
    throw new Error(value.error === "sensitive_fields_present"
      ? "Finish sign-in or clear the password and code fields before returning control."
      : value.error === "page_check_unconfirmed"
        ? "The page could not be checked. Reload a failed tab or close extra browser windows, then try again."
        : "The browser action could not be confirmed. Check the page before continuing.");
  }
  return response.json();
}

function render(value) {
  if (current?.controlling && !value.controlling) hideKeyboard();
  current = value;
  viewingOnly = value.viewing_only === true;
  document.body.classList.toggle("viewing-only", viewingOnly);
  $("touch-layer").hidden = !viewingOnly;
  $("take").hidden = viewingOnly || !value.can_take;
  $("return").hidden = viewingOnly || !value.controlling;
  $("agent").disabled = busy || value.mode !== "agent";
  $("owner").textContent = value.controlling ? "You have control" : ({
    agent: "Agent has control", takeover_pending: "Handing over…", human: "Another viewer has control",
    paused: "Browser paused", recovering: "Check the page", retired: "Browser closed",
  }[value.mode] || "Connecting…");
  $("browsing-mode").textContent = value.public_web ? "Public web · sandbox enabled" : "Sandboxed exercise pages";
  $("instructions").textContent = value.public_web
    ? "Take control and use Chrome’s address bar to browse websites. Try typing, selection, paste and scrolling, then return control for a page observation."
    : "Edit the exercise form, try selection and paste, then return control.";
  $("hint").textContent = viewingOnly ? "Viewing only. Zoom and scroll here to read the screen."
    : (localTouch || inputStatus.touch) ? "Take control, tap a page field, then Keyboard to type. Keys includes the address bar and Tab."
    : "Click a page field to type after taking control. Click the draft to return keyboard focus to chat.";
  if (value.boundary_blocked) $("notice").textContent = "The input boundary needs diagnosis. Agent input remains paused.";
  if (streamToken !== value.stream_token) {
    hideKeyboard();
    inputStatus = {ready: false, touch: false, hardware: false};
    streamToken = value.stream_token;
    // A fragment-only change does not reload the core or its authentication.
    // The public nonce forces a new document; the credential stays in the hash.
    $("stream").src = "/stream/index.html?connection=" + crypto.randomUUID()
      + "#token=" + encodeURIComponent(streamToken);
    $("connection").textContent = "Connecting stream…";
  }
  mobileControls();
}

async function act(work) {
  if (busy) return;
  busy = true;
  mobileControls();
  for (const id of ["take", "return", "agent"]) $(id).disabled = true;
  $("notice").textContent = "";
  try { render(await work()); }
  catch (error) { $("notice").textContent = error.message; }
  finally {
    busy = false;
    mobileControls();
    for (const id of ["take", "return"]) $(id).disabled = false;
    if (current) $("agent").disabled = current.mode !== "agent";
  }
}

$("take").addEventListener("click", () => act(() => api("take", {
  revision: current.revision, request_id: crypto.randomUUID(),
})));
$("return").addEventListener("click", () => {
  hideKeyboard();
  act(() => api("return", {revision: current.revision, lease_id: current.lease_id}));
});
$("keyboard").addEventListener("click", () => inputAction("show", false));
$("keyboard-override").addEventListener("click", () => inputAction("show", true));
$("keyboard-hide").addEventListener("click", hideKeyboard);
$("draft").addEventListener("focus", hideKeyboard);
for (const button of document.querySelectorAll("[data-key]")) button.addEventListener("click", () => inputAction("press", button.dataset.key));
$("agent").addEventListener("click", () => act(async () => {
  const result = await api("agent", {tool: "browser_snapshot", arguments: {}});
  $("observation").textContent = result.result.data?.snapshot || "Page observation completed.";
  return result.state;
}));
$("fit").addEventListener("click", () => $("viewport").classList.remove("zoomed"));
$("zoom").addEventListener("click", () => $("viewport").classList.add("zoomed"));
$("expand").addEventListener("click", () => {
  const expanded = document.body.classList.toggle("expanded");
  $("expand").textContent = expanded ? "Collapse" : "Expand";
});
window.addEventListener("message", event => {
  if (event.origin !== location.origin || event.source !== $("stream").contentWindow) return;
  if (event.data?.type === "mobileInputStatus" && ["ready", "touch", "hardware", "focused"].every(key => typeof event.data[key] === "boolean")) {
    inputStatus = {ready: event.data.ready, touch: event.data.touch, hardware: event.data.hardware};
    mobileControls();
  }
  if (event.data?.type === "framePresented") $("connection").textContent = "Live browser";
  if (event.data?.type === "pipelineStatusUpdate") $("connection").textContent = event.data.video ? "Live browser" : "Stream paused";
});

if (!token) $("notice").textContent = "Open the private browser launch link.";
else {
  try {
    // A reload or duplicated tab receives its own owner binding. A copied
    // sessionStorage credential must not clone another tab's input lease.
    const session = await api("session", {});
    token = session.token;
    sessionStorage.setItem("radhouse-trial-viewer", token);
    render(session.state);
  } catch (error) { $("notice").textContent = error.message; }
}
setInterval(async () => {
  if (!token || busy || document.hidden) return;
  try { render(await api("state")); }
  catch { $("connection").textContent = "Connection unavailable"; }
}, 1000);
setInterval(async () => {
  if (!current?.controlling || busy || document.hidden) return;
  try { render(await api("heartbeat", {revision: current.revision, lease_id: current.lease_id})); }
  catch { $("notice").textContent = "Control could not be renewed. Input will pause when the lease expires."; }
}, 15000);
