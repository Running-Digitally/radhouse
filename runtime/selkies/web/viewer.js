const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.replace(/^#/, "").replace(/^phone&/, ""));
const suppliedToken = fragment.get("token");
let token = suppliedToken || sessionStorage.getItem("radhouse-trial-viewer"), current = null, busy = false, streamToken = null;
let phone = location.hash.startsWith("#phone");
document.body.classList.toggle("phone", phone);
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
      : "The browser action could not be confirmed. Check the page before continuing.");
  }
  return response.json();
}

function render(value) {
  current = value;
  phone = value.viewing_only === true;
  document.body.classList.toggle("phone", phone);
  $("touch-layer").hidden = !phone;
  $("take").hidden = phone || !value.can_take;
  $("return").hidden = phone || !value.controlling;
  $("agent").disabled = busy || value.mode !== "agent";
  $("owner").textContent = value.controlling ? "You have control" : ({
    agent: "Agent has control", takeover_pending: "Handing over…", human: "Desktop has control",
    paused: "Browser paused", recovering: "Check the page", retired: "Browser closed",
  }[value.mode] || "Connecting…");
  $("hint").textContent = phone ? "Viewing only. Zoom and scroll here to read the screen."
    : "Click a page field to type after taking control. Click the draft to return keyboard focus to chat.";
  if (value.boundary_blocked) $("notice").textContent = "The input boundary needs diagnosis. Agent input remains paused.";
  if (streamToken !== value.stream_token) {
    streamToken = value.stream_token;
    // A fragment-only change does not reload the core or its authentication.
    // The public nonce forces a new document; the credential stays in the hash.
    $("stream").src = "/stream/index.html?connection=" + crypto.randomUUID()
      + "#token=" + encodeURIComponent(streamToken);
    $("connection").textContent = "Connecting stream…";
  }
}

async function act(work) {
  if (busy) return;
  busy = true;
  for (const id of ["take", "return", "agent"]) $(id).disabled = true;
  $("notice").textContent = "";
  try { render(await work()); }
  catch (error) { $("notice").textContent = error.message; }
  finally {
    busy = false;
    for (const id of ["take", "return"]) $(id).disabled = false;
    if (current) $("agent").disabled = current.mode !== "agent";
  }
}

$("take").addEventListener("click", () => act(() => api("take", {
  revision: current.revision, request_id: crypto.randomUUID(),
})));
$("return").addEventListener("click", () => act(() => api("return", {
  revision: current.revision, lease_id: current.lease_id,
})));
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
  if (event.data?.type === "framePresented") $("connection").textContent = "Live browser";
  if (event.data?.type === "pipelineStatusUpdate") $("connection").textContent = event.data.video ? "Live browser" : "Stream paused";
});

if (!token) $("notice").textContent = "Open the private desktop or phone trial link.";
else {
  try {
    if (suppliedToken) {
      const session = await api("session", {});
      token = session.token;
      sessionStorage.setItem("radhouse-trial-viewer", token);
      render(session.state);
    } else render(await api("state"));
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
