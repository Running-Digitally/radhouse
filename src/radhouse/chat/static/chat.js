"use strict";
const $ = id => document.getElementById(id);
const terminal = new Set(["completed","failed","cancelled","interrupted"]);
const explanations = {
  authentication_required:"Sign in again to continue. Your message and draft are kept.",
  login_denied:"Check your username, password and authenticator code.",
  invalid_credentials:"Check your username, password and authenticator code.",
  authentication_unavailable:"Sign-in is temporarily unavailable. Try again shortly.",
  identity_binding_denied:"This account’s conversation access needs to be checked.",
  work_home_unavailable:"This account’s conversation access needs to be checked.",
  owner_access_required:"This account doesn’t have access to this conversation.",
  assistant_unavailable:"The assistant is unavailable. Your message is kept; retry to check whether it was received.",
  conversation_unavailable:"Your conversation couldn’t be loaded. Your draft is kept.",
  reply_pending:"A reply is already in progress. You can keep writing your next message.",
  reply_dispatch_uncertain:"The connection was lost. Your message is kept; retry to check whether it was received.",
  reply_recovery_required:"This saved message needs recovery before another can be sent. You can keep your next draft here.",
  reply_status_unavailable:"Your message is saved. We couldn’t check the reply just now.",
  chat_capability_unavailable:"The assistant isn’t ready to receive this message. It is kept here for retry.",
  unexpected_runtime_approval:"The assistant needs attention before it can continue. Your message is saved.",
  reply_failed:"The assistant couldn’t finish this reply. You can send another message.",
  reply_cancelled:"Reply stopped. You can send another message.",
  reply_interrupted:"The reply was interrupted. You can send another message.",
  empty_reply:"The assistant finished without an answer. You can send another message.",
  request_origin_denied:"Your connection needs refreshing. Your message and draft are kept.",
  csrf_denied:"Your connection needs refreshing. Your message and draft are kept.",
  invalid_request:"This message couldn’t be sent. Its text and files are kept so you can edit it.",
  network_error:"We lost the connection. Your message and files are kept.",
  empty_message:"Write a message or attach a file before sending.",
  message_conflict:"This message has already been received with different content. Reconnect to check the saved conversation.",
  attachment_invalid:"This filename couldn’t be used. Edit the message and attach a renamed copy.",
  attachment_conflict:"This upload has different saved content. Edit the message and attach the file again.",
  attachment_not_found:"A saved file couldn’t be found. Your message is kept; reconnect and try again.",
  file_storage_unavailable:"The upload couldn’t be saved. Your original file and message are kept here for retry.",
  draft_storage_unavailable:"Your browser couldn’t save this draft. Keep this tab open and retry saving it.",
  draft_recovery_in_tab:"You’re signed out. Keep this tab open and sign in here to recover the draft your browser couldn’t save.",
  original_unavailable:"This browser no longer has the unsent original. Edit this message and attach the file again.",
};
let session=null, turns=new Map(), outbox=null, busy=false, polling=false, filesLoading=false;
let olderBefore=null, olderLoaded=false, openingHistory=false, followingLatest=true;
let pendingLookup=null;
const emptyDraft = () => ({text:"",attachments:[]});
let draft=emptyDraft(), noticeCode=null, noticeAction=null, draftSignature="";
const turnNodes=new Map(), previewUrls=new Map();
const retainedSnapshots=new Map();
const browserView=typeof window.BrowserView==="function" ? new window.BrowserView($("assistant-browser")) : null;
let browserEpoch=0, browserStatusRequest=null, browserRequestId=null, browserSuspended=false;
function stopBrowser() {
  browserEpoch++; browserStatusRequest?.controller.abort(); browserStatusRequest=null;
  browserRequestId=null; browserView?.stop();
}
async function refreshBrowser() {
  const pending=pendingTurn();
  if (!browserView || !session || session.features?.browser!==true || !pending || browserSuspended || openingHistory) {
    stopBrowser(); return;
  }
  if (document.hidden) { return; }
  if (browserRequestId!==pending.request_id) { stopBrowser(); browserRequestId=pending.request_id; }
  if (browserStatusRequest) { return; }
  const request={session,request_id:pending.request_id,epoch:browserEpoch,controller:new AbortController()};
  browserStatusRequest=request;
  const timeout=setTimeout(()=>request.controller.abort(),5000);
  const current=()=>session===request.session && browserEpoch===request.epoch && !browserSuspended &&
    pendingTurn()?.request_id===request.request_id && session.features?.browser===true;
  try {
    const status=await api("/chat/browser",undefined,false,request.controller.signal);
    if (current()) { browserView.update(status); }
  } catch {
    // The current request becomes unavailable; cancelled or obsolete requests stay quiet.
    if (current() && !request.controller.signal.aborted) {
      browserView.update({state:"unavailable",run_id:browserView.run,generation:null,url:null});
    }
  } finally {
    clearTimeout(timeout);
    if (browserStatusRequest===request) { browserStatusRequest=null; }
  }
}
$("assistant-browser").addEventListener("browser-auth-required",()=>{ if (session) { showLogin(true); } });
document.addEventListener("visibilitychange",()=>{
  browserEpoch++; browserStatusRequest?.controller.abort(); browserStatusRequest=null;
  if (!document.hidden) { void refreshBrowser(); }
});
window.addEventListener("pagehide",stopBrowser);
function messageFits(text) {
  const characters = text[Symbol.iterator]();
  for (let count = 0; count <= 16000; count++) {
    if (characters.next().done) return true;
  }
  return false;
}
function tell(code, action=null) {
  noticeCode=code; noticeAction=action;
  if (!session) { $("login-notice").textContent=explanations[code] || "We couldn’t sign you in. Try again."; $("login-notice").hidden=false; return; }
  $("notice-text").textContent=explanations[code] || "Something went wrong. Your draft is kept. Try reconnecting.";
  $("notice").hidden=false; $("notice-action").hidden=!action;
  $("notice-action").textContent=["csrf_denied","request_origin_denied","message_conflict"].includes(code) ? "Reconnect" : "Retry";
}
function clearNotice() { noticeCode=null; noticeAction=null; $("notice").hidden=true; $("login-notice").hidden=true; }
function managementNavigation() { $("management-nav").hidden=session?.management?.read!==true; }
function key() { return "radhouse-chat-draft:"+session.username; }
let draftDatabase;
function database() {
  if (!draftDatabase) { draftDatabase=new Promise((resolve,reject) => {
    const request=indexedDB.open("radhouse-chat-drafts",1);
    request.onupgradeneeded=() => request.result.createObjectStore("drafts");
    request.onsuccess=() => resolve(request.result); request.onerror=() => reject(new Error("draft_storage_unavailable"));
  }); }
  return draftDatabase;
}
async function draftOperation(storageKey,value) {
  const db=await database();
  return new Promise((resolve,reject) => {
    const transaction=db.transaction("drafts",value===undefined ? "readonly" : "readwrite"), store=transaction.objectStore("drafts");
    const request=value===undefined ? store.get(storageKey) : store.put(value,storageKey);
    transaction.oncomplete=() => resolve(request.result);
    transaction.onerror=transaction.onabort=() => reject(new Error("draft_storage_unavailable"));
  });
}
let draftWrites=Promise.resolve(), draftRevision=0, savedSignature=null, draftWriteFailed=false;
let managementLeaving=false;
function snapshotSignature(value) {
  return JSON.stringify({...value,revision:undefined,
    attachments:value.attachments.map(file => ({...file,blob:undefined})),
    outbox:value.outbox ? {...value.outbox,phase:undefined,error:undefined,
      attachments:value.outbox.attachments.map(file => ({...file,blob:undefined}))} : null});
}
function saveState() {
  if (!session || openingHistory) { return Promise.resolve(); }
  draft.text=$("message").value;
  const saved=structuredClone({...draft,outbox}), signature=snapshotSignature(saved);
  // Merely checking history or signing out in an unchanged tab must not give
  // its older draft a fresh revision over another tab's newer user edits.
  if (signature===savedSignature && !draftWriteFailed) { return draftWrites; }
  savedSignature=signature;
  draftRevision=Math.max(draftRevision+1,Date.now());
  const storageKey=key(); saved.version=2; saved.revision=draftRevision;
  let fallback=false;
  try {
    localStorage.setItem(storageKey,JSON.stringify({version:2,revision:saved.revision,text:saved.text,
      attachments:saved.attachments.map(file => ({...file,blob:undefined})),
      has_files:!!(saved.attachments.length || saved.outbox?.attachments.length || saved.outbox?.missing_files),
      outbox:saved.outbox ? {...saved.outbox,attachments:saved.outbox.attachments.map(file => ({...file,blob:undefined}))} : null})); fallback=true;
  } catch { /* IndexedDB remains the authority when the text-only fallback fails. */ }
  draftWrites=draftWrites.catch(() => {}).then(() => draftOperation(storageKey,saved)).then(() => { draftWriteFailed=false; }).catch(() => {
    if (saved.attachments.length || saved.outbox?.attachments.length || !fallback) { draftWriteFailed=true; throw new Error("draft_storage_unavailable"); }
  });
  return draftWrites;
}
function persist() { const savingSession=session; return saveState().catch(() => { if (session===savingSession) { tell("draft_storage_unavailable",persist); } }); }
$("management-nav").addEventListener("click",async event => {
  const link=event.target.closest("a");
  if (!link || event.button!==0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) { return; }
  event.preventDefault();
  const destination=new URL(link.href);
  if (destination.pathname==="/" || !session || openingHistory || managementLeaving) { return; }
  const leavingSession=session; managementLeaving=true;
  try {
    // Full-page navigation must not discard the only unsent original. Also
    // await edits/files queued while a previous IndexedDB write was pending.
    while (session===leavingSession && !openingHistory) {
      const saving=saveState(); await saving;
      if (session!==leavingSession || openingHistory) { return; }
      if (saving!==draftWrites || snapshotSignature({...draft,text:$("message").value,outbox})!==savedSignature) { continue; }
      location.assign(destination.href); return;
    }
  } catch { if (session===leavingSession) { tell("draft_storage_unavailable",persist); } }
  finally { managementLeaving=false; }
});
function releaseFile(file) { const url=previewUrls.get(file.file_id); if (url) { URL.revokeObjectURL(url); } previewUrls.delete(file.file_id); }
function releasePreviews() { for (const url of previewUrls.values()) { URL.revokeObjectURL(url); } previewUrls.clear(); }
function showLogin(expired=false) {
  stopBrowser(); browserSuspended=false;
  if (session) {
    $("username").value=session.username;
    // Keep the only original in this tab when browser storage is unavailable.
    // The signed-out UI is cleared; restoration uses the exact owner's key.
    if (!openingHistory) { retainedSnapshots.set(session.username,
      structuredClone({...draft,text:$("message").value,outbox,version:2,revision:draftRevision})); }
  }
  session=null; pendingLookup=null; releasePreviews(); draft=emptyDraft(); outbox=null; turns.clear(); turnNodes.clear(); draftSignature="";
  managementNavigation();
  busy=false; polling=false; filesLoading=false; openingHistory=false;
  $("messages").replaceChildren(); $("draft-files").replaceChildren(); $("message").value="";
  $("chat-view").hidden=true; $("logout").hidden=true; $("login-view").hidden=false; $("loading").hidden=true;
  clearNotice(); if (expired) { tell("authentication_required"); }
}
async function api(path,body,initial=false,signal=undefined) {
  const requestingSession=session;
  const headers={};
  if (body!==undefined) { headers["Content-Type"]="application/json"; if (session) { headers["X-Radhouse-CSRF"]=session.csrf_token; } }
  let response;
  try { response=await fetch(path,{method:body===undefined ? "GET" : "POST",headers,body:body===undefined ? undefined : JSON.stringify(body),signal}); }
  catch { throw new Error("network_error"); }
  if (!response.ok) {
    let value; try { value=await response.json(); } catch { value={}; }
    if (response.status===401 && session===requestingSession) { showLogin(!initial); }
    const error=new Error(value.error || "service_unavailable"); error.status=response.status; throw error;
  }
  return response.status===204 ? null : response.json();
}
function pendingTurn() { return [...turns.values()].find(turn => !terminal.has(turn.status)); }
function rememberTurn(turn) {
  turns.set(turn.seq,turn);
  if (outbox?.request_id===turn.request_id) { outbox.attachments.forEach(releaseFile); outbox=null; persist(); }
}
async function reconcilePending(data) {
  const pending=pendingTurn();
  if (!session || !pending || pendingLookup || !data.turns.some(turn => turn.seq>pending.seq) ||
      data.turns.some(turn => turn.request_id===pending.request_id)) { return; }
  const lookup={request_id:pending.request_id,session}; pendingLookup=lookup;
  try {
    const receipt=await api("/chat/messages/"+encodeURIComponent(lookup.request_id));
    if (session!==lookup.session) { return; }
    rememberTurn(receipt.turn); render(); void refreshBrowser();
  } catch (error) { if (session===lookup.session) { tell(error.message,refreshHistory); } }
  finally { if (pendingLookup===lookup) { pendingLookup=null; } }
}
function accept(data,older=false,latest=false,requestedBefore=olderBefore) {
  const cachedLatest=[...turns.keys()].reduce((max,seq) => Math.max(max,seq),0);
  const disjointLatest=!older && cachedLatest && data.turns.length && data.turns[0].seq>cachedLatest &&
    !data.turns.some(turn => turns.has(turn.seq));
  if (outbox && outbox.request_id===data.accepted_request_id) { outbox.attachments.forEach(releaseFile); outbox=null; persist(); }
  for (const turn of data.turns) { rememberTurn(turn); }
  // A new latest page can be separated from an already-loaded older range.
  // Reopen pagination at that page so every intervening message stays reachable.
  if (older ? requestedBefore===olderBefore : !olderLoaded || disjointLatest) { olderBefore=data.older_before; }
  if (older) { olderLoaded=true; }
  if (["network_error","conversation_unavailable","assistant_unavailable"].includes(noticeCode)) { clearNotice(); }
  render({older,latest});
  if (!older) { void refreshBrowser(); }
  if (!older) { reconcilePending(data); }
}
function fileKind(file) {
  const extension=file.name.split(".").pop().toLowerCase();
  if (["png","jpg","jpeg","webp"].includes(extension) || ["image/png","image/jpeg","image/webp"].includes(file.type)) { return "image"; }
  if (["wav","mp3","m4a","ogg","flac","webm"].includes(extension)) { return "audio"; }
  return ["pdf","docx","xlsx","pptx"].includes(extension) ? "document" : "file";
}
function sizeLabel(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}
function previewUrl(file) { if (!(file.blob instanceof Blob)) { return null; } if (!previewUrls.has(file.file_id)) { previewUrls.set(file.file_id,URL.createObjectURL(file.blob)); } return previewUrls.get(file.file_id); }
const documentTypes={pdf:{icon:"pdf",label:"PDF"},docx:{icon:"word",label:"Word"},xlsx:{icon:"excel",label:"Excel"},pptx:{icon:"powerpoint",label:"PowerPoint"}};
function readingLabel(file) {
  if (file.reading_state==="available") { return "Available to the assistant"; }
  if (file.reading_state==="excerpt") { return "Text excerpt shared"; }
  if (file.reading_state!=="not_read") { return null; }
  return ({document_encrypted:"Password-protected; original saved",document_needs_ocr:"No readable text; original saved",
    audio_transcription_not_configured:"Audio saved; transcription isn’t connected",audio_no_speech:"No speech found; original saved",
    image_transport_unavailable:"Image saved; not provided to the assistant",reading_budget:"Original saved; not included in this reply"})[file.reading_error] || "Original saved; assistant access pending";
}
function fileVisual(file, url, type) {
  if (file.kind==="image" && url || type) {
    const img=document.createElement("img"); img.className="file-visual "+(type ? "document-icon" : "image-preview");
    img.src=type ? "/icons/"+type.icon+".svg" : url; img.alt=type ? type.label+" document" : file.name; return img;
  } else { const icon=document.createElement("span"); icon.className="file-visual file-generic"; icon.textContent=file.kind==="audio" ? "♫" : "▤"; icon.setAttribute("aria-hidden","true"); return icon; }
}
function fileInfo(file, url, removable, type) {
  const info=document.createElement("div"); info.className="file-info";
  const name=document.createElement(removable || !url ? "span" : "a"); name.className="file-name"; name.textContent=file.name;
  if (!removable && url) { name.href=file.blob ? url : url+"?download=true"; name.setAttribute("download",file.name); }
  const detail=document.createElement("span"); detail.className="file-detail"; detail.textContent=(type?.label || file.kind)+" · "+sizeLabel(file.size); info.append(name,detail);
  const label=readingLabel(file);
  if (label) { const reading=document.createElement("span"); reading.className="file-detail"+(file.reading_state==="not_read" ? " file-warning" : ""); reading.textContent=label; info.append(reading); }
  if (file.kind==="audio" && url) {
    const playback=document.createElement("details"), summary=document.createElement("summary"), audio=document.createElement("audio");
    playback.dataset.detail="audio"; summary.textContent="Play audio"; audio.controls=true; audio.preload="none"; audio.src=url; audio.setAttribute("aria-label",file.name); playback.append(summary,audio); info.append(playback);
  }
  if (file.transcript) {
    const transcript=document.createElement("details"), summary=document.createElement("summary"), text=document.createElement("p");
    transcript.dataset.detail="transcript"; summary.textContent="Audio transcript"; text.textContent=file.transcript; transcript.append(summary,text); info.append(transcript);
  }
  return info;
}
function fileCard(file,url,removable) {
  const card=document.createElement("div"); card.className="attachment";
  const extension=file.name.split(".").pop().toLowerCase(), type=Object.hasOwn(documentTypes,extension) ? documentTypes[extension] : null;
  card.append(fileVisual(file, url, type));
  const info = fileInfo(file, url, removable, type);
  card.append(info);
  if (removable) {
    const remove=document.createElement("button"); remove.type="button"; remove.className="remove-file"; remove.textContent="×"; remove.setAttribute("aria-label","Remove "+file.name);
    remove.addEventListener("click",() => { releaseFile(file); draft.attachments=draft.attachments.filter(a => a.file_id!==file.file_id); persist(); render(); $("attach").focus(); }); card.append(remove);
  }
  return card;
}
function attachmentList(turn) {
  const files=document.createElement("div"); files.className="attachments";
  const attachments=turn.attachments || [];
  const append=(target,file) => target.append(fileCard(file,turn.local ? previewUrl(file) : "/chat/messages/"+turn.request_id+"/attachments/"+file.position,false));
  attachments.slice(0,3).forEach(file => append(files,file));
  if (attachments.length>3) {
    const more=document.createElement("details"), summary=document.createElement("summary"), rest=document.createElement("div");
    more.className="attachment-list-more"; more.dataset.detail="more"; summary.textContent=(attachments.length-3)+" more files"; rest.className="attachments";
    attachments.slice(3).forEach(file => append(rest,file)); more.append(summary,rest); files.append(more);
  }
  return files;
}
function assistantReply(turn) {
  const reply=document.createElement("div"); reply.className="assistant";
  const name=document.createElement("p"), answer=document.createElement("div"), copy=document.createElement("button"); name.className="message-label"; name.textContent="Radhouse";
  answer.className="answer"; answer.append(window.RadhouseFormat.render(turn.output)); copy.type="button"; copy.className="copy-answer"; copy.dataset.label="Copy answer"; copy.textContent="Copy answer";
  copy.addEventListener("click",() => window.RadhouseFormat.copyText(turn.output,copy)); reply.append(name,answer,copy); return reply;
}
function turnStatusText(turn) {
  if (turn.error) return explanations[turn.error] || "This message needs attention. Its text and files are kept.";
  if (turn.local) {
    if (turn.phase === "uploading") return "Uploading files…";
    if (turn.phase === "checking") return "Checking your saved message…";
    return "Sending…";
  }
  if (turn.status === "awaiting_dispatch") return "Your message is saved. Preparing the reply…";
  return "Radhouse is replying…";
}
function pendingReply(block, turn) {
  const status=document.createElement("p"); status.className=turn.error ? "turn-error" : "pending";
  status.textContent = turnStatusText(turn);
  block.append(status);
  if (turn.local && turn.phase==="uploading") { const progress=document.createElement("p"); progress.className="sending-files"; progress.dataset.uploadProgress=""; block.append(progress); }
  if (turn.local && turn.error) {
    const retry=document.createElement("button"); retry.className="retry"; retry.dataset.outgoing="true"; retry.textContent="Retry message"; retry.addEventListener("click",retryOutgoing); block.append(retry);
    if (!turn.transmitted) { const edit=document.createElement("button"); edit.className="retry"; edit.textContent="Edit message"; edit.addEventListener("click",editOutgoing); block.append(edit); }
  } else if (!turn.local && turn.status==="awaiting_dispatch" && turn.error!=="reply_recovery_required") {
    const retry=document.createElement("button"); retry.className="retry"; retry.textContent="Retry message"; retry.addEventListener("click",() => retrySaved(turn.request_id)); block.append(retry);
  }
}
function makeTurn(turn) {
  const block=document.createElement("article"); block.className="turn"; block.dataset.requestId=turn.request_id;
  const label=document.createElement("p"), text=document.createElement("p"); label.className="message-label"; label.textContent="You";
  text.className="message-text"; text.textContent=turn.text; block.append(label,text);
  if (turn.attachments?.length) { block.append(attachmentList(turn)); }
  if (turn.output) { block.append(assistantReply(turn)); }
  else { pendingReply(block, turn); }
  return block;
}

