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
  original_unavailable:"This browser no longer has the unsent original. Edit this message and attach the file again.",
};
let session=null, turns=new Map(), outbox=null, busy=false, polling=false, filesLoading=false;
let olderBefore=null, olderLoaded=false, openingHistory=false, followingLatest=true;
const emptyDraft = () => ({text:"",attachments:[]});
let draft=emptyDraft(), noticeCode=null, noticeAction=null, draftSignature="";
const turnNodes=new Map(), previewUrls=new Map();
function messageFits(text) { let count=0; for (const _ of text) if (++count>16000) return false; return true; }
function tell(code, action=null) {
  noticeCode=code; noticeAction=action;
  if (!session) { $("login-notice").textContent=explanations[code] || "We couldn’t sign you in. Try again."; $("login-notice").hidden=false; return; }
  $("notice-text").textContent=explanations[code] || "Something went wrong. Your draft is kept. Try reconnecting.";
  $("notice").hidden=false; $("notice-action").hidden=!action;
  $("notice-action").textContent=["csrf_denied","request_origin_denied","message_conflict"].includes(code) ? "Reconnect" : "Retry";
}
function clearNotice() { noticeCode=null; noticeAction=null; $("notice").hidden=true; $("login-notice").hidden=true; }
function key() { return "radhouse-chat-draft:"+session.username; }
let draftDatabase;
function database() {
  if (!draftDatabase) draftDatabase=new Promise((resolve,reject) => {
    const request=indexedDB.open("radhouse-chat-drafts",1);
    request.onupgradeneeded=() => request.result.createObjectStore("drafts");
    request.onsuccess=() => resolve(request.result); request.onerror=() => reject(new Error("draft_storage_unavailable"));
  });
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
let draftWrites=Promise.resolve(), draftRevision=0;
function saveState() {
  if (!session) return Promise.resolve();
  draft.text=$("message").value;
  draftRevision=Math.max(draftRevision+1,Date.now());
  const storageKey=key(), saved=structuredClone({version:2,revision:draftRevision,...draft,outbox});
  let fallback=false;
  try {
    localStorage.setItem(storageKey,JSON.stringify({version:2,revision:saved.revision,text:saved.text,
      attachments:saved.attachments.map(file => ({...file,blob:undefined})),
      has_files:!!(saved.attachments.length || saved.outbox?.attachments.length || saved.outbox?.missing_files),
      outbox:saved.outbox ? {...saved.outbox,attachments:saved.outbox.attachments.map(file => ({...file,blob:undefined}))} : null})); fallback=true;
  } catch (_) {}
  draftWrites=draftWrites.catch(() => {}).then(() => draftOperation(storageKey,saved)).catch(error => {
    if (saved.attachments.length || saved.outbox?.attachments.length || !fallback) throw error;
  });
  return draftWrites;
}
function persist() { return saveState().catch(() => tell("draft_storage_unavailable",persist)); }
function releaseFile(file) { const url=previewUrls.get(file.file_id); if (url) URL.revokeObjectURL(url); previewUrls.delete(file.file_id); }
function releasePreviews() { for (const url of previewUrls.values()) URL.revokeObjectURL(url); previewUrls.clear(); }
function showLogin(expired=false) {
  if (session) $("username").value=session.username;
  session=null; releasePreviews(); draft=emptyDraft(); outbox=null; turns.clear(); turnNodes.clear(); draftSignature="";
  $("messages").replaceChildren(); $("draft-files").replaceChildren(); $("message").value="";
  $("chat-view").hidden=true; $("logout").hidden=true; $("login-view").hidden=false; $("loading").hidden=true;
  clearNotice(); if (expired) tell("authentication_required");
}
async function api(path,body,initial=false) {
  const headers={};
  if (body!==undefined) { headers["Content-Type"]="application/json"; if (session) headers["X-Radhouse-CSRF"]=session.csrf_token; }
  let response;
  try { response=await fetch(path,{method:body===undefined ? "GET" : "POST",headers,body:body===undefined ? undefined : JSON.stringify(body)}); }
  catch (_) { throw new Error("network_error"); }
  if (!response.ok) {
    let value; try { value=await response.json(); } catch (_) { value={}; }
    if (response.status===401) showLogin(!initial);
    const error=new Error(value.error || "service_unavailable"); error.status=response.status; throw error;
  }
  return response.status===204 ? null : response.json();
}
function pendingTurn() { return [...turns.values()].find(turn => !terminal.has(turn.status)); }
function accept(data,older=false,latest=false) {
  for (const turn of data.turns) {
    turns.set(turn.seq,turn);
    if (outbox?.request_id===turn.request_id) { outbox.attachments.forEach(releaseFile); outbox=null; persist(); }
  }
  if (older || !olderLoaded) olderBefore=data.older_before;
  if (older) olderLoaded=true;
  if (["network_error","conversation_unavailable","assistant_unavailable"].includes(noticeCode)) clearNotice();
  render({older,latest});
}
function fileKind(file) {
  const extension=file.name.split(".").pop().toLowerCase();
  if (["png","jpg","jpeg","webp"].includes(extension) || ["image/png","image/jpeg","image/webp"].includes(file.type)) return "image";
  if (["wav","mp3","m4a","ogg","flac","webm"].includes(extension)) return "audio";
  return ["pdf","docx","xlsx","pptx"].includes(extension) ? "document" : "file";
}
function sizeLabel(bytes) { return bytes<1024 ? bytes+" B" : bytes<1024*1024 ? Math.round(bytes/1024)+" KB" : (bytes/1024/1024).toFixed(1)+" MB"; }
function previewUrl(file) { if (!(file.blob instanceof Blob)) return null; if (!previewUrls.has(file.file_id)) previewUrls.set(file.file_id,URL.createObjectURL(file.blob)); return previewUrls.get(file.file_id); }
const documentTypes={pdf:{icon:"pdf",label:"PDF"},docx:{icon:"word",label:"Word"},xlsx:{icon:"excel",label:"Excel"},pptx:{icon:"powerpoint",label:"PowerPoint"}};
function readingLabel(file) {
  if (file.reading_state==="excerpt") return "Text excerpt shared";
  if (file.reading_state!=="not_read") return null;
  return ({document_encrypted:"Password-protected; original saved",document_needs_ocr:"No readable text; original saved",
    audio_transcription_not_configured:"Audio saved; transcription isn’t connected",audio_no_speech:"No speech found; original saved",
    image_transport_unavailable:"Image saved; not provided to the assistant",reading_budget:"Original saved; not included in this reply"})[file.reading_error] || "Original saved; assistant access pending";
}
function fileCard(file,url,removable) {
  const card=document.createElement("div"); card.className="attachment";
  const extension=file.name.split(".").pop().toLowerCase(), type=Object.hasOwn(documentTypes,extension) ? documentTypes[extension] : null;
  if (file.kind==="image" && url || type) {
    const img=document.createElement("img"); img.className="file-visual "+(type ? "document-icon" : "image-preview");
    img.src=type ? "/icons/"+type.icon+".svg" : url; img.alt=type ? type.label+" document" : file.name; card.append(img);
  } else { const icon=document.createElement("span"); icon.className="file-visual file-generic"; icon.textContent=file.kind==="audio" ? "♫" : "▤"; icon.setAttribute("aria-hidden","true"); card.append(icon); }
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
function makeTurn(turn) {
  const block=document.createElement("article"); block.className="turn"; block.dataset.requestId=turn.request_id;
  const label=document.createElement("p"), text=document.createElement("p"); label.className="message-label"; label.textContent="You";
  text.className="message-text"; text.textContent=turn.text; block.append(label,text);
  if (turn.attachments?.length) block.append(attachmentList(turn));
  if (turn.output) {
    const reply=document.createElement("div"); reply.className="assistant";
    const name=document.createElement("p"), answer=document.createElement("div"), copy=document.createElement("button"); name.className="message-label"; name.textContent="Radhouse";
    answer.className="answer"; answer.append(window.RadhouseFormat.render(turn.output)); copy.type="button"; copy.className="copy-answer"; copy.dataset.label="Copy answer"; copy.textContent="Copy answer";
    copy.addEventListener("click",() => window.RadhouseFormat.copyText(turn.output,copy)); reply.append(name,answer,copy); block.append(reply);
  } else {
    const status=document.createElement("p"); status.className=turn.error ? "turn-error" : "pending";
    status.textContent=turn.error ? (explanations[turn.error] || "This message needs attention. Its text and files are kept.") :
      turn.local ? (turn.phase==="uploading" ? "Uploading files…" : turn.phase==="checking" ? "Checking your saved message…" : "Sending…") :
      turn.status==="awaiting_dispatch" ? "Your message is saved. Preparing the reply…" : "Radhouse is replying…";
    block.append(status);
    if (turn.local && turn.phase==="uploading") { const progress=document.createElement("p"); progress.className="sending-files"; progress.dataset.uploadProgress=""; block.append(progress); }
    if (turn.local && turn.error) {
      const retry=document.createElement("button"); retry.className="retry"; retry.textContent="Retry message"; retry.addEventListener("click",retryOutgoing); block.append(retry);
      if (!turn.transmitted) { const edit=document.createElement("button"); edit.className="retry"; edit.textContent="Edit message"; edit.addEventListener("click",editOutgoing); block.append(edit); }
    } else if (!turn.local && turn.status==="awaiting_dispatch" && turn.error!=="reply_recovery_required") {
      const retry=document.createElement("button"); retry.className="retry"; retry.textContent="Retry message"; retry.addEventListener("click",() => retrySaved(turn.request_id)); block.append(retry);
    }
  }
  return block;
}
function scrollAnchor() {
  const top=$("history-pane").getBoundingClientRect().top;
  for (const node of $("messages").children) { const r=node.getBoundingClientRect(); if (r.bottom>top) return {id:node.dataset.requestId,offset:r.top-top}; }
  return null;
}
function updateLatest() { $("latest").hidden=followingLatest || $("history-pane").scrollHeight<=$("history-pane").clientHeight+80; }
function renderHistory({older=false,latest=false}={}) {
  const pane=$("history-pane"), anchor=scrollAnchor();
  const ordered=[...turns.values()].sort((a,b) => a.seq-b.seq);
  if (outbox) ordered.push({...outbox,local:true});
  let preceding=null;
  const current=new Set();
  for (const turn of ordered) {
    current.add(turn.request_id);
    const signature=JSON.stringify({...turn,attachments:turn.attachments?.map(file => ({...file,blob:undefined}))});
    let saved=turnNodes.get(turn.request_id);
    if (!saved || saved.signature!==signature) {
      const node=makeTurn(turn);
      if (saved) {
        const open=[...saved.node.querySelectorAll("details")].map(d => d.open);
        [...node.querySelectorAll("details")].forEach((d,i) => { d.open=!!open[i]; }); saved.node.replaceWith(node);
      }
      saved={signature,node}; turnNodes.set(turn.request_id,saved);
    }
    const expected=preceding ? preceding.nextSibling : $("messages").firstChild;
    if (saved.node!==expected) $("messages").insertBefore(saved.node,expected);
    preceding=saved.node;
  }
  for (const [id,saved] of turnNodes) if (!current.has(id)) { saved.node.remove(); turnNodes.delete(id); }
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
function controls() {
  const pending=pendingTurn(), tooLong=!messageFits($("message").value), hasContent=!!($("message").value.trim() || draft.attachments.length);
  $("send").disabled=busy || filesLoading || !!pending || !!outbox || tooLong || !hasContent || openingHistory;
  $("attach").disabled=filesLoading; $("attach-text").disabled=filesLoading; $("long-text").hidden=!tooLong;
  $("send").textContent=busy ? "Sending…" : "Send ↗";
  $("reply-status").textContent=filesLoading ? "Adding files…" : busy ? (outbox?.phase==="uploading" ? "Uploading…" : "Sending…") : pending ? "Radhouse is replying…" : "";
  document.querySelectorAll(".retry,#notice-action").forEach(button => { button.disabled=busy || openingHistory; });
  resizeMessage();
}
function render(options) { renderHistory(options); renderDraft(); controls(); }
function migrateFile(file) {
  if (file.blob instanceof Blob) return {...file,file_id:file.file_id || crypto.randomUUID()};
  if (file.content===undefined) return file; // Text-only recovery preserves immutable file references, never omits them.
  const bytes=Uint8Array.from(atob(file.content),c => c.charCodeAt(0));
  return {...file,content:undefined,blob:new Blob([bytes],{type:file.type}),file_id:crypto.randomUUID()};
}
function recoveredSnapshot(stored,fallback) {
  const revision=value => Number.isSafeInteger(value?.revision) && value.revision>=0 ? value.revision : 0;
  draftRevision=Math.max(draftRevision,revision(stored),revision(fallback));
  if (!fallback || stored && revision(stored)>=revision(fallback)) return stored;
  // The fallback owns newer text/request state; IndexedDB may still hold the
  // same immutable originals after a failed write. Never restore removed files.
  const originals=new Map([...(stored?.attachments || []),...(stored?.outbox?.attachments || [])]
    .filter(file => file.file_id && file.blob instanceof Blob).map(file => [file.file_id,file.blob]));
  const files=values => (values || []).map(file => originals.has(file.file_id) ? {...file,blob:originals.get(file.file_id)} : file);
  return {...fallback,attachments:files(fallback.attachments),
    outbox:fallback.outbox ? {...fallback.outbox,attachments:files(fallback.outbox.attachments)} : null};
}
async function openConversation() {
  const openingSession=session; openingHistory=true; followingLatest=true; olderLoaded=false; olderBefore=null;
  turns.clear(); turnNodes.clear(); $("messages").replaceChildren(); draftSignature=""; draft=emptyDraft(); outbox=null;
  $("login-view").hidden=true; $("chat-view").hidden=false; $("logout").hidden=false; $("loading").hidden=true;
  let stored, fallback;
  try { stored=await draftOperation(key()); } catch (_) {}
  try { fallback=JSON.parse(localStorage.getItem(key()) || "null"); } catch (_) {}
  const saved=recoveredSnapshot(stored,fallback);
  if (saved?.has_files && [...(saved.attachments || []),...(saved.outbox?.attachments || [])].some(file => !(file.blob instanceof Blob))) tell("draft_storage_unavailable",persist);
  if (session!==openingSession) return;
  if (saved && typeof saved.text==="string") {
    if (saved.version===2) { draft={text:saved.text,attachments:(saved.attachments || []).map(migrateFile)}; outbox=saved.outbox; }
    else if (saved.request_id) { outbox={text:saved.text,request_id:saved.request_id,attachments:(saved.attachments || []).map(migrateFile),transmitted:true,legacy:true}; }
    else { draft={text:saved.text,attachments:(saved.attachments || []).map(migrateFile)}; }
    if (outbox) {
      // Earlier text-only recovery records did not retain file IDs. Never retry these as a text-only message.
      if (saved.version!==2 && saved.has_files && !outbox.attachments.length) outbox.missing_files=true;
      outbox.attachments=outbox.attachments.map(migrateFile); outbox.phase="checking"; outbox.error=null;
    }
  }
  $("message").value=draft.text; render({latest:true});
  try { const data=await api("/chat/history"); if (session===openingSession) accept(data,false,true); }
  catch (error) { if (session===openingSession) tell(error.message,refreshHistory); }
  finally {
    if (session===openingSession) {
      openingHistory=false;
      if (outbox) { outbox.phase="failed"; outbox.error="network_error"; }
      await persist(); render(); if (!matchMedia("(pointer:coarse)").matches) $("message").focus();
    }
  }
}
async function refreshHistory() {
  if (busy || !session) return;
  try {
    const fresh=await api("/auth/session"); session=fresh; clearNotice();
    const data=await api("/chat/history"); accept(data);
  } catch (error) { if (session) tell(error.message,refreshHistory); }
}
function progress(file,loaded,total) {
  const box=outbox; if (!box) return;
  const target=document.querySelector("[data-upload-progress]");
  if (target) target.textContent=file.name+" · "+(total ? Math.round(loaded/total*100)+"% transferred" : sizeLabel(loaded)+" transferred");
}
async function uploadOriginal(file, sendingSession) {
  let receipt;
  try { receipt=await api("/chat/files/"+file.file_id); }
  catch (error) { if (error.status!==404) throw error; }
  if (session!==sendingSession) throw new Error("authentication_required");
  if (!receipt && !(file.blob instanceof Blob)) throw new Error("original_unavailable");
  if (!receipt) receipt=await new Promise((resolve,reject) => {
    const request=new XMLHttpRequest(); request.open("PUT","/chat/files/"+file.file_id+"?name="+encodeURIComponent(file.name));
    request.setRequestHeader("Content-Type","application/octet-stream"); request.setRequestHeader("X-Radhouse-CSRF",sendingSession.csrf_token);
    request.upload.onprogress=event => progress(file,event.loaded,event.lengthComputable ? event.total : 0);
    request.onerror=request.onabort=() => reject(new Error("network_error"));
    request.onload=() => {
      let value; try { value=JSON.parse(request.responseText); } catch (_) { value={}; }
      if (request.status>=200 && request.status<300) resolve(value);
      else { if (request.status===401) showLogin(true); const error=new Error(value.error || "file_storage_unavailable"); error.status=request.status; reject(error); }
    };
    progress(file,0,file.size); request.send(file.blob);
  });
  if (receipt.name!==file.name || receipt.size!==file.size) throw new Error("attachment_conflict");
  file.uploaded=true;
}
async function transmit(box) {
  if (busy || !session || outbox!==box) return;
  const sendingSession=session; busy=true; box.error=null; clearNotice(); box.phase="sending"; render({latest:true});
  try {
    await saveState();
    if (session!==sendingSession) return;
    if (box.legacy) {
      try { const data=await api("/chat/messages/"+box.request_id+"/retry",{}); if (session===sendingSession) accept(data); return; }
      catch (error) { if (error.status!==404) throw error; box.transmitted=false; }
    }
    if (box.missing_files) throw new Error("original_unavailable");
    for (const file of box.attachments) {
      box.phase="uploading"; render(); await uploadOriginal(file,sendingSession);
      if (session!==sendingSession) return;
      await saveState();
    }
    box.phase="sending"; box.transmitted=true; await saveState(); render();
    if (session!==sendingSession) return;
    const data=await api("/chat/messages",{request_id:box.request_id,text:box.text,attachments:box.attachments.map(a => a.file_id)});
    if (session===sendingSession) accept(data);
  } catch (error) {
    if (session===sendingSession && outbox===box) {
      box.phase="failed"; box.error=error.message;
      if ([413,422].includes(error.status)) box.transmitted=false;
      await persist();
      try { const data=await api("/chat/history"); if (session===sendingSession) accept(data); } catch (_) {}
    }
  } finally { busy=false; if (session===sendingSession) render(); }
}
function retryOutgoing() { if (outbox && !pendingTurn()) transmit(outbox); }
async function retrySaved(requestId) {
  if (busy || !session) return;
  const sendingSession=session; busy=true; clearNotice(); controls();
  try { const data=await api("/chat/messages/"+requestId+"/retry",{}); if (session===sendingSession) accept(data); }
  catch (error) { if (session===sendingSession) tell(error.message,refreshHistory); }
  finally { busy=false; if (session===sendingSession) render(); }
}
function editOutgoing() {
  if (!outbox || outbox.transmitted || busy) return;
  const missingFiles=outbox.missing_files;
  draft.text=[outbox.text,$("message").value].filter(Boolean).join("\n\n");
  draft.attachments=[...outbox.attachments,...draft.attachments]; outbox=null;
  $("message").value=draft.text; persist(); render(); if (missingFiles) tell("original_unavailable"); $("message").focus();
}
async function addFiles(fileList) {
  if (!session || filesLoading) return;
  const addingSession=session; filesLoading=true; clearNotice(); controls();
  try {
    draft.attachments.push(...[...fileList].map(file => ({name:file.name,blob:file,file_id:crypto.randomUUID(),kind:fileKind(file),type:file.type,size:file.size})));
    await saveState();
  } catch (error) { if (session===addingSession) tell(error.message,persist); }
  finally { filesLoading=false; if (session===addingSession) render(); }
}
$("attach").addEventListener("click",() => $("file-picker").click());
$("file-picker").addEventListener("change",event => { addFiles(event.target.files); event.target.value=""; });
$("attach-text").addEventListener("click",async () => {
  const text=$("message").value;
  await addFiles([new File([text],"pasted-text.txt",{type:"text/plain"})]);
  // Only clear after the file draft was successfully written.
  try {
    await saveState();
    if ($("message").value===text) { draft.text=""; $("message").value=""; }
    await saveState(); render(); $("message").focus();
  }
  catch (_) { tell("draft_storage_unavailable",persist); }
});
$("compose").addEventListener("paste",event => { const files=[...(event.clipboardData?.files || [])]; if (files.length) { event.preventDefault(); addFiles(files); } });
$("chat-view").addEventListener("dragover",event => { if ([...event.dataTransfer.types].includes("Files")) { event.preventDefault(); $("compose").classList.add("dragging"); } });
$("chat-view").addEventListener("dragleave",event => { if (!$("chat-view").contains(event.relatedTarget)) $("compose").classList.remove("dragging"); });
$("chat-view").addEventListener("drop",event => { event.preventDefault(); $("compose").classList.remove("dragging"); addFiles(event.dataTransfer.files); });
$("compose").addEventListener("submit",event => {
  event.preventDefault();
  if ($("send").disabled) return;
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
new ResizeObserver(entries => { $("chat-view").style.setProperty("--composer-height",entries[0].target.offsetHeight+14+"px"); if (followingLatest) $("history-pane").scrollTop=$("history-pane").scrollHeight; updateLatest(); }).observe($("compose"));
$("older").addEventListener("click",async () => {
  const readingSession=session;
  try { const data=await api("/chat/history?before="+olderBefore); if (session===readingSession) accept(data,true); }
  catch (error) { if (session===readingSession) tell(error.message,refreshHistory); }
});
$("login-form").addEventListener("submit",async event => {
  event.preventDefault(); clearNotice(); const button=event.submitter; button.disabled=true;
  try { session=await api("/auth/login",{username:$("username").value,password:$("password").value,totp_code:$("totp").value,remember_browser:$("remember").checked}); $("password").value=""; $("totp").value=""; await openConversation(); }
  catch (error) { tell(error.message); } finally { button.disabled=false; }
});
$("logout").addEventListener("click",async () => { try { await saveState(); await api("/auth/logout",{}); showLogin(); } catch (error) { tell(error.message); } });
setInterval(async () => {
  if (!session || !pendingTurn() || busy || polling) return;
  polling=true; const readingSession=session;
  try { const data=await api("/chat/reply"); if (session===readingSession) accept(data); }
  catch (error) { if (session===readingSession) tell(error.message,refreshHistory); }
  finally { polling=false; }
},2000);
(async () => {
  try { session=await api("/auth/session",undefined,true); await openConversation(); }
  catch (error) { if (error.status!==401) { showLogin(); tell(error.message); } }
})();
