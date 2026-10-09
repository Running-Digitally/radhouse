// Actual static UI in Chromium, with synthetic owner and native/browser responses.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const browser=await chromium.launch({headless:true});
const origin="http://127.0.0.1:61509",root=new URL("../src/radhouse/chat/static/",import.meta.url);
let turns=[],site="https://example.org/",sequence=1,prefs={revision:0,search_engine:"google",history:[]};
const navigations=[],errors=[],followupAttempts=[];let loseFollowup=false;
const native=await browser.newPage({viewport:{width:960,height:540}});
await native.setContent("<h1>Disposable browser page</h1>");
const jpeg=(await native.screenshot({type:"jpeg"})).toString("base64");
const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage();
page.on("pageerror",error=>errors.push(error.message));
const state=()=>({state:"live",generation:"fixture-generation",url:site,title:"Disposable page",viewport:{width:960,height:540},
  control:{mode:"human",revision:1,lease_id:"fixture-lease",lease_expires_at:Date.now()/1000+300,next_sequence:sequence},
  page_context:{current:{url:site,title:"Disposable page"},previous:null},can_return:!turns.some(t=>t.status==="running"),vault_enabled:false});
await context.route(origin+"/**",async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  const json=(value,status=200)=>route.fulfill({status,contentType:"application/json",body:JSON.stringify(value)});
  const body=request.postDataJSON();
  if(path==="/auth/session")return json({username:"alice",csrf_token:"fixture-csrf",management:{read:true,write:false},features:{browser:true,browser_control:true}});
  if(path==="/chat/history"||path==="/chat/reply")return json({turns,older_before:null});
  if(path==="/chat/browser/preferences") {
    if(request.method()==="POST")prefs={...prefs,revision:prefs.revision+1,search_engine:body.search_engine};
    return json(prefs);
  }
  if(path==="/chat/browser/history/clear"){prefs.history=[];return json(prefs);}
  if(path==="/chat/browser")return json(state());
  if(path.startsWith("/chat/browser/frame"))return route.fulfill({contentType:"image/jpeg",body:Buffer.from(jpeg,"base64"),
    headers:{"X-Radhouse-Browser-Generation":"fixture-generation","X-Radhouse-Browser-Frame-Id":"fixture-frame",
      "X-Radhouse-Browser-Width":"960","X-Radhouse-Browser-Height":"540"}});
  if(path==="/chat/browser/control/heartbeat")return json(state());
  if(path==="/chat/browser/control/input") {
    sequence=body.sequence+1;
    if(body.operation==="navigate") {
      navigations.push(body.arguments.url);site=body.arguments.url;
      const url=new URL(site);url.search="";url.hash="";
      prefs.history=[{url:url.href,visited_at:Date.now()/1000}];
    }
    return json({outcome:"applied",sequence:body.sequence});
  }
  if(path==="/chat/messages") {
    if(body.text==="Follow up during the reply") {
      followupAttempts.push(body.request_id);
      if(loseFollowup){loseFollowup=false;return route.abort("failed");}
    }
    const old=turns.find(t=>t.request_id===body.request_id);
    if(!old)turns.push({seq:turns.length+1,request_id:body.request_id,text:body.text,
      status:turns.some(t=>!["completed","cancelled"].includes(t.status))?"waiting":"running",output:null,error:null,attachments:[],shared_files:[]});
    return json({turns,older_before:null,accepted_request_id:body.request_id});
  }
  if(/^\/chat\/messages\/[^/]+\/cancel$/.test(path)) {
    const turn=turns.find(t=>t.request_id===path.split("/")[3]);turn.status="cancelled";turn.error="followup_cancelled";
    return json({turns,older_before:null});
  }
  if(path==="/admin/settings")return json({checked_at:new Date().toISOString(),authentication:{idle_timeout_seconds:1800,maximum_session_seconds:43200,remembered_session_seconds:2592000},
    files:{upload_size_limit_bytes:null,upload_count_limit:null},documents:{selective_access_enabled:true},browser:{enabled:true,mode:"owner_session"},messages:{character_limit:16000}});
  if(path==="/chat/library")return json({files:[],next_cursor:null});
  const file=["/","/browser"].includes(path)?"index.html":path==="/settings"?"admin.html":path.startsWith("/workspace-assets/")?path.slice(18):path.slice(1);
  try {
    if(file.includes("..")||path.startsWith("/chat/"))return route.fulfill({status:404});
    return route.fulfill({contentType:file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":file.endsWith(".json")?"application/json":"text/html",body:await readFile(new URL(file,root))});
  } catch {return route.fulfill({status:404});}
});
try {
  await page.goto(origin+"/browser");
  const address=page.getByRole("combobox",{name:"Search or enter address",exact:true}),go=page.getByRole("button",{name:"Go",exact:true});
  await expect(go).toBeEnabled();
  await address.fill("example.org/path");
  await page.evaluate(()=>refreshBrowser());await expect(address).toHaveValue("example.org/path");
  await address.press("Enter");await expect.poll(()=>navigations.at(-1)).toBe("https://example.org/path");
  for(const width of [320,390,1280]) {
    await page.setViewportSize({width,height:844});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error("Address bar overflows at "+width);
    if((await address.boundingBox()).width<90)throw new Error("Address field is unusably narrow at "+width);
    if(width===320)await page.screenshot({path:"/private/tmp/radhouse-browser-followups-mobile.png",fullPage:true});
  }
  await page.goto(origin+"/settings");
  await expect(page.getByRole("radio",{name:"Google",exact:true})).toBeChecked();
  await page.getByRole("radio",{name:"DuckDuckGo",exact:true}).check();
  await page.getByRole("button",{name:"Save browser settings",exact:true}).click();
  await expect(page.getByText("Browser settings saved.",{exact:true})).toBeVisible();
  await page.reload();await expect(page.getByRole("radio",{name:"DuckDuckGo",exact:true})).toBeChecked();
  await page.goto(origin+"/browser");await expect(go).toBeEnabled();
  await address.fill("why do leaves change colour");await address.press("Enter");
  await expect.poll(()=>new URL(navigations.at(-1)).hostname).toBe("duckduckgo.com");
  if(new URL(navigations.at(-1)).searchParams.get("q")!=="why do leaves change colour")throw new Error("Search query was changed");
  await address.focus();await expect.poll(()=>page.locator("datalist option").count()).toBe(1);
  await page.setViewportSize({width:390,height:844});await page.goto(origin+"/");
  const message=page.getByRole("textbox",{name:"Message your assistant",exact:true}),send=page.getByRole("button",{name:"Send",exact:true});
  await message.fill("First question");await send.click();await expect(page.getByText("First question",{exact:true})).toBeVisible();
  await message.fill("Follow up during the reply");await expect(send).toBeEnabled();loseFollowup=true;await send.click();
  await expect(page.getByRole("button",{name:"Retry message",exact:true})).toBeEnabled();
  await page.getByRole("button",{name:"Retry message",exact:true}).click();
  await expect(page.getByText("Saved · Waiting for the current reply to finish…",{exact:true})).toBeVisible();
  if(followupAttempts.length!==2||followupAttempts[0]!==followupAttempts[1])throw new Error("Retry changed the follow-up identity");
  await page.reload();await expect(page.getByRole("button",{name:"Cancel follow-up",exact:true})).toBeVisible();
  await page.screenshot({path:"/private/tmp/radhouse-browser-followups-queue.png",fullPage:true});
  await page.getByRole("button",{name:"Cancel follow-up",exact:true}).click();
  await expect(page.getByText("Follow-up cancelled before it was sent.",{exact:true})).toBeVisible();
  if(turns.length!==2)throw new Error("Reload duplicated an outgoing message");
  await page.goto(origin+"/settings");await page.getByRole("button",{name:"Clear browsing history",exact:true}).click();
  await expect(page.getByText("Browsing history cleared.",{exact:true})).toBeVisible();
  if(prefs.history.length)throw new Error("History was not cleared");
  await page.screenshot({path:"/private/tmp/radhouse-browser-followups-settings.png",fullPage:true});
  if(errors.length)throw new Error(errors.join("; "));
  console.log("Address/search, saved engine/history, 320/390/1280px, follow-up Send/retry/reload/cancel passed.");
} finally {await context.close();await browser.close();}
