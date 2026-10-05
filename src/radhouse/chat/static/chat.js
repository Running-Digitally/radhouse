"use strict";
const $ = (id) => document.getElementById(id);
const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);
const explanations = {
  authentication_required: "Please sign in to continue.", login_denied: "Check your username, password and authenticator code.",
  invalid_credentials: "Check your username, password and authenticator code.",
  authentication_unavailable: "Sign-in is temporarily unavailable. Try again shortly.",
  identity_binding_denied: "Your account’s conversation access needs to be checked.", work_home_unavailable: "Your account’s conversation access needs to be checked.",
  assistant_unavailable: "Your assistant is unavailable. Your conversation is saved; try again shortly.",
  conversation_unavailable: "Your saved conversation is temporarily unavailable. Try again shortly.",
  reply_pending: "Wait for this reply before sending another message.",
  reply_dispatch_uncertain: "The connection was lost while sending. Retry this message to check whether it was received.",
  reply_recovery_required: "We couldn’t confirm this reply in time. It is saved and needs recovery before you continue.",
  reply_status_unavailable: "The reply is still saved. We couldn’t check its progress just now.",
  chat_capability_unavailable: "Your assistant isn’t ready for chat yet. Try again after its connection is checked.",
  unexpected_runtime_approval: "The assistant needs a capability this conversation doesn’t support. Your message is saved.",
  reply_failed: "Your assistant couldn’t finish this reply. You can send another message.", reply_cancelled: "This reply was cancelled. You can send another message.",
  reply_interrupted: "This reply was interrupted. You can send another message.", empty_reply: "Your assistant finished without a response. You can send another message.",
  request_origin_denied: "Refresh this page and try again.", csrf_denied: "Refresh this page and try again.", owner_access_required: "This account doesn’t have access to this conversation.",
  invalid_request: "Check the fields and try again.", network_error: "We lost the connection. Retry the saved message to check whether it was received.",
  empty_message: "Write a message or attach a file before sending.", message_conflict: "This message was already received with different content. Refresh to recover the conversation.",
  attachments_too_many: "Attach up to 4 files per message.", attachment_too_large: "Images can be up to 4 MB each; documents and audio up to 20 MB each.",
  attachments_too_large: "Use up to 24 MB per message, including at most 8 MB of images.", attachment_empty: "This file is empty. Choose another file.",
  attachment_invalid: "This file’s name or content couldn’t be read. Choose another file.",
  attachment_unsupported: "Use PNG, JPEG, WebP, text/code, PDF, DOCX, XLSX, PPTX, WAV, MP3, M4A, OGG, FLAC or WebM files.",
  attachment_text_too_large: "There’s too much document text for one message. Split it into smaller files.",
  document_unreadable: "This document couldn’t be read. Try exporting it as text or a searchable PDF.", document_encrypted: "Use a copy without password protection.",
  document_too_complex: "This document is too large or complex to read. Try a smaller export.", document_needs_ocr: "This PDF has no readable text. Attach its pages as images or use a searchable PDF.",
  audio_transcription_not_configured: "Audio transcription hasn’t been connected yet. Your file is still in the draft.",
  audio_transcription_unavailable: "We couldn’t transcribe the audio just now. Your file is saved; retry this message.",
  audio_no_speech: "No readable speech was found in this audio. You can try another file.",
  draft_storage_unavailable: "Your browser couldn’t save this file draft. Free some browser storage and try again.",
};
let session = null, turns = new Map(), olderBefore = null, olderLoaded = false, busy = false, polling = false, filesLoading = false;
const emptyDraft = () => ({text:"", request_id:null, attachments:[]});
let draft = emptyDraft(), noticeCode = null, renderedHistory = "";
const previewUrls = new Map();
function tell(code) { noticeCode = code; $("notice").textContent = explanations[code] || "Something went wrong. Refresh the page and try again."; $("notice").hidden = false; }
function clearNotice() { noticeCode = null; $("notice").hidden = true; }
function draftKey() { return "radhouse-chat-draft:" + session.username; }
// IndexedDB can retain binary-sized drafts beyond localStorage's small quota.
let draftDatabase;
function database() {
  if (!draftDatabase) draftDatabase = new Promise((resolve,reject) => {
    const request = indexedDB.open("radhouse-chat-drafts",1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts");
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(new Error("draft_storage_unavailable"));
  });
  return draftDatabase;
}
async function draftOperation(key, value) {
  const db = await database();
  return new Promise((resolve,reject) => {
    const transaction = db.transaction("drafts",value === undefined ? "readonly" : "readwrite");
    const store = transaction.objectStore("drafts"), request = value === undefined ? store.get(key) : store.put(value,key);
    transaction.oncomplete = () => resolve(request.result);
    transaction.onerror = transaction.onabort = () => reject(new Error("draft_storage_unavailable"));
  });
}
let draftWrites = Promise.resolve();
function saveDraft() {
  if (!session) return Promise.resolve();
  draft.text = $("message").value;
  const key = draftKey(), saved = structuredClone(draft);
  // Keep a small text-only recovery record for older browsers and old drafts.
  let fallbackSaved = false;
  try { localStorage.setItem(key,JSON.stringify({text:saved.text,request_id:saved.request_id,has_files:!!saved.attachments.length})); fallbackSaved = true; } catch (_) {}
  draftWrites = draftWrites.catch(() => {}).then(() => draftOperation(key,saved)).catch(error => {
    if (saved.attachments.length || !fallbackSaved) throw error;
  });
  return draftWrites;
}
function releasePreviews() { for (const url of previewUrls.values()) URL.revokeObjectURL(url); previewUrls.clear(); }
function clearDraft() { releasePreviews(); draft = emptyDraft(); $("message").value = ""; saveDraft().catch(() => tell("draft_storage_unavailable")); }
function showLogin() {
  session = null; releasePreviews(); draft = emptyDraft(); turns.clear(); renderedHistory = "";
  $("messages").replaceChildren(); $("draft-files").replaceChildren(); $("message").value = "";
  $("chat-view").hidden = true; $("logout").hidden = true; $("login-view").hidden = false; $("loading").hidden = true;
}
async function api(path, body) {
  const headers = {};
  if (body !== undefined) { headers["Content-Type"] = "application/json"; if (session) headers["X-Radhouse-CSRF"] = session.csrf_token; }
  let response;
  try { response = await fetch(path,{method:body === undefined ? "GET" : "POST",headers,body:body === undefined ? undefined : JSON.stringify(body)}); }
  catch (_) { throw new Error("network_error"); }
  if (!response.ok) {
    let value; try { value = await response.json(); } catch (_) { value = {}; }
    if (response.status === 401) showLogin();
    const error = new Error(value.error || "service_unavailable"); error.status = response.status; throw error;
  }
  return response.status === 204 ? null : response.json();
}
function accept(data, older = false) {
  for (const turn of data.turns) { turns.set(turn.seq,turn); if (draft.request_id === turn.request_id) clearDraft(); }
  if (older || !olderLoaded) olderBefore = data.older_before;
  if (older) olderLoaded = true;
  if (!pendingTurn() && !draft.request_id && ["network_error","assistant_unavailable"].includes(noticeCode)) clearNotice();
  render();
}
function pendingTurn() { return [...turns.values()].find(turn => !terminal.has(turn.status)); }
function fileKind(file) {
  const extension = file.name.split(".").pop().toLowerCase();
  return ["png","jpg","jpeg","webp"].includes(extension) || ["image/png","image/jpeg","image/webp"].includes(file.type) ? "image" :
    ["wav","mp3","m4a","ogg","flac","webm"].includes(extension) ? "audio" : "document";
}
function sizeLabel(bytes) { return bytes < 1024 * 1024 ? Math.max(1,Math.round(bytes/1024)) + " KB" : (bytes/1024/1024).toFixed(1) + " MB"; }
function previewUrl(file) {
  if (!previewUrls.has(file)) {
    const bytes = Uint8Array.from(atob(file.content), c => c.charCodeAt(0));
    previewUrls.set(file,URL.createObjectURL(new Blob([bytes],{type:file.type})));
  }
  return previewUrls.get(file);
}
const documentTypes = {
  pdf: {icon:"pdf", label:"PDF", description:"PDF document"},
  docx: {icon:"word", label:"Word", description:"Word document"},
  xlsx: {icon:"excel", label:"Excel", description:"Excel workbook"},
  pptx: {icon:"powerpoint", label:"PowerPoint", description:"PowerPoint presentation"},
};
function fileCard(file, url, removable) {
  const card = document.createElement("div"); card.className = "attachment";
  const extension = file.name.split(".").pop().toLowerCase();
  const documentType = file.kind === "document" && Object.hasOwn(documentTypes,extension) ? documentTypes[extension] : null;
  if (file.kind === "image") { const img = document.createElement("img"); img.src = url; img.alt = file.name; card.append(img); }
  else if (documentType) {
    const tile = document.createElement("div"); tile.className = "document-thumbnail";
    const icon = document.createElement("img"); icon.className = "document-icon";
    icon.src = "/icons/" + documentType.icon + ".svg"; icon.alt = documentType.description;
    tile.append(icon); card.append(tile);
  }
  const label = document.createElement(removable ? "span" : "a"); label.className = "file-name"; label.textContent = file.name;
  if (!removable) { label.href = url + "?download=true"; label.setAttribute("download",file.name); }
  card.append(label);
  const detail = document.createElement("span"); detail.className = "file-detail"; detail.textContent = (documentType ? documentType.label : file.kind) + " · " + sizeLabel(file.size); card.append(detail);
  if (file.kind === "audio") { const audio = document.createElement("audio"); audio.controls = true; audio.preload = "none"; audio.src = url; audio.setAttribute("aria-label",file.name); card.append(audio); }
  if (file.transcript) { const transcript = document.createElement("details"), summary = document.createElement("summary"), text = document.createElement("p"); summary.textContent = "Audio transcript"; text.textContent = file.transcript; transcript.append(summary,text); card.append(transcript); }
  if (removable) {
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "remove-file"; remove.textContent = "×"; remove.setAttribute("aria-label","Remove " + file.name);
    remove.disabled = busy || filesLoading || !!draft.request_id;
    remove.addEventListener("click",() => { const url = previewUrls.get(file); if (url) URL.revokeObjectURL(url); previewUrls.delete(file); draft.attachments = draft.attachments.filter(a => a !== file); saveDraft().catch(() => tell("draft_storage_unavailable")); render(); }); card.append(remove);
  }
  return card;
}
function render() {
  const ordered = [...turns.values()].sort((a,b) => a.seq-b.seq), signature = JSON.stringify(ordered);
  if (signature !== renderedHistory) {
    const fragment = document.createDocumentFragment();
    for (const turn of ordered) {
      const block = document.createElement("article"); block.className = "turn";
      const label = document.createElement("p"); label.className = "message-label"; label.textContent = "You";
      const text = document.createElement("p"); text.className = "message-text"; text.textContent = turn.text; block.append(label,text);
      const files = document.createElement("div"); files.className = "attachments";
      for (const file of turn.attachments || []) files.append(fileCard(file,"/chat/messages/" + turn.request_id + "/attachments/" + file.position,false));
      if (files.childNodes.length) block.append(files);
      if (turn.output) {
        const reply = document.createElement("div"); reply.className = "assistant";
        const name = document.createElement("p"); name.className = "message-label"; name.textContent = "Radhouse";
        const answer = document.createElement("p"); answer.className = "message-text"; answer.textContent = turn.output; reply.append(name,answer); block.append(reply);
      } else {
        const status = document.createElement("p"); status.className = turn.error ? "turn-error" : "pending";
        status.textContent = turn.error ? (explanations[turn.error] || "This reply needs attention.") : turn.status === "awaiting_dispatch" && (turn.attachments || []).some(a => a.kind === "audio" && !a.transcript) ? "Preparing your audio transcript…" : "Your assistant is replying…"; block.append(status);
        if (turn.status === "awaiting_dispatch" && turn.error !== "reply_recovery_required") {
          const retry = document.createElement("button"); retry.className = "retry"; retry.textContent = "Retry this message";
          retry.addEventListener("click",() => submit(turn.request_id,null)); block.append(retry);
        }
      }
      fragment.append(block);
    }
    $("messages").replaceChildren(fragment); renderedHistory = signature;
  }
  document.querySelectorAll(".retry").forEach(button => { button.disabled = busy; });
  $("draft-files").replaceChildren(...draft.attachments.map(file => fileCard(file,previewUrl(file),true)));
  $("empty").hidden = turns.size > 0; $("older").hidden = !olderBefore;
  const pending = pendingTurn(), locked = busy || filesLoading || !!pending || !!draft.request_id;
  $("send").disabled = busy || filesLoading || !!pending; $("message").disabled = locked; $("attach").disabled = locked;
  $("send").textContent = draft.request_id ? "Retry message" : "Send ↗";
  $("reply-status").textContent = filesLoading ? "Adding files…" : busy && draft.attachments.some(a => a.kind === "audio") ? "Transcribing audio and sending…" : pending ? "Your conversation is saved. You can leave and return." : "Ready when you are.";
}
async function openConversation() {
  const openingSession = session;
  turns.clear(); renderedHistory = ""; olderLoaded = false; olderBefore = null; draft = emptyDraft();
  $("login-view").hidden = true; $("chat-view").hidden = false; $("logout").hidden = false; $("loading").hidden = true;
  let saved;
  try { saved = await draftOperation(draftKey()); } catch (_) {}
  if (!saved) { try { saved = JSON.parse(localStorage.getItem(draftKey()) || "null"); if (saved?.has_files) tell("draft_storage_unavailable"); } catch (_) {} }
  if (session !== openingSession) return;
  if (saved && typeof saved.text === "string" && saved.text.length <= 16000) {
    draft = {text:saved.text,request_id:/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(saved.request_id || "") ? saved.request_id : null,
      attachments:Array.isArray(saved.attachments) ? saved.attachments : []};
  }
  $("message").value = draft.text; render();
  const data = await api("/chat/history"); if (session === openingSession) accept(data);
}
async function submit(requestId, text) {
  if (busy || !session) return;
  const sendingSession = session, isRetry = text === null;
  busy = true; clearNotice(); let transmitted = false;
  try {
    if (!isRetry) { draft.request_id = requestId; draft.text = text; render(); await saveDraft(); }
    if (session !== sendingSession) return;
    render(); transmitted = true;
    const data = isRetry ? await api("/chat/messages/" + requestId + "/retry",{}) :
      await api("/chat/messages",{request_id:requestId,text,attachments:draft.attachments.map(a => ({name:a.name,content:a.content}))});
    if (session === sendingSession) { if (!isRetry) clearDraft(); accept(data); }
  } catch (error) {
    if (session === sendingSession) {
      // Definite validation rejection allows correcting the unsent draft.
      if (!isRetry && (!transmitted || [413,422].includes(error.status))) { draft.request_id = null; saveDraft().catch(() => {}); }
      tell(error.message);
      try { const data = await api("/chat/history"); if (session === sendingSession) accept(data); } catch (_) {}
    }
  } finally { busy = false; if (session === sendingSession) render(); }
}
async function addFiles(fileList) {
  if (!session || busy || filesLoading || pendingTurn() || draft.request_id) return;
  const addingSession = session; filesLoading = true; clearNotice(); render();
  try {
    const files = [...fileList];
    if (draft.attachments.length + files.length > 4) throw new Error("attachments_too_many");
    const next = [];
    for (const file of files) {
      const kind = fileKind(file);
      if (!file.size) throw new Error("attachment_empty");
      if (file.size > (kind === "image" ? 4 : 20) * 1024 * 1024) throw new Error("attachment_too_large");
      const content = await new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]); reader.onerror = () => reject(new Error("attachment_invalid")); reader.readAsDataURL(file); });
      next.push({name:file.name,content,kind,type:file.type || (kind === "image" ? "image/" + file.name.split(".").pop().replace("jpg","jpeg") : "application/octet-stream"),size:file.size});
    }
    const all = [...draft.attachments,...next];
    if (all.reduce((n,a) => n+a.size,0) > 24*1024*1024 || all.filter(a => a.kind === "image").reduce((n,a) => n+a.size,0) > 8*1024*1024) throw new Error("attachments_too_large");
    if (session !== addingSession) return;
    draft.attachments = all; await saveDraft();
  } catch (error) { if (session === addingSession) tell(error.message); }
  finally { filesLoading = false; if (session === addingSession) render(); }
}
$("attach").addEventListener("click",() => $("file-picker").click());
$("file-picker").addEventListener("change",event => { addFiles(event.target.files); event.target.value = ""; });
$("compose").addEventListener("paste",event => {
  const files = [...(event.clipboardData?.files || [])];
  if (files.length) { event.preventDefault(); addFiles(files); }
});
$("compose").addEventListener("dragover",event => { if ([...event.dataTransfer.types].includes("Files")) { event.preventDefault(); $("compose").classList.add("dragging"); } });
$("compose").addEventListener("dragleave",event => { if (!$("compose").contains(event.relatedTarget)) $("compose").classList.remove("dragging"); });
$("compose").addEventListener("drop",event => { event.preventDefault(); $("compose").classList.remove("dragging"); addFiles(event.dataTransfer.files); });
$("login-form").addEventListener("submit",async event => {
  event.preventDefault(); clearNotice(); const button = event.submitter; button.disabled = true;
  try {
    session = await api("/auth/login",{username:$("username").value,password:$("password").value,totp_code:$("totp").value,remember_browser:$("remember").checked});
    $("password").value = ""; $("totp").value = ""; await openConversation();
  } catch (error) { tell(error.message); } finally { button.disabled = false; }
});
$("compose").addEventListener("submit",event => { event.preventDefault(); if (!$("message").value.trim() && !draft.attachments.length) { tell("empty_message"); return; } if (!pendingTurn()) submit(draft.request_id || crypto.randomUUID(),$("message").value); });
$("message").addEventListener("input",() => { saveDraft().catch(() => tell("draft_storage_unavailable")); });
$("message").addEventListener("keydown",event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$("send").disabled && ($("message").value.trim() || draft.attachments.length)) $("compose").requestSubmit(); } });
$("older").addEventListener("click",async () => { const readingSession = session; try { const data = await api("/chat/history?before=" + olderBefore); if (session === readingSession) accept(data,true); } catch (error) { tell(error.message); } });
$("logout").addEventListener("click",async () => { try { await api("/auth/logout",{}); showLogin(); clearNotice(); } catch (error) { tell(error.message); } });
setInterval(async () => {
  if (!session || !pendingTurn() || busy || polling) return;
  polling = true; const readingSession = session;
  try { const data = await api("/chat/reply"); if (session === readingSession) accept(data); } catch (error) { if (session === readingSession) tell(error.message); } finally { polling = false; }
},2000);
(async () => { try { session = await api("/auth/session"); await openConversation(); } catch (error) { tell(error.message); } })();
