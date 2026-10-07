// Main chat integration with one agent page's real CDP stream; synthetic API only.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect:baseExpect}=await import(moduleUrl);
const expect=baseExpect.configure({timeout:10000});
const browser=await chromium.launch({headless:true});
const origin="http://127.0.0.1:61483", staticRoot=new URL("../src/radhouse/chat/static/",import.meta.url);
let jpeg=null, frameCalls=0, statusCalls=0, active=true, enabled=true;
let run="run-1", generation="generation-1", holdStatus=false, releaseStatus;
const first={seq:1,request_id:"request-1",text:"Work through this page",status:"running",output:null,
  attachments:[{name:"guide.pdf",kind:"document",media_type:"application/pdf",size:123,reading_state:"available",position:0}]};
let turns=[first];
const history=()=>({turns,older_before:null});
const credentials=()=>({username:"alice",csrf_token:"synthetic-csrf",features:{browser:enabled,documents:true}});
const agent=await browser.newContext({viewport:{width:960,height:540}}), agentPage=await agent.newPage();
const cdp=await agent.newCDPSession(agentPage);
await cdp.send("Page.enable");
cdp.on("Page.screencastFrame",event=>{jpeg=Buffer.from(event.data,"base64");void cdp.send("Page.screencastFrameAck",{sessionId:event.sessionId}).catch(()=>{});});
await cdp.send("Page.startScreencast",{format:"jpeg",quality:65,maxWidth:960,maxHeight:540,everyNthFrame:1});
await agentPage.setContent('<body style="background:#315441;color:white;font:40px system-ui"><h1>Agent-owned page</h1></body>');
await expect.poll(()=>jpeg?.length||0).toBeGreaterThan(100);
const context=await browser.newContext({viewport:{width:1200,height:900}}), page=await context.newPage(), errors=[];
await page.addInitScript(()=>{
  const realFetch=fetch;window.ignoreAbort=false;window.urls=new Set();
  window.fetch=(path,options)=>realFetch(path,window.ignoreAbort?{...options,signal:undefined}:options);
  const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
  URL.createObjectURL=blob=>{const url=create(blob);window.urls.add(url);return url;};
  URL.revokeObjectURL=url=>{window.urls.delete(url);revoke(url);};
});
page.on("pageerror",error=>errors.push(error.message));
await context.route(`${origin}/**`,async route=>{
  const url=new URL(route.request().url()), path=url.pathname;
  const json=(value,status=200)=>route.fulfill({status,contentType:"application/json",body:JSON.stringify(value)});
  if(path==="/auth/session")return active?json(credentials()):json({error:"authentication_required"},401);
  if(path==="/auth/login"){active=true;return json(credentials());}
  if(path==="/auth/logout"){active=false;return route.fulfill({status:204});}
  if(path==="/chat/history"||path==="/chat/reply")return json(history());
  if(path==="/chat/browser"){
    statusCalls++;const value={state:"live",run_id:run,generation,url:`https://example.org/${run}`};
    if(holdStatus){holdStatus=false;await new Promise(resolve=>{releaseStatus=resolve;});}
    return json(value);
  }
  if(path==="/chat/browser/frame"){
    frameCalls++;
    return active?route.fulfill({status:200,contentType:"image/jpeg",headers:{"X-Radhouse-Browser-Generation":generation,"X-Radhouse-Browser-Received-At":String(Date.now()/1000)},body:jpeg}) : json({error:"authentication_required"},401);
  }
  if(path.startsWith("/chat/messages/")&&path.includes("/attachments/"))return route.fulfill({status:200,body:"synthetic original"});
  const file={"/":"index.html","/chat.js":"chat.js","/chat.css":"chat.css","/format.js":"format.js","/browser-view.js":"browser-view.js","/browser-view.css":"browser-view.css","/icons/pdf.svg":"icons/pdf.svg"}[path];
  if(!file)return route.fulfill({status:404});
  return route.fulfill({status:200,contentType:file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":file.endsWith(".svg")?"image/svg+xml":"text/html",body:await readFile(new URL(file,staticRoot)),headers:{"Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; base-uri 'none'"}});
});
try{
  await page.goto(origin);
  const pane=page.locator("#assistant-browser"),img=pane.locator("img");
  await expect(page.locator("#chat-view")).toBeVisible();await expect(pane).toBeVisible();await expect(img).toBeVisible();
  await expect(pane.locator(".browser-view-site")).toHaveText("https://example.org/run-1");
  await expect(page.locator(".attachment")).toContainText("Available to the assistant");
  await expect(page.locator("#compose")).toBeInViewport();
  await page.locator("#message").fill("Keep my next draft while the browser works");
  await page.reload();await expect(img).toBeVisible();await expect(page.locator("#message")).toHaveValue("Keep my next draft while the browser works");
  await pane.getByRole("button",{name:"Hide browser",exact:true}).click();
  const count=frameCalls;await page.waitForTimeout(1100);if(frameCalls!==count)throw new Error("Hidden chat browser kept reading frames");
  await pane.getByRole("button",{name:"Show browser",exact:true}).click();await expect(img).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error("Chat viewer overflows mobile");
  await expect(page.locator("#compose")).toBeInViewport();
  // The old run's delayed status must not replace a newly accepted run.
  await expect.poll(()=>page.evaluate(()=>browserStatusRequest===null)).toBe(true);
  holdStatus=true;await page.evaluate(()=>{window.ignoreAbort=true;void refreshBrowser();});
  await expect.poll(()=>typeof releaseStatus).toBe("function");
  turns=[{...first,status:"completed",output:"Completed first page"},{seq:2,request_id:"request-2",text:"Continue",status:"running",output:null,attachments:[]}];
  run="run-2";generation="generation-2";
  await page.evaluate(async()=>accept(await api('/chat/reply')));releaseStatus();
  await expect(pane.locator(".browser-view-site")).toHaveText("https://example.org/run-2");await expect(img).toBeVisible();
  // Auth feature refresh is effective immediately and revokes display URLs.
  enabled=false;await page.evaluate(()=>refreshHistory());await expect(pane).toBeHidden();
  if(await page.evaluate(()=>window.urls.size))throw new Error("Disabled browser retained displayed frames");
  const stoppedFrames=frameCalls,stoppedStatus=statusCalls;await page.waitForTimeout(2100);
  if(frameCalls!==stoppedFrames||statusCalls!==stoppedStatus)throw new Error("Disabled feature still polls");
  enabled=true;await page.evaluate(()=>refreshHistory());await expect(img).toBeVisible();
  // Sign-out clears the live view immediately, preserving the next draft.
  await page.locator("#logout").click();await expect(page.locator("#login-view")).toBeVisible();await expect(pane).toBeHidden();
  if(await page.evaluate(()=>window.urls.size))throw new Error("Sign-out retained frame URLs");
  await page.locator("#password").fill("synthetic-password");await page.locator("#totp").fill("123456");
  await page.getByRole("button",{name:"Sign in",exact:true}).click();await expect(img).toBeVisible();
  await expect(page.locator("#message")).toHaveValue("Keep my next draft while the browser works");
  turns=turns.map(turn=>({...turn,status:"completed",output:"Finished"}));
  await page.evaluate(async()=>accept(await api('/chat/reply')));await expect(pane).toBeHidden();
  if(await page.evaluate(()=>window.urls.size))throw new Error("Terminal run retained frame URLs");
  if(errors.length)throw new Error(errors.join("; "));
  console.log("Chat browser integration passed: first-class live pane, same agent stream, saved drafts, mobile composer, new-run race, feature revocation and sign-out.");
}finally{releaseStatus?.();await browser.close();}
