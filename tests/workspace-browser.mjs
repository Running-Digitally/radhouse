// Real product shell with HTTP fixtures; no owner data or production connections.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import assert from "node:assert/strict";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const root=new URL("../src/radhouse/chat/static/",import.meta.url), origin="http://127.0.0.1:61882";
const session={username:"fixture-owner",csrf_token:"fixture",features:{terminal:true,about_you:true,inference:true,browser:false,browser_control:false}};
const caps={state:"supported",choices:["low","high"],can_disable:true,can_enable:true};
const catalog={schema:"radhouse.inference.v1",state:"available",checked_at:"2026-10-08T19:00:00Z",
  engine:{id:"fixture-engine",label:"Fixture engine"},current_model:"fixture-alpha",
  models:[{id:"fixture-alpha",label:"Fixture Alpha",available:true,reason:null,thinking:caps},
    {id:"fixture-beta",label:"Fixture Beta",available:true,reason:null,thinking:{state:"unknown",choices:[],can_disable:false,can_enable:false}}]};
const binding={terminal_id:"d282655b-3e6c-4205-bfca-f5eeea345bbf",generation:"8c5688b8-4a33-455d-a028-d07a2d826301",attach_epoch:1};
let opened=false,openCount=0,lastSequence=0,sent=[],turns=[],output="fixture@agent:~$ hello 🌿\r\n",capturing=null,releaseCapture;
const status=()=>({state:opened?"open":"closed",...(opened?binding:{terminal_id:null,generation:null,attach_epoch:0}),
  next_cursor:Buffer.byteLength(output),last_sequence:lastSequence,last_outcome:lastSequence?"written":"none"});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1280,height:900}}),page=await context.newPage(),errors=[];
