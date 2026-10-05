"use strict";
const $ = (id) => document.getElementById(id);
const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);
const explanations = {
  authentication_required: "Please sign in to continue.", login_denied: "Check your username, password and authenticator code.",
  invalid_credentials: "Check your username, password and authenticator code.",
  authentication_unavailable: "Sign-in is temporarily unavailable. Try again shortly.",
  identity_binding_denied: "Your account’s conversation access needs to be checked.",
  work_home_unavailable: "Your account’s conversation access needs to be checked.",
  assistant_unavailable: "Your assistant is unavailable. Your conversation is saved; try again shortly.",
  conversation_unavailable: "Your saved conversation is temporarily unavailable. Try again shortly.",
  reply_pending: "Wait for this reply before sending another message.",
  reply_dispatch_uncertain: "The connection was lost while sending. Retry this message to check whether it was received.",
  reply_recovery_required: "We couldn’t confirm this reply in time. It is saved and needs recovery before you continue.",
  reply_status_unavailable: "The reply is still saved. We couldn’t check its progress just now.",
  chat_capability_unavailable: "Your assistant isn’t ready for chat yet. Try again after its connection is checked.",
  unexpected_runtime_approval: "The assistant needs a capability this conversation doesn’t support. Your message is saved.",
  reply_failed: "Your assistant couldn’t finish this reply. You can send another message.",
  reply_cancelled: "This reply was cancelled. You can send another message.",
  reply_interrupted: "This reply was interrupted. You can send another message.",
  empty_reply: "Your assistant finished without a response. You can send another message.",
  request_origin_denied: "Refresh this page and try again.", csrf_denied: "Refresh this page and try again.",
  owner_access_required: "This account doesn’t have access to this conversation.",
  invalid_request: "Check the fields and try again.", network_error: "We lost the connection. Retry the saved message to check whether it was received.",
  empty_message: "Write a message before sending.",
  message_conflict: "This saved message has already been received with different text. Refresh to recover the conversation.",
};
let session = null, turns = new Map(), olderBefore = null, olderLoaded = false, busy = false, polling = false;
let draft = {text: "", request_id: null};
let noticeCode = null;
function tell(code) { noticeCode = code; $("notice").textContent = explanations[code] || "Something went wrong. Refresh the page and try again."; $("notice").hidden = false; }
function clearNotice() { noticeCode = null; $("notice").hidden = true; }
function draftKey() { return "radhouse-chat-draft:" + session.username; }
function saveDraft() { if (session) { draft.text = $("message").value; try { localStorage.setItem(draftKey(), JSON.stringify(draft)); } catch (_) {} } }
function clearDraft() { draft = {text: "", request_id: null}; $("message").value = ""; saveDraft(); }
function showLogin() {
  session = null; draft = {text: "", request_id: null}; turns.clear(); $("messages").replaceChildren(); $("message").value = "";
  $("chat-view").hidden = true; $("logout").hidden = true; $("login-view").hidden = false; $("loading").hidden = true;
}
async function api(path, body) {
  const headers = {};
  if (body !== undefined) { headers["Content-Type"] = "application/json"; if (session) headers["X-Radhouse-CSRF"] = session.csrf_token; }
  let response;
  try { response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body)}); }
  catch (_) { throw new Error("network_error"); }
  if (!response.ok) {
    let value; try { value = await response.json(); } catch (_) { value = {}; }
    if (response.status === 401) showLogin();
    throw new Error(value.error || "service_unavailable");
  }
  return response.status === 204 ? null : response.json();
}
function accept(data, older = false) {
  for (const turn of data.turns) { turns.set(turn.seq, turn); if (draft.request_id === turn.request_id) clearDraft(); }
  if (older || !olderLoaded) olderBefore = data.older_before;
  if (older) olderLoaded = true;
  if (!pendingTurn() && !draft.request_id && ["network_error", "assistant_unavailable"].includes(noticeCode)) clearNotice();
  render();
}
function pendingTurn() { return [...turns.values()].find(turn => !terminal.has(turn.status)); }
function render() {
  const fragment = document.createDocumentFragment();
  for (const turn of [...turns.values()].sort((a, b) => a.seq - b.seq)) {
    const block = document.createElement("article"); block.className = "turn";
    const label = document.createElement("p"); label.className = "message-label"; label.textContent = "You";
    const text = document.createElement("p"); text.className = "message-text"; text.textContent = turn.text;
    block.append(label, text);
    if (turn.output) {
      const reply = document.createElement("div"); reply.className = "assistant";
      const name = document.createElement("p"); name.className = "message-label"; name.textContent = "Radhouse";
      const answer = document.createElement("p"); answer.className = "message-text"; answer.textContent = turn.output;
      reply.append(name, answer); block.append(reply);
    } else {
      const status = document.createElement("p"); status.className = turn.error ? "turn-error" : "pending";
      status.textContent = turn.error ? (explanations[turn.error] || "This reply needs attention.") : "Your assistant is replying…";
      block.append(status);
      if (turn.status === "awaiting_dispatch" && turn.error !== "reply_recovery_required") {
        const retry = document.createElement("button"); retry.className = "retry"; retry.textContent = "Retry this message"; retry.disabled = busy;
        retry.addEventListener("click", () => submit(turn.request_id, turn.text)); block.append(retry);
      }
    }
    fragment.append(block);
  }
  $("messages").replaceChildren(fragment); $("empty").hidden = turns.size > 0; $("older").hidden = !olderBefore;
  const pending = pendingTurn(); $("send").disabled = busy || !!pending; $("message").disabled = !!pending || !!draft.request_id;
  $("send").textContent = draft.request_id ? "Retry message" : "Send ↗";
  $("reply-status").textContent = pending ? "Your conversation is saved. You can leave and return." : "Ready when you are.";
}
async function openConversation() {
  turns.clear(); olderLoaded = false; olderBefore = null;
  $("login-view").hidden = true; $("chat-view").hidden = false; $("logout").hidden = false; $("loading").hidden = true;
  try { const saved = JSON.parse(localStorage.getItem(draftKey()) || "null"); if (saved && typeof saved.text === "string" && saved.text.length <= 16000) draft = {text: saved.text, request_id: /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(saved.request_id || "") ? saved.request_id : null}; } catch (_) {}
  $("message").value = draft.text;
  accept(await api("/chat/history"));
}
async function submit(requestId, text) {
  if (busy || !session) return;
  const sendingSession = session;
  if (!pendingTurn()) { draft.request_id = requestId; draft.text = text; saveDraft(); }
  busy = true; clearNotice(); render();
  try {
    const data = await api("/chat/messages", {request_id: requestId, text});
    if (session === sendingSession) { clearDraft(); accept(data); }
  } catch (error) {
    tell(error.message);
    if (session === sendingSession) { try { const data = await api("/chat/history"); if (session === sendingSession) accept(data); } catch (_) {} }
  } finally { busy = false; if (session) render(); }
}
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearNotice(); const button = event.submitter; button.disabled = true;
  try {
    session = await api("/auth/login", {username: $("username").value, password: $("password").value, totp_code: $("totp").value, remember_browser: $("remember").checked});
    $("password").value = ""; $("totp").value = ""; await openConversation();
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
});
$("compose").addEventListener("submit", event => { event.preventDefault(); if (!$("message").value.trim()) { tell("empty_message"); return; } if (!pendingTurn()) submit(draft.request_id || crypto.randomUUID(), $("message").value); });
$("message").addEventListener("input", saveDraft);
$("message").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$("send").disabled && $("message").value.trim()) $("compose").requestSubmit(); } });
$("older").addEventListener("click", async () => { const readingSession = session; try { const data = await api("/chat/history?before=" + olderBefore); if (session === readingSession) accept(data, true); } catch (error) { tell(error.message); } });
$("logout").addEventListener("click", async () => { try { await api("/auth/logout", {}); showLogin(); clearNotice(); } catch (error) { tell(error.message); } });
setInterval(async () => {
  if (!session || !pendingTurn() || busy || polling) return;
  polling = true; const readingSession = session;
  try { const data = await api("/chat/reply"); if (session === readingSession) accept(data); }
  catch (error) { tell(error.message); } finally { polling = false; }
}, 2000);
(async () => {
  try { session = await api("/auth/session"); await openConversation(); }
  catch (error) { if (error.message === "authentication_required") showLogin(); else { $("loading").hidden = true; tell(error.message); } }
})();