function scrollAnchor() {
  const top=$("history-pane").getBoundingClientRect().top;
  for (const node of $("messages").children) { const r=node.getBoundingClientRect(); if (r.bottom>top) { return {id:node.dataset.requestId,offset:r.top-top}; } }
  return null;
}
function updateLatest() { $("latest").hidden=followingLatest || $("history-pane").scrollHeight<=$("history-pane").clientHeight+80; }
function replaceSavedTurn(turn, signature, saved) {
  const node=makeTurn(turn);
  if (saved) {
    const open=[...saved.node.querySelectorAll("details")].map(d => d.open);
    [...node.querySelectorAll("details")].forEach((d,i) => { d.open=!!open[i]; }); saved.node.replaceWith(node);
  }
  saved={signature,node}; turnNodes.set(turn.request_id,saved);
  return saved;
}
function renderHistory({older=false,latest=false}={}) {
  const pane=$("history-pane"), anchor=scrollAnchor();
  const ordered=[...turns.values()].sort((a,b) => a.seq-b.seq);
  if (outbox) { ordered.push({...outbox,local:true}); }
  let preceding=null;
  const current=new Set();
  for (const turn of ordered) {
    current.add(turn.request_id);
    const signature=JSON.stringify({...turn,attachments:turn.attachments?.map(file => ({...file,blob:undefined}))});
    let saved=turnNodes.get(turn.request_id);
    if (saved?.signature!==signature) {
      saved = replaceSavedTurn(turn, signature, saved);
    }
    const expected=preceding ? preceding.nextSibling : $("messages").firstChild;
    if (saved.node!==expected) { $("messages").insertBefore(saved.node,expected); }
    preceding=saved.node;
  }
  for (const [id,saved] of turnNodes) { if (!current.has(id)) { saved.node.remove(); turnNodes.delete(id); } }
  $("empty").hidden=ordered.length>0; $("older").hidden=!olderBefore;
  if (latest || followingLatest && !older) { followingLatest=true; pane.scrollTop=pane.scrollHeight; }
  else if (anchor && turnNodes.has(anchor.id)) { pane.scrollTop+=turnNodes.get(anchor.id).node.getBoundingClientRect().top-pane.getBoundingClientRect().top-anchor.offset; }
  updateLatest();
}
function renderDraft() {
  const signature=draft.attachments.map(a => a.file_id).join(":");
  if (signature!==draftSignature) { $("draft-files").replaceChildren(...draft.attachments.map(file => fileCard(file,previewUrl(file),true))); draftSignature=signature; }
}
function resizeMessage() { const input=$("message"); input.style.height="auto"; input.style.height=Math.min(input.scrollHeight,Math.min(180,innerHeight*.24))+"px"; }
function replyStatus(pending) {
  if (filesLoading) return "Adding files…";
  if (busy) return outbox?.phase === "uploading" ? "Uploading…" : "Sending…";
  return pending ? "Radhouse is replying…" : "";
}
function controls() {
  const pending=pendingTurn(), tooLong=!messageFits($("message").value), hasContent=!!($("message").value.trim() || draft.attachments.length);
  $("message").disabled=openingHistory;
  $("send").disabled=busy || filesLoading || !!pending || !!outbox || tooLong || !hasContent || openingHistory;
  $("attach").disabled=filesLoading || openingHistory; $("attach-text").disabled=filesLoading || openingHistory; $("long-text").hidden=!tooLong;
  $("send").textContent=busy ? "Sending…" : "Send ↗";
  $("reply-status").textContent = replyStatus(pending);
  document.querySelectorAll(".retry,#notice-action").forEach(button => { button.disabled=busy || openingHistory || button.dataset.outgoing==="true" && !!pending; });
  resizeMessage();
}
function render(options) { renderHistory(options); renderDraft(); controls(); }
function migrateFile(file) {
  if (file.blob instanceof Blob) { return {...file,file_id:file.file_id || crypto.randomUUID()}; }
  if (file.content===undefined) { return file; } // Text-only recovery preserves immutable file references, never omits them.
  const bytes=Uint8Array.from(atob(file.content),c => c.codePointAt(0));
  return {...file,content:undefined,blob:new Blob([bytes],{type:file.type}),file_id:crypto.randomUUID()};
}
function recoveredSnapshot(stored,fallback) {
  const revision=value => Number.isSafeInteger(value?.revision) && value.revision>=0 ? value.revision : 0;
  draftRevision=Math.max(draftRevision,revision(stored),revision(fallback));
  if (!fallback) { return stored; }
  const chosen=stored && revision(stored)>=revision(fallback) ? stored : fallback;
  // The newest snapshot owns text/request state. Either store or this tab may
  // retain its immutable originals after a failed write; never restore removals.
  const originals=new Map([...(stored?.attachments || []),...(stored?.outbox?.attachments || []),
    ...(fallback.attachments || []),...(fallback.outbox?.attachments || [])]
    .filter(file => file.file_id && file.blob instanceof Blob).map(file => [file.file_id,file.blob]));
  const files=values => (values || []).map(file => !(file.blob instanceof Blob) && originals.has(file.file_id) ? {...file,blob:originals.get(file.file_id)} : file);
  return {...chosen,attachments:files(chosen.attachments),
    outbox:chosen.outbox ? {...chosen.outbox,attachments:files(chosen.outbox.attachments)} : null};
}
function restoreSnapshot(saved) {
  if (saved && typeof saved.text==="string") {
    if (saved.version===2) { draft={text:saved.text,attachments:(saved.attachments || []).map(migrateFile)}; outbox=saved.outbox; }
    else if (saved.request_id) { outbox={text:saved.text,request_id:saved.request_id,attachments:(saved.attachments || []).map(migrateFile),transmitted:true,legacy:true}; }
    else { draft={text:saved.text,attachments:(saved.attachments || []).map(migrateFile)}; }
    if (outbox) {
      // Earlier text-only recovery records did not retain file IDs. Never retry these as a text-only message.
      if (saved.version!==2 && saved.has_files && !outbox.attachments.length) { outbox.missing_files=true; }
      outbox.attachments=outbox.attachments.map(migrateFile); outbox.phase="checking"; outbox.error=null;
    }
  }
}
async function finishOpening(openingSession) {
  if (session !== openingSession) return;
  openingHistory = false;
  if (outbox) { outbox.phase = "failed"; outbox.error = "network_error"; }
  await persist();
  if (session !== openingSession) return;
  if (!draftWriteFailed) retainedSnapshots.delete(openingSession.username);
  render(); void refreshBrowser();
  if (!matchMedia("(pointer:coarse)").matches) $("message").focus();
}
async function openConversation() {
  stopBrowser(); browserSuspended=false;
  const openingSession=session; openingHistory=true; followingLatest=true; olderLoaded=false; olderBefore=null;
  turns.clear(); turnNodes.clear(); $("messages").replaceChildren(); draftSignature=""; draft=emptyDraft(); outbox=null;
  $("login-view").hidden=true; $("chat-view").hidden=false; $("logout").hidden=false; $("loading").hidden=true;
  managementNavigation();
  controls();
  const storageKey=key(); let stored, fallback;
  try { stored=await draftOperation(storageKey); } catch { /* Recover through the text fallback or this tab’s retained originals. */ }
  if (session!==openingSession) { return; }
  try { fallback=JSON.parse(localStorage.getItem(storageKey) || "null"); } catch { /* Invalid or blocked fallback storage cannot replace retained originals. */ }
  const retained=retainedSnapshots.get(openingSession.username);
  const saved=recoveredSnapshot(recoveredSnapshot(stored,fallback),retained);
  if (saved?.has_files && [...(saved.attachments || []),...(saved.outbox?.attachments || [])].some(file => !(file.blob instanceof Blob))) { tell("draft_storage_unavailable",persist); }
  if (session!==openingSession) { return; }
  restoreSnapshot(saved);
  savedSignature=snapshotSignature({...draft,outbox}); draftWriteFailed=!!retained;
  $("message").value=draft.text; render({latest:true});
  try { const data=await api("/chat/history"); if (session===openingSession) { accept(data,false,true); } }
  catch (error) { if (session===openingSession) { tell(error.message,refreshHistory); } }
  finally { await finishOpening(openingSession); }
}

