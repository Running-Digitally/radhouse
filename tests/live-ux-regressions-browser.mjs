// Real application controllers and DOM with disposable HTTP fixtures only.
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const root=new URL("../src/radhouse/chat/static/",import.meta.url),origin="http://127.0.0.1:61517";
const browser=await chromium.launch({headless:true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
const profile={schema:"radhouse.agent-profile.v1",revision:0,name:"",intro:"",theme:"hearthside",portrait:"ember",accent:"fern",surface:"paper",stateMotion:true,iconMotion:true,portraitSize:80};
const owner={username:"fixture",csrf_token:"fixture-csrf",management:{read:true,write:false},features:{browser:true,browser_control:true}};
const browserStatus={state:"live",generation:"fixture-generation",url:"https://example.org/",control:{mode:"human",revision:1,lease_id:"fixture-lease",lease_expires_at:Date.now()/1000+3600,next_sequence:1},page_context:{current:{url:"https://example.org/"}},can_return:true};
const infrastructure={checked_at:"2026-10-10T12:00:00Z",components:[],versions:{release_commit:"fixture",package:"fixture",python:"3.14"}};
const failures=[];
async function journey(name,run) {
  const context=await browser.newContext({viewport:{width:1280,height:900}}),page=await context.newPage(),errors=[];
  const state={profileFailure:false,receipt:"missing",posts:[],turns:[],uploads:new Map()};
  page.on("pageerror",error=>errors.push(error.message));
  await context.route(origin+"/**",async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname;
    const json=(value,status=200)=>route.fulfill({status,contentType:"application/json",body:JSON.stringify(value)});
    if(path==="/auth/session"||path==="/auth/login")return json(owner);
    if(path==="/auth/logout")return route.fulfill({status:204});
    if(path==="/chat/agent-profile")return state.profileFailure?json({error:"conversation_unavailable"},503):json(profile);
    if(path==="/chat/history"||path==="/chat/reply")return json({turns:state.turns,older_before:null});
    if(path==="/chat/browser")return json(browserStatus);
    if(path==="/chat/library")return json({files:[],next_cursor:null});
    if(path==="/chat/messages"){
      state.posts.push(request.postDataJSON());
      return json({error:"browser_context_changed"},409);
    }
    if(path.startsWith("/chat/messages/")) {
      if(state.receipt==="unavailable")return json({error:"conversation_unavailable"},503);
      if(state.receipt==="saved")return json({turn:{seq:1,...state.posts.at(-1),status:"completed",output:"Already received",attachments:[]}});
      return json({error:"message_not_found"},404);
    }
    if(path.startsWith("/chat/files/")){
      const id=path.split("/")[3];
      if(request.method()==="PUT")state.uploads.set(id,{file_id:id,name:url.searchParams.get("name"),size:request.postDataBuffer().length});
      return state.uploads.has(id)?json(state.uploads.get(id)):json({error:"attachment_not_found"},404);
    }
    if(path==="/admin/infrastructure")return json(infrastructure);
    if(path.startsWith("/chat/"))return json({error:"unavailable"},503);
    const file=["/","/library","/agent"].includes(path)?"index.html":path==="/infrastructure"?"admin.html"
      :path.startsWith("/workspace-assets/")?path.slice(18):path.startsWith("/workspace-vendor/")?"vendor/"+path.slice(18):path.slice(1);
    if(file.includes(".."))return route.fulfill({status:404});
    try {return route.fulfill({contentType:file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":file.endsWith(".json")?"application/json":file.endsWith(".webp")?"image/webp":"text/html",body:await readFile(new URL(file,root))});}
    catch {return route.fulfill({status:404});}
  });
  try {await run(page,state);assert.deepEqual(errors,[]);console.log("PASS "+name);}
  catch(error){failures.push(name+": "+error.message);console.error("FAIL "+name+": "+error.message.slice(0,450));}
  finally {await context.close();}
}
async function chat(page){await page.goto(origin+"/");await expect(page.locator("#message")).toBeEnabled();await expect.poll(()=>page.evaluate(()=>!!agentProfile.savedProfile)).toBe(true);}
async function rejectMessage(page,state,receipt){
  state.receipt=receipt;await chat(page);
  await page.locator("#message").fill("Keep this question and its original");
  await page.locator("#file-picker").setInputFiles({name:"original.txt",mimeType:"text/plain",buffer:Buffer.from("Original bytes")});
  await expect(page.locator("#send")).toBeEnabled();await page.locator("#send").click();
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeEnabled();
}
try {
  await journey("rejected browser context restores an editable message only after a missing receipt",async(page,state)=>{
    await rejectMessage(page,state,"missing");
    await expect(page.getByRole("button",{name:"Edit message",exact:true})).toBeVisible();
    await page.getByRole("button",{name:"Edit message",exact:true}).click();
    await expect(page.locator("#message")).toHaveValue("Keep this question and its original");
    assert.equal(await page.evaluate(()=>draft.attachments[0].blob.text()),"Original bytes");
    assert.equal(state.posts.length,1);
  });
  await journey("an unavailable receipt keeps the original retry identity",async(page,state)=>{
    await rejectMessage(page,state,"unavailable");
    await expect(page.getByRole("button",{name:"Edit message",exact:true})).toHaveCount(0);
    await page.getByRole("button",{name:"Retry message",exact:true}).click();
    await expect.poll(()=>state.posts.length).toBe(2);
    assert.equal(state.posts[0].request_id,state.posts[1].request_id);
  });
  await journey("an existing receipt reconciles without creating another message",async(page,state)=>{
    state.receipt="saved";await chat(page);await page.locator("#message").fill("Already sent");await page.locator("#send").click();
    await expect(page.locator(".answer")).toHaveText("Already received");
    await expect(page.getByRole("button",{name:"Edit message",exact:true})).toHaveCount(0);
    assert.equal(state.posts.length,1);assert.equal(await page.evaluate(()=>outbox),null);
  });
  await journey("brand navigation retains originals when browser storage fails",async(page)=>{
    await chat(page);await page.evaluate(()=>{window.sameDocument=true;draftOperation=async()=>{throw new Error("draft_storage_unavailable");};Storage.prototype.setItem=()=>{throw new Error("storage blocked");};});
    await page.locator("#message").fill("Unstored draft");
    await page.locator("#file-picker").setInputFiles({name:"unsaved.txt",mimeType:"text/plain",buffer:Buffer.from("Only in this tab")});
    await expect(page.locator("#notice")).toBeVisible();await expect(page.locator("#draft-files .attachment")).toHaveCount(1);
    await page.locator("#library-link").click();await expect(page.locator("#library-view")).toBeVisible();
    await page.locator("a.brand").click();await expect(page.locator("#chat-view")).toBeVisible();
    assert.equal(await page.evaluate(()=>window.sameDocument),true);
    await expect(page.locator("#message")).toHaveValue("Unstored draft");
    assert.equal(await page.evaluate(()=>draft.attachments[0].blob.text()),"Only in this tab");
  });
  await journey("profile loading can fail and recover after sign-out",async(page,state)=>{
    await chat(page);state.profileFailure=true;
    await page.evaluate(async()=>{agentProfile.clear();await agentProfile.load();});
    await page.locator("#agent-profile-link").click();
    await expect(page.getByRole("button",{name:"Try again",exact:true})).toBeVisible();
    state.profileFailure=false;await page.getByRole("button",{name:"Try again",exact:true}).click();
    await expect(page.locator("#agent-profile-name")).toBeEnabled();
  });
  await journey("expired authentication discards a delayed infrastructure response",async(page)=>{
    await page.goto(origin+"/infrastructure");await expect(page.locator("#content")).toBeVisible();
    await page.evaluate(async value=>{
      const original=request;let finish,started;const ready=new Promise(resolve=>{started=resolve;});
      request=(path,...args)=>path==="/admin/infrastructure"?new Promise(resolve=>{finish=resolve;started();}):original(path,...args);
      const pending=load();await ready;failed("authentication_required");finish(value);await pending;request=original;
    },infrastructure);
    await expect(page.locator("#content")).toBeHidden();await expect(page.locator("#notice-text")).toHaveText("Sign in to open this page.");
    assert.equal(await page.evaluate(()=>session),null);
  });
  await journey("a delayed browser action cannot change a reopened view",async(page)=>{
    await chat(page);
    const result=await page.evaluate(async()=>{
      const root=document.createElement("div");document.body.append(root);const releases=[];
      const view=new BrowserView(root,{persistent:true,request:()=>new Promise(resolve=>releases.push(resolve)),tab:()=>"fixture"});
      const ready=()=>{view.controlEnabled=true;view.active=true;view.generation="fixture";view.lease="lease";view.control={mode:"human",lease_id:"lease",revision:1,lease_expires_at:Date.now()/1000+60};view.displayedFrame={frame_id:"frame",viewport:{width:100,height:100}};};
      ready();const old=view._input("press",{key:"Tab"});view.stop();ready();
      const current=view._input("press",{key:"Enter"});
      releases[0]({outcome:"applied"});await old;
      const snapshot={requests:releases.length,pending:view.actionPending,unconfirmed:view.inputUnconfirmed};
      releases[1]?.({outcome:"applied"});await current;view.destroy();root.remove();return snapshot;
    });
    assert.deepEqual(result,{requests:2,pending:true,unconfirmed:false});
  });
  await journey("late polling cannot turn a cancelled follow-up back into a waiting one",async(page)=>{
    await chat(page);
    await page.evaluate(()=>{
      const saved={seq:1,request_id:"fixture-followup",text:"A cancelled follow-up",status:"cancelled",error:"followup_cancelled",attachments:[]};
      accept({turns:[saved],older_before:null});accept({turns:[{...saved,status:"waiting",error:null}],older_before:null});
    });
    await expect(page.getByText("Follow-up cancelled before it was sent.",{exact:true})).toBeVisible();
    await expect(page.getByRole("button",{name:"Cancel follow-up",exact:true})).toHaveCount(0);
  });
} finally {await browser.close();}
assert.deepEqual(failures,[]);
console.log("Eight live-app UX recovery regression journeys passed; synthetic data only.");