page.on("pageerror",error=>errors.push(error.message));
await context.route(`${origin}/**`,async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  const json=async value=>route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(value)});
  if(path==="/auth/session")return json(session);
  if(path==="/chat/history" || path==="/chat/reply")return json({turns,older_before:null});
  if(path==="/chat/inference")return json(catalog);
  if(path==="/chat/about-you")return json({schema:"radhouse.saved-memory.v1",checked_at:"2026-10-08T19:00:00Z",sources:[
    {target:"user",source_filename:"USER.md",state:"available",entries:["Enjoys careful work.\n<script>window.unwanted=true</script>"],file_modified_at:null,complete:true},
    {target:"memory",source_filename:"MEMORY.md",state:"missing",entries:[],file_modified_at:null,complete:true}]});
  if(path.startsWith("/chat/terminal/")){
    const body=request.postDataJSON();assert.equal(request.headers()["x-radhouse-csrf"],"fixture");
    assert.equal(request.headers()["x-radhouse-browser-tab"],body.tab_id);
    const operation=path.split("/").at(-1);
    if(operation==="open"){opened=true;openCount++;return json(status());}
    if(operation==="status")return json(status());
    if(operation==="close"){opened=false;return json({...status(),...binding});}
    if(operation==="resize")return json(status());
    if(operation==="input"){lastSequence=body.sequence;output+=Buffer.from(body.data_b64,"base64").toString("utf8");return json(status());}
    if(operation==="output"){
      await new Promise(resolve=>setTimeout(resolve,60));
      const bytes=Buffer.from(output,"utf8"),data=bytes.subarray(body.cursor);
      return json({...status(),...binding,data_b64:data.toString("base64"),truncated:false});
    }
    if(operation==="context-scrub"){
      if(capturing)await capturing;
      const {tab_id,...value}=body;
      return json({kind:"terminal_excerpt",label:"Agent VM terminal",...value,text:value.text.replaceAll("fixture-secret","[REDACTED]")});
    }
  }
  if(path==="/chat/messages"){
    sent.push(request.postDataJSON());
    if(sent.length===1)return route.abort("failed");
    const body=sent.at(-1);turns=[{...body,seq:1,status:"completed",output:"Fixture reply",attachments:[],shared_files:[]}];
    return json({turns,older_before:null,accepted_request_id:body.request_id});
  }
  let filename=["/","/terminal","/about-you","/browser","/library"].includes(path)?"index.html":path.slice(1);
  if(path.startsWith("/workspace-assets/"))filename=path.slice("/workspace-assets/".length);
  if(path.startsWith("/workspace-vendor/xterm/"))filename="vendor/xterm/"+path.split("/").at(-1);
  if(!/^[a-zA-Z0-9./-]+$/.test(filename))return route.fulfill({status:404,body:""});
  try{const data=await readFile(new URL(filename,root));return route.fulfill({status:200,
    contentType:filename.endsWith(".js")?"text/javascript":filename.endsWith(".css")?"text/css":"text/html; charset=utf-8",body:data});}
  catch{return route.fulfill({status:404,body:""});}
});
try{
  await page.goto(origin+"/terminal");
  await expect(page.getByRole("link",{name:"Terminal",exact:true}).locator("svg")).toHaveAttribute("data-icon","terminal");
  await expect(page.getByRole("link",{name:"About You",exact:true}).locator("svg")).toHaveAttribute("data-icon","about-you");
  await expect(page.getByRole("button",{name:"Open terminal",exact:true})).toBeVisible();assert.equal(openCount,0);
  await expect(page.getByRole("button",{name:"Open terminal",exact:true}).locator("svg")).toHaveAttribute("data-icon","terminal");
  await page.getByRole("button",{name:"Open terminal",exact:true}).click();
  await expect(page.locator(".xterm")).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>ownerTerminal.term?.buffer.active.getLine(0)?.translateToString(true)||"")).toContain("hello");
  await page.locator(".xterm-helper-textarea").pressSequentially("pwd\r");
  await expect.poll(()=>lastSequence).toBeGreaterThan(0);
  await page.getByRole("link",{name:"Chat",exact:true}).click();assert.equal(openCount,1);
  await expect(page.locator("#terminal-context-chip .rh-icon[data-icon='terminal-context']")).toBeVisible();
  await expect(page.getByRole("button",{name:"Refresh models",exact:true}).locator("svg")).toHaveAttribute("data-icon","refresh");
  await page.getByLabel("Model",{exact:true}).selectOption("fixture-alpha");
  await page.getByLabel("Thinking",{exact:true}).selectOption("high");
  await page.locator("#use-terminal-context").check();
  await page.locator("#message").fill("Explain the output");
  capturing=new Promise(resolve=>releaseCapture=resolve);
  await page.locator("#send").click();await expect(page.locator("#message")).toBeDisabled();
  const dropped=await page.evaluate(async()=>{
    const data=new DataTransfer();data.items.add(new File(["late"],"late.txt",{type:"text/plain"}));
    document.getElementById("chat-view").dispatchEvent(new DragEvent("drop",{bubbles:true,dataTransfer:data}));
    return document.querySelectorAll("#draft-files .attachment").length;
  });assert.equal(dropped,0);
  releaseCapture();capturing=null;
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeVisible();
  const first=structuredClone(sent[0]);assert.equal(first.inference.model,"fixture-alpha");
  assert.equal(first.inference.thinking,"high");assert.match(first.terminal_context.text,/hello 🌿/);
  output+="a later terminal result\r\n";
  await page.getByLabel("Model",{exact:true}).selectOption("fixture-beta");
  await page.getByRole("button",{name:"Retry message",exact:true}).click();
  await expect(page.getByText("Fixture reply",{exact:true})).toBeVisible();assert.deepEqual(sent[1],first);
  await page.getByRole("link",{name:"About You",exact:true}).click();
  await expect(page.getByRole("button",{name:"Refresh",exact:true}).locator("svg")).toHaveAttribute("data-icon","refresh");
  await expect(page.getByText("Enjoys careful work.",{exact:false})).toBeVisible();
  assert.equal(await page.evaluate(()=>window.unwanted),undefined);
  await page.getByRole("link",{name:"Terminal",exact:true}).click();assert.equal(openCount,1);
  await page.reload();await expect(page.locator(".xterm")).toBeVisible();assert.equal(openCount,1);
  // A delayed capture from a signed-out session must not fence the new login,
  // or clear the new capture's edit/file guard when its stale response arrives.
  await page.getByRole("link",{name:"Chat",exact:true}).click();
  await page.locator("#use-terminal-context").check();
  await page.locator("#message").fill("Old session capture");
  let releaseOld;
  capturing=new Promise(resolve=>releaseOld=resolve);
  const staleResponse=page.waitForResponse(response=>response.url().endsWith("/chat/terminal/context-scrub"));
  await page.locator("#send").click();await expect(page.locator("#message")).toBeDisabled();
  await page.evaluate(async()=>{showLogin(true);session=await api("/auth/session",undefined,true);await openConversation();});
  await expect(page.locator("#message")).toBeEnabled();
  await page.getByRole("link",{name:"Terminal",exact:true}).click();
  await expect(page.locator(".xterm")).toBeVisible();
  await page.getByRole("link",{name:"Chat",exact:true}).click();
  await page.locator("#use-terminal-context").check();
  await page.locator("#message").fill("New session capture");
  let releaseNew;
  capturing=new Promise(resolve=>releaseNew=resolve);
  await page.locator("#send").click();await expect(page.locator("#message")).toBeDisabled();
  releaseOld();await staleResponse;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.evaluate(()=>capturingContext),true);
  const staleDrop=await page.evaluate(()=>{
    const data=new DataTransfer();data.items.add(new File(["late"],"stale-session.txt",{type:"text/plain"}));
    document.getElementById("chat-view").dispatchEvent(new DragEvent("drop",{bubbles:true,dataTransfer:data}));
    return document.querySelectorAll("#draft-files .attachment").length;
  });assert.equal(staleDrop,0);
  releaseNew();capturing=null;
  await expect.poll(()=>sent.length).toBe(3);
  assert.equal(sent[2].text,"New session capture");
  assert.equal(sent.some(body=>body.text==="Old session capture"),false);
  await page.getByRole("link",{name:"Terminal",exact:true}).click();
  for(const width of [390,320]) {
    await page.setViewportSize({width,height:844});
    for(const path of ["/terminal","/"]) {
      await page.evaluate(path=>showPage(path),path);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${path} overflows at ${width}px`);
    }
  }
  await page.evaluate(()=>showPage("/terminal"));
  await expect(page.getByRole("button",{name:"Close terminal",exact:true}).locator("svg")).toHaveAttribute("data-icon","close");
  await page.getByRole("button",{name:"Close terminal",exact:true}).click();
  await expect(page.getByRole("button",{name:"Open terminal",exact:true})).toBeVisible();assert.equal(opened,false);
  assert.deepEqual(errors,[]);console.log("Workspace Chromium integration passed: lazy terminal, navigation, frozen model/context retry, capture/drop and relogin guards, notes and mobile.");
}finally{await browser.close();}