async function refreshHistory() {
  if (busy || !session) { return; }
  const readingSession=session;
  try {
    const fresh=await api("/auth/session");
    if (session!==readingSession) { return; }
    Object.assign(readingSession,fresh); managementNavigation(); clearNotice();
    const data=await api("/chat/history"); if (session===readingSession) { accept(data); }
  } catch (error) { if (session===readingSession) { tell(error.message,refreshHistory); } }
}
function progress(file,loaded,total,sendingSession) {
  if (session!==sendingSession) { return; }
  const box=outbox; if (!box) { return; }
  const target=document.querySelector("[data-upload-progress]");
  if (target) { target.textContent=file.name+" · "+(total ? Math.round(loaded/total*100)+"% transferred" : sizeLabel(loaded)+" transferred"); }
}
async function uploadOriginal(file, sendingSession) {
  let receipt;
  try { receipt=await api("/chat/files/"+file.file_id); }
  catch (error) { if (error.status!==404) { throw error; } }
  if (session!==sendingSession) { throw new Error("authentication_required"); }
  if (!receipt && !(file.blob instanceof Blob)) { throw new Error("original_unavailable"); }
  if (!receipt) { receipt=await new Promise((resolve,reject) => {
    const request=new XMLHttpRequest(); request.open("PUT","/chat/files/"+file.file_id+"?name="+encodeURIComponent(file.name));
    request.setRequestHeader("Content-Type","application/octet-stream"); request.setRequestHeader("X-Radhouse-CSRF",sendingSession.csrf_token);
    request.upload.onprogress=event => progress(file,event.loaded,event.lengthComputable ? event.total : 0,sendingSession);
    request.onerror=request.onabort=() => reject(new Error("network_error"));
    request.onload=() => {
      let value; try { value=JSON.parse(request.responseText); } catch { value={}; }
      if (request.status>=200 && request.status<300) { resolve(value); }
      else { if (request.status===401 && session===sendingSession) { showLogin(true); } const error=new Error(value.error || "file_storage_unavailable"); error.status=request.status; reject(error); }
    };
    progress(file,0,file.size,sendingSession); request.send(file.blob);
  }); }
  if (receipt.name!==file.name || receipt.size!==file.size) { throw new Error("attachment_conflict"); }
  file.uploaded=true;
}
async function prepareOutgoingFiles(box, sendingSession) {
  if (box.legacy) {
    try { const data=await api("/chat/messages/"+box.request_id+"/retry",{}); if (session===sendingSession) { accept(data); } return false; }
    catch (error) { if (error.status!==404) { throw error; } box.transmitted=false; }
  }
  if (box.missing_files) { throw new Error("original_unavailable"); }
  for (const file of box.attachments) {
    box.phase="uploading"; render(); await uploadOriginal(file,sendingSession);
    if (session!==sendingSession) { return false; }
    await saveState();
  }
  return true;
}
async function recoverOutgoing(box, sendingSession, error) {
  if (session===sendingSession && outbox===box) {
    box.phase="failed"; box.error=error.message;
    if ([413,422].includes(error.status) || error.message==="reply_pending") { box.transmitted=false; }
    await persist();
    if (["csrf_denied","request_origin_denied"].includes(error.message)) { tell(error.message,refreshHistory); }
    try { const data=await api("/chat/history"); if (session===sendingSession) { accept(data); } } catch { /* The failed outbox and its retry identity are already retained. */ }
  }
}
async function transmit(box) {
  if (busy || !session || outbox!==box) { return; }
  const sendingSession=session; busy=true; box.error=null; clearNotice(); box.phase="sending"; render({latest:true});
  try {
    const credentials=await api("/auth/session");
    if (session!==sendingSession) { return; }
    Object.assign(sendingSession,credentials); managementNavigation();
    await saveState();
    if (session!==sendingSession) { return; }
    if (!await prepareOutgoingFiles(box, sendingSession)) return;
    box.phase="sending"; box.transmitted=true; await saveState(); render();
    if (session!==sendingSession) { return; }
    const data=await api("/chat/messages",{request_id:box.request_id,text:box.text,attachments:box.attachments.map(a => a.file_id)});
    if (session===sendingSession) { accept(data); }
  } catch (error) {
    await recoverOutgoing(box, sendingSession, error);
  } finally { if (session===sendingSession) { busy=false; render(); } }
}
function retryOutgoing() { if (outbox && !pendingTurn()) { transmit(outbox); } }
async function retrySaved(requestId) {
  if (busy || !session) { return; }
  const sendingSession=session; busy=true; clearNotice(); controls();
  try {
    const credentials=await api("/auth/session");
    if (session!==sendingSession) { return; }
    Object.assign(sendingSession,credentials); managementNavigation();
    const data=await api("/chat/messages/"+requestId+"/retry",{}); if (session===sendingSession) { accept(data); }
  }
  catch (error) { if (session===sendingSession) { tell(error.message,refreshHistory); } }
  finally { if (session===sendingSession) { busy=false; render(); } }
}
function editOutgoing() {
  if (!outbox || outbox.transmitted || busy) { return; }
  const missingFiles=outbox.missing_files;
  draft.text=[outbox.text,$("message").value].filter(Boolean).join("\n\n");
  draft.attachments=[...outbox.attachments,...draft.attachments]; outbox=null;
  $("message").value=draft.text; persist(); render(); if (missingFiles) { tell("original_unavailable"); } $("message").focus();
}
async function addFiles(fileList) {
  if (!session || filesLoading || openingHistory) { return; }
  const addingSession=session; filesLoading=true; clearNotice(); controls();
  try {
    draft.attachments.push(...[...fileList].map(file => ({name:file.name,blob:file,file_id:crypto.randomUUID(),kind:fileKind(file),type:file.type,size:file.size})));
    await saveState();
  } catch (error) { if (session===addingSession) { tell(error.message,persist); } }
  finally { if (session===addingSession) { filesLoading=false; render(); } }
}
$("attach").addEventListener("click",() => $("file-picker").click());
$("file-picker").addEventListener("change",event => { addFiles(event.target.files); event.target.value=""; });
$("attach-text").addEventListener("click",async () => {
  const text=$("message").value, convertingSession=session;
  await addFiles([new File([text],"pasted-text.txt",{type:"text/plain"})]);
  if (session!==convertingSession) { return; }
  // Only clear after the file draft was successfully written.
  try {
    await saveState();
    if (session!==convertingSession) { return; }
    if ($("message").value===text) { draft.text=""; $("message").value=""; }
    await saveState(); if (session===convertingSession) { render(); $("message").focus(); }
  }
  catch { if (session===convertingSession) { tell("draft_storage_unavailable",persist); } }
});
$("compose").addEventListener("paste",event => { const files=[...(event.clipboardData?.files || [])]; if (files.length) { event.preventDefault(); addFiles(files); } });
$("chat-view").addEventListener("dragover",event => { if ([...event.dataTransfer.types].includes("Files")) { event.preventDefault(); $("compose").classList.add("dragging"); } });
$("chat-view").addEventListener("dragleave",event => { if (!$("chat-view").contains(event.relatedTarget)) { $("compose").classList.remove("dragging"); } });
$("chat-view").addEventListener("drop",event => { event.preventDefault(); $("compose").classList.remove("dragging"); addFiles(event.dataTransfer.files); });
$("compose").addEventListener("submit",event => {
  event.preventDefault();
  if ($("send").disabled) { return; }
  outbox={request_id:crypto.randomUUID(),text:$("message").value,attachments:draft.attachments,phase:"sending",transmitted:false,error:null};
  draft=emptyDraft(); $("message").value=""; render({latest:true}); $("message").focus(); transmit(outbox);
});
$("message").addEventListener("input",() => { persist(); controls(); });
$("message").addEventListener("keydown",event => {
  if (event.key==="Enter" && !event.shiftKey && !event.isComposing && (!matchMedia("(pointer:coarse)").matches || event.ctrlKey || event.metaKey) && !$("send").disabled) { event.preventDefault(); $("compose").requestSubmit(); }
});
$("notice-action").addEventListener("click",() => noticeAction?.());
$("history-pane").addEventListener("scroll",() => { const pane=$("history-pane"); followingLatest=pane.scrollHeight-pane.scrollTop-pane.clientHeight<80; updateLatest(); });
$("latest").addEventListener("click",() => { followingLatest=true; $("history-pane").scrollTop=$("history-pane").scrollHeight; updateLatest(); });
new ResizeObserver(entries => { $("chat-view").style.setProperty("--composer-height",entries[0].target.offsetHeight+14+"px"); if (followingLatest) { $("history-pane").scrollTop=$("history-pane").scrollHeight; } updateLatest(); }).observe($("compose"));
new ResizeObserver(()=>{ if (followingLatest) { $("history-pane").scrollTop=$("history-pane").scrollHeight; } updateLatest(); }).observe($("assistant-browser"));
$("older").addEventListener("click",async () => {
  const readingSession=session, requestedBefore=olderBefore;
  try { const data=await api("/chat/history?before="+requestedBefore); if (session===readingSession) { accept(data,true,false,requestedBefore); } }
  catch (error) { if (session===readingSession) { tell(error.message,refreshHistory); } }
});
$("login-form").addEventListener("submit",async event => {
  event.preventDefault(); clearNotice(); const button=event.submitter, signingInSession=session; button.disabled=true;
  try {
    const credentials=await api("/auth/login",{username:$("username").value,password:$("password").value,totp_code:$("totp").value,remember_browser:$("remember").checked});
    if (session!==signingInSession) { return; }
    session=credentials; $("password").value=""; $("totp").value=""; await openConversation();
  }
  catch (error) { if (session===signingInSession) { tell(error.message); } } finally { button.disabled=false; }
});
$("logout").addEventListener("click",async () => {
  browserSuspended=true; stopBrowser();
  const signingOutSession=session; let saved=true;
  try { await saveState(); } catch { saved=false; }
  if (session!==signingOutSession) { return; }
  try { await api("/auth/logout",{}); if (session===signingOutSession) { showLogin(); if (!saved) { tell("draft_recovery_in_tab"); } } }
  catch (error) { if (session===signingOutSession) { browserSuspended=false; void refreshBrowser(); tell(error.message); } }
});
setInterval(async () => {
  if (!session || !pendingTurn() || busy || polling) { return; }
  polling=true; const readingSession=session;
  try { const data=await api("/chat/reply"); if (session===readingSession) { accept(data); } }
  catch (error) { if (session===readingSession) { tell(error.message,refreshHistory); } }
  finally { if (session===readingSession) { polling=false; } }
},2000);
setInterval(()=>{ void refreshBrowser(); },2000);
window.addEventListener("resize", resizeMessage);
(async () => {
  const startingSession=session;
  try { const credentials=await api("/auth/session",undefined,true); if (session!==startingSession) { return; } session=credentials; await openConversation(); }
  catch (error) { if (session===startingSession && error.status!==401) { showLogin(); tell(error.message); } }
})();
