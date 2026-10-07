import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const {chromium, expect: baseExpect} = await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const expect = baseExpect.configure({timeout:10000});
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport:{width:1200,height:950},permissions:["clipboard-read","clipboard-write"]});
const page = await context.newPage(); const errors = [];
async function screenshot(options) {
  for (let attempt=0; ; attempt++) {
    try { return await page.screenshot(options); }
    catch (error) { if (attempt >= 2 || !error.message.includes("Unable to capture screenshot")) throw error; }
  }
}
page.on("pageerror", error => errors.push(error.message));
try {
  await page.goto(process.env.RADHOUSE_BROWSER_ORIGIN);
  await expect(page.locator("#login-view")).toBeVisible();
  await expect(page.locator("#login-notice")).toBeHidden();
  await screenshot({path:process.env.RADHOUSE_SCREENSHOT.replace(".png","-login.png"),fullPage:true});
  await page.locator("#username").fill("alice");
  await page.locator("#password").fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.locator("#totp").fill(process.env.RADHOUSE_TEST_TOTP);
  await page.getByRole("button", {name:"Sign in",exact:true}).click();
  await expect(page.locator("#chat-view")).toBeVisible();
  await screenshot({path:process.env.RADHOUSE_SCREENSHOT.replace(".png","-empty.png"),fullPage:true});
  await page.locator("#message").fill("Help me think through a simpler morning routine.");
  await page.locator("#send").click();
  await expect(page.locator(".assistant")).toHaveCount(1);
  await expect(page.locator(".assistant")).toContainText("<script>window.chatInjected=true</script>");
  if (await page.evaluate(() => window.chatInjected)) throw new Error("Unsafe HTML rendering");
  await expect(page.locator(".answer strong")).toHaveText("Small step");
  await expect(page.locator(".answer ul li")).toHaveCount(2);
  await expect(page.locator(".answer pre code")).toHaveText("print('hello')");
  await expect(page.locator(".answer a")).toHaveAttribute("href","https://example.com/guide");
  await expect(page.locator(".answer a")).toHaveAttribute("rel","noopener noreferrer");
  await expect(page.locator(".answer script,.answer img,.answer iframe,.answer a[href^='javascript:']")).toHaveCount(0);
  await page.getByRole("button",{name:"Copy code",exact:true}).click();
  if (await page.evaluate(() => navigator.clipboard.readText()) !== "print('hello')") throw new Error("Incorrect code copy");
  await page.getByRole("button",{name:"Copy answer",exact:true}).click();
  if (!(await page.evaluate(() => navigator.clipboard.readText())).includes("<script>window.chatInjected")) throw new Error("Incorrect answer copy");
  await page.reload();
  await expect(page.locator(".assistant")).toHaveCount(1);
  await page.locator("#message").fill("What is the smallest change I can start with?");
  await page.locator("#message").press("Enter");
  await expect(page.locator(".assistant")).toHaveCount(2);
  await page.route("**/chat/messages", async route => { const response = await route.fetch(); console.log("Lost-response fixture status", response.status()); await route.abort("failed"); }, {times:1});
  await page.locator("#message").fill("Keep this message even if the connection drops.");
  await page.locator("#send").click();
  await expect(page.locator(".assistant")).toHaveCount(3);
  await page.reload();
  await expect(page.locator(".turn")).toHaveCount(3);
  await page.route("**/chat/messages", async route => { await route.fetch(); await route.abort("failed"); }, {times:1});
  await page.route("**/chat/history", async route => { await route.abort("failed"); }, {times:1});
  await page.locator("#message").fill("Recover this even when the history check also fails.");
  await page.locator("#send").click();
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeEnabled();
  await expect(page.locator("#message")).toBeEnabled();
  await expect(page.locator("#message")).toHaveValue("");
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("radhouse-chat-draft:alice")));
  if (!saved.outbox.request_id || !saved.outbox.text.includes("history check")) throw new Error("Lost recovery request identity");
  await page.locator("#message").fill("Keep my next draft separate from the outgoing message.");
  await page.reload();
  await expect(page.locator(".assistant")).toHaveCount(4);
  await expect(page.locator("#message")).toHaveValue("Keep my next draft separate from the outgoing message.");
  await page.locator("#message").fill("");
  // File picker, durable unsent draft, removal, audio and attachment-only send.
  const fixtures = process.env.RADHOUSE_ATTACHMENT_FIXTURES;
  await page.locator("#file-picker").setInputFiles([fixtures+"/diagram.png",fixtures+"/plan.pdf",fixtures+"/plan.docx"]);
  await expect(page.locator("#draft-files .attachment")).toHaveCount(3);
  await expect(page.locator("#draft-files img:not(.document-icon)")).toBeVisible();
  await page.reload();
  await expect(page.locator("#draft-files .attachment")).toHaveCount(3);
  await page.getByRole("button",{name:"Remove plan.docx",exact:true}).click();
  await page.locator("#file-picker").setInputFiles(fixtures+"/voice.wav");
  await expect(page.locator("#draft-files audio")).toBeHidden();
  await page.locator("#draft-files summary").filter({hasText:"Play audio"}).click();
  await expect(page.locator("#draft-files audio")).toBeVisible();
  await expect(page.locator("#attach")).toBeEnabled();
  await screenshot({path:process.env.RADHOUSE_SCREENSHOT.replace(".png","-attachments.png"),fullPage:true});
  await page.route("**/chat/messages",async route => { await route.fetch(); await route.abort("failed"); },{times:1});
  await page.route("**/chat/history",async route => { await route.abort("failed"); },{times:1});
  await page.locator("#send").click();
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeEnabled();
  await expect(page.getByRole("button",{name:"Remove voice.wav",exact:true})).toHaveCount(0);
  await expect(page.locator("#attach")).toBeEnabled();
  await page.reload();
  await expect(page.locator(".assistant")).toHaveCount(5);
  await expect(page.locator("#draft-files .attachment")).toHaveCount(0);
  await expect(page.locator(".turn .attachment")).toHaveCount(3);
  await expect(page.locator(".turn audio")).toBeHidden();
  await page.locator(".turn summary").filter({hasText:"Play audio"}).click();
  await expect(page.locator(".turn audio")).toBeVisible();
  await page.locator(".turn summary").filter({hasText:"Audio transcript"}).click();
  await expect(page.locator('.turn details[data-detail="transcript"]')).toContainText("simulated voice note");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link",{name:"plan.pdf",exact:true}).click();
  const download = await downloadEvent;
  if (!(await readFile(await download.path())).equals(await readFile(fixtures+"/plan.pdf"))) throw new Error("Changed original attachment");
  // Exercise the drop handler using browser-native File and DataTransfer objects.
  const transfer = await page.evaluateHandle(() => {
    const value = new DataTransfer(); value.items.add(new File(["A dropped text note"],"dropped.txt",{type:"text/plain"})); return value;
  });
  await page.locator("#compose").dispatchEvent("drop",{dataTransfer:transfer});
  await expect(page.locator("#draft-files")).toContainText("dropped.txt");
  await page.locator("#send").click();
  await expect(page.locator(".assistant")).toHaveCount(6);
  await page.reload();
  await expect(page.locator(".turn .attachment")).toHaveCount(4);
  // Above former file/aggregate/request limits; binary drafts survive reload.
  await page.locator("#file-picker").setInputFiles([fixtures+"/large.bin",fixtures+"/notes.txt",fixtures+"/plan.pdf",fixtures+"/plan.docx",fixtures+"/voice.wav"]);
  await expect(page.locator("#draft-files .attachment")).toHaveCount(5);
  await page.reload();
  await expect(page.locator("#draft-files .attachment")).toHaveCount(5);
  await page.route("**/chat/files/*",async route => {
    if (route.request().method() === "PUT") { await route.fetch(); await route.abort("failed"); }
    else await route.continue();
  },{times:2}); // GET receipt lookup, then lost upload acknowledgement.
  await page.locator("#send").click();
  await expect(page.locator(".turn-error")).toContainText("lost the connection",{timeout:30000});
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeEnabled();
  await expect(page.getByRole("button",{name:"Edit message",exact:true})).toBeEnabled();
  await page.reload();
  await expect(page.locator("#draft-files .attachment")).toHaveCount(0);
  await expect(page.locator(".turn").last().locator(".attachment")).toHaveCount(5);
  const uploadIds = [];
  page.on("request",request => { if (request.method() === "PUT") uploadIds.push(request.url()); });
  await page.getByRole("button",{name:"Retry message",exact:true}).click();
  await expect(page.locator(".assistant")).toHaveCount(7);
  if (uploadIds.some(url => url.includes("name=large.bin"))) throw new Error("Lost upload acknowledgement caused a duplicate large transfer");
  await expect(page.locator(".turn .attachment")).toHaveCount(9);
  await expect(page.locator(".turn .attachment").filter({hasText:"large.bin"})).toContainText("Original saved; assistant access pending");
  const largeDownload = page.waitForEvent("download");
  await page.getByRole("link",{name:"large.bin",exact:true}).click();
  if (!(await readFile(await (await largeDownload).path())).equals(await readFile(fixtures+"/large.bin"))) throw new Error("Changed large original");
  // A failed IndexedDB write must not let an older readable record replace
  // newer fallback text, and matching binary originals must remain available.
  await page.locator("#file-picker").setInputFiles(fixtures+"/notes.txt");
  await expect(page.locator("#draft-files")).toContainText("notes.txt");
  await page.locator("#message").fill("Older draft with a retained original.");
  await page.evaluate(async () => { await draftWrites; window.originalDraftOperation=draftOperation;
    draftOperation=(storageKey,value) => value===undefined ? window.originalDraftOperation(storageKey) : Promise.reject(new Error("draft_storage_unavailable")); });
  await page.locator("#message").fill("Newer draft survives the failed storage write.");
  await expect(page.locator("#notice")).toContainText("couldn’t save this draft");
  await page.reload();
  await expect(page.locator("#message")).toHaveValue("Newer draft survives the failed storage write.");
  if (await page.evaluate(() => draft.attachments[0].blob.text())!=="A simple plan") throw new Error("Fallback recovery lost the retained original");
  // The same reconciliation must retain an outgoing request, rather than
  // reintroducing the old unsent draft or creating a second request identity.
  const recoveredRequest=await page.evaluate(async () => {
    await draftWrites; window.originalDraftOperation=draftOperation;
    draftOperation=(storageKey,value) => value===undefined ? window.originalDraftOperation(storageKey) : Promise.reject(new Error("draft_storage_unavailable"));
    outbox={request_id:crypto.randomUUID(),text:$("message").value,attachments:draft.attachments,transmitted:false};
    draft=emptyDraft(); $("message").value="A separate next draft.";
    try { await saveState(); } catch (_) {}
    return outbox.request_id;
  });
  await page.reload();
  await expect(page.locator("#message")).toHaveValue("A separate next draft.");
  if (await page.evaluate(() => outbox.request_id)!==recoveredRequest) throw new Error("Fallback recovery changed the outgoing request");
  if (await page.evaluate(() => outbox.attachments[0].blob.text())!=="A simple plan") throw new Error("Outgoing fallback lost the retained original");
  await page.getByRole("button",{name:"Edit message",exact:true}).click();
  await page.getByRole("button",{name:"Remove notes.txt",exact:true}).click();
  // Long text is preserved verbatim, and conversion is an explicit owner action.
  const longText="A long pasted line — 😀\n".repeat(1100);
  await page.locator("#message").fill(longText);
  await expect(page.locator("#message")).toHaveValue(longText);
  await expect(page.locator("#long-text")).toBeVisible();
  await expect(page.locator("#send")).toBeDisabled();
  await page.reload();
  await expect(page.locator("#message")).toHaveValue(longText);
  await page.evaluate(() => { window.originalDraftOperation=draftOperation; window.holdDraftWrite=true;
    draftOperation=async (storageKey,value) => {
      if (value!==undefined && window.holdDraftWrite) await new Promise(resolve => { window.releaseDraftWrite=resolve; });
      return window.originalDraftOperation(storageKey,value);
    }; });
  await page.getByRole("button",{name:"Attach as text file",exact:true}).click();
  await expect.poll(() => page.evaluate(() => typeof window.releaseDraftWrite)).toBe("function");
  const editedLongText=longText+"Edits typed while the file conversion is saving.";
  await page.locator("#message").fill(editedLongText);
  await page.evaluate(() => { window.holdDraftWrite=false; window.releaseDraftWrite(); });
  await expect(page.locator("#draft-files")).toContainText("pasted-text.txt");
  await expect(page.locator("#message")).toHaveValue(editedLongText);
  await page.reload();
  await expect(page.locator("#message")).toHaveValue(editedLongText);
  // Unchanged text still clears normally; retain that file for the download proof.
  await page.getByRole("button",{name:"Remove pasted-text.txt",exact:true}).click();
  await page.locator("#message").fill(longText);
  await page.getByRole("button",{name:"Attach as text file",exact:true}).click();
  await expect(page.locator("#message")).toHaveValue("");
  await expect(page.locator("#draft-files")).toContainText("pasted-text.txt");
  // Hold the first acknowledgement: outgoing text is visible immediately and a next draft stays editable.
  let releaseSend;
  const holdSend=new Promise(resolve => { releaseSend=resolve; });
  await page.route("**/chat/messages",async route => { await holdSend; await route.continue(); },{times:1});
  await page.evaluate(() => {
    window.uploadProgressSeen=[];
    new MutationObserver(() => {
      const text=document.querySelector('[data-upload-progress]')?.textContent;
      if (text && window.uploadProgressSeen.length<100) window.uploadProgressSeen.push(text);
    }).observe(document.querySelector('#messages'),{subtree:true,childList:true,characterData:true});
  });
  await page.locator("#message").fill("Read this pasted text.");
  await page.locator("#send").click();
  await expect(page.locator(".turn").last()).toContainText("Read this pasted text.");
  await expect(page.locator("#message")).toBeEnabled();
  await expect(page.locator("#attach")).toBeEnabled();
  await page.locator("#message").fill("My next draft survives this reply.");
  await page.locator("#file-picker").setInputFiles(fixtures+"/notes.txt");
  await expect(page.locator("#draft-files")).toContainText("notes.txt");
  releaseSend();
  await expect(page.locator(".assistant")).toHaveCount(8);
  if (!(await page.evaluate(() => window.uploadProgressSeen)).some(text => /pasted-text.txt.*[1-9]\d*% transferred/.test(text))) throw new Error("No byte upload progress reported");
  await expect(page.locator("#message")).toHaveValue("My next draft survives this reply.");
  await page.reload();
  await expect(page.locator("#message")).toHaveValue("My next draft survives this reply.");
  await expect(page.locator("#draft-files")).toContainText("notes.txt");
  const pastedDownload=page.waitForEvent("download");
  await page.getByRole("link",{name:"pasted-text.txt",exact:true}).click();
  if ((await readFile(await (await pastedDownload).path())).toString("utf8")!==longText) throw new Error("Long paste changed");
  // Re-authentication retains both text and binary draft, and ordinary sign-out has no error banner.
  await page.route("**/chat/files/*",route => route.fulfill({status:401,contentType:"application/json",body:JSON.stringify({error:"authentication_required"})}),{times:1});
  await page.locator("#send").click();
  await expect(page.locator("#login-view")).toBeVisible();
  await expect(page.locator("#login-notice")).toContainText("Sign in again");
  await page.locator("#password").fill(process.env.RADHOUSE_TEST_PASSWORD);
  await page.locator("#totp").fill(process.env.RADHOUSE_TEST_NEXT_TOTP);
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeEnabled();
  await expect(page.locator(".turn").last()).toContainText("My next draft survives this reply.");
  await page.getByRole("button",{name:"Edit message",exact:true}).click();
  await expect(page.locator("#message")).toHaveValue("My next draft survives this reply.");
  await expect(page.locator("#draft-files")).toContainText("notes.txt");
  // Migrate an earlier text-only recovery record without silently dropping its unknown files.
  await page.evaluate(async () => {
    const db=await new Promise(resolve => { const request=indexedDB.open('radhouse-chat-drafts',1); request.onsuccess=() => resolve(request.result); });
    await new Promise(resolve => { const tx=db.transaction('drafts','readwrite'); tx.objectStore('drafts').delete('radhouse-chat-draft:alice'); tx.oncomplete=resolve; });
    localStorage.setItem('radhouse-chat-draft:alice',JSON.stringify({text:'Legacy outgoing message with an unavailable original.',request_id:crypto.randomUUID(),has_files:true}));
  });
  let legacyPosts=0;
  const countLegacyPosts=request => { if (request.method()==='POST' && new URL(request.url()).pathname==='/chat/messages') legacyPosts++; };
  page.on('request',countLegacyPosts);
  await page.reload();
  await page.getByRole('button',{name:'Retry message',exact:true}).click();
  await expect(page.locator('.turn-error')).toContainText('unsent original');
  if (legacyPosts) throw new Error('Legacy recovery silently omitted unavailable originals');
  await page.getByRole('button',{name:'Edit message',exact:true}).click();
  await expect(page.locator('#message')).toHaveValue('Legacy outgoing message with an unavailable original.');
  await expect(page.locator('#notice')).toContainText('attach the file again');
  page.off('request',countLegacyPosts);
  // History owns the scroll, the composer stays onscreen, and older pages retain a reading anchor.
  const history=await context.request.get(process.env.RADHOUSE_BROWSER_ORIGIN+"/chat/history");
  const recent=(await history.json()).turns;
  const fixtureTurns=Array.from({length:70},(_,i) => ({...recent[0],request_id:"history-fixture-"+i,seq:i+1,text:"History fixture "+i,attachments:[]}));
  await page.route("**/chat/history*",route => {
    const before=new URL(route.request().url()).searchParams.get("before");
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({turns:before ? fixtureTurns.slice(0,20) : fixtureTurns.slice(20),older_before:before ? null : 21})});
  });
  await page.reload();
  await expect(page.locator(".turn")).toHaveCount(50);
  const pane=page.locator("#history-pane");
  await expect.poll(() => pane.evaluate(e => e.scrollHeight-e.scrollTop-e.clientHeight)).toBeLessThan(80);
  await pane.evaluate(e => { e.scrollTop=0; });
  await expect(page.locator("#latest")).toBeVisible();
  const anchor=page.locator('[data-request-id="history-fixture-20"]');
  const originalTop=await anchor.evaluate(e => e.getBoundingClientRect().top);
  await page.locator("#older").click();
  await expect(page.locator(".turn")).toHaveCount(70);
  if (Math.abs(await anchor.evaluate(e => e.getBoundingClientRect().top)-originalTop)>2) throw new Error("Older page lost reading position");
  await page.locator("#message").fill("Typing should not jump the conversation.");
  if (Math.abs(await anchor.evaluate(e => e.getBoundingClientRect().top)-originalTop)>2) throw new Error("Typing lost reading position");
  await page.locator("#latest").click();
  await expect.poll(() => pane.evaluate(e => e.scrollHeight-e.scrollTop-e.clientHeight)).toBeLessThan(80);
  await page.unroute("**/chat/history*");
  await page.reload();
  await expect(page.locator(".assistant")).toHaveCount(8);
  await screenshot({path:process.env.RADHOUSE_SCREENSHOT, fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await screenshot({path:process.env.RADHOUSE_SCREENSHOT.replace(".png","-mobile.png"),fullPage:true});
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error("Mobile horizontal overflow");
  const bounds=await page.locator("#compose").boundingBox();
  if (bounds.y<0 || bounds.y+bounds.height>844) throw new Error("Mobile composer outside viewport");
  await page.getByRole("button",{name:"Sign out"}).click();
  await expect(page.locator("#login-view")).toBeVisible();
  await expect(page.locator("#login-notice")).toBeHidden();
  await expect(page.locator(".turn")).toHaveCount(0);
  if (errors.length) throw new Error(errors.join("; "));
  console.log("PASS: real authentication and recovery; safe formatting/copy; long-paste exact download; separate next draft during send and reload; session expiry; pagination/reading anchor/latest; compact files; large transfer acknowledgement recovery; mobile composer and logout");
} catch (error) { console.log("Browser state", (await page.locator("main").innerText()).slice(-2000)); throw error; } finally { await browser.close(); }
