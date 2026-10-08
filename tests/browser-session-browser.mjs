// Real Chromium stream and human input; disposable synthetic authenticated API.
import {readFile,mkdir} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect:baseExpect}=await import(moduleUrl),expect=baseExpect.configure({timeout:10000});
const browser=await chromium.launch({headless:true,
  ...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})}),origin="http://127.0.0.1:61484";
const staticRoot=new URL("../src/radhouse/chat/static/",import.meta.url);
let native=null,cdp=null,jpeg=null,frame=0,mode="idle",revision=1,sequence=1,holder=null,site=null;
let openCalls=0,inputCalls=0,frameCalls=0,active=true,controlSupported=true,turns=[],savedLogin=null;
let loseInput=false,pendingInput=false,pauseCalls=0,takeCalls=0,leaseSerial=1;
let statusUnavailable=true,statusCalls=0,reconnectMethods=[];
let rejectFirstNavigation=true;
let idleControl=null;
const calls=[],errors=[],secret="SYNTHETIC-PASSWORD-NOT-IN-CHAT",draft="Keep my next message while browsing";
const nativeContext=await browser.newContext({viewport:{width:960,height:540}});
await nativeContext.route("https://example.org/**",route=>route.fulfill({contentType:"text/html",body:`<html><body style="font:20px system-ui;background:#f5f7f1;padding:36px"><h1>Example sign-in</h1><form id="login"><label>Account<input id="account" style="display:block;margin:12px 0"></label><label>Password<input id="password" type="password" style="display:block;margin:12px 0"></label><button>Sign in</button></form><p id="result"></p><script>document.getElementById('login').onsubmit=e=>{e.preventDefault();document.getElementById('password').value='';document.getElementById('result').textContent='Signed in';};</script></body></html>`}));
async function openNative(){
  if(native)return;
  native=await nativeContext.newPage();cdp=await nativeContext.newCDPSession(native);
  await cdp.send("Page.enable");
  cdp.on("Page.screencastFrame",event=>{jpeg=Buffer.from(event.data,"base64");frame++;void cdp.send("Page.screencastFrameAck",{sessionId:event.sessionId}).catch(()=>{});});
  await cdp.send("Page.startScreencast",{format:"jpeg",quality:65,maxWidth:960,maxHeight:540,everyNthFrame:1});
  await native.setContent('<body style="background:white;font:24px system-ui"><p>Browser ready</p></body>');
  await expect.poll(()=>jpeg?.length||0).toBeGreaterThan(100);
}
const state=tab=>({state:mode==="idle"?"idle":"live",generation:mode==="idle"?null:"generation-1",url:mode==="idle"?null:site,
  title:site?"Example sign-in":null,viewport:mode==="idle"?null:{width:960,height:540},
  control:mode==="idle"?idleControl:{mode,revision,can_take:["agent","paused"].includes(mode),
    ...(holder===tab&&mode==="human"?{lease_id:"lease-"+leaseSerial,lease_expires_at:Date.now()/1000+60,next_sequence:sequence}:{})},
  page_context:{current:mode==="idle"?null:{url:site,title:site?"Example sign-in":null},previous:mode==="idle"&&site?{url:site,title:"Example sign-in"}:null},
  can_return:!turns.some(t=>t.status==="running"),vault_enabled:true});
const context=await browser.newContext({viewport:{width:1200,height:1000}});
await context.route(`${origin}/**`,async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname,tab=request.headers()["x-radhouse-browser-tab"];
  const data=request.postDataJSON(),json=(value,status=200)=>route.fulfill({status,contentType:"application/json",body:JSON.stringify(value)});
  if(path==="/auth/session")return active?json({username:"alice",csrf_token:"synthetic-csrf",features:{browser:true,browser_control:controlSupported,documents:true}}):json({error:"authentication_required"},401);
  if(path==="/auth/logout"){active=false;return route.fulfill({status:204});}
  if(path==="/chat/history"||path==="/chat/reply")return json({turns,older_before:null});
  if(path==="/chat/library")return json({files:[],next_cursor:null});
  if(path==="/chat/browser"){
    statusCalls++;reconnectMethods.push(request.method());
    return statusUnavailable?json({error:"browser_unavailable"},503):json(state(tab));
  }
  if(path==="/chat/browser/open"){
    calls.push([path,data]);openCalls++;await openNative();mode="human";holder=tab;revision=3;sequence=1;return json(state(tab));
  }
  if(path==="/chat/browser/frame"){
    frameCalls++;if(!active)return json({error:"authentication_required"},401);
    if(mode==="idle"||!jpeg)return json({error:"browser_closed"},409);
    return route.fulfill({contentType:"image/jpeg",headers:{"X-Radhouse-Browser-Generation":"generation-1",
      "X-Radhouse-Browser-Frame-Id":"frame-"+frame,"X-Radhouse-Browser-Width":"960","X-Radhouse-Browser-Height":"540"},body:jpeg});
  }
  if(path==="/chat/browser/control/input"){
    calls.push([path,data]);inputCalls++;
    if(loseInput){loseInput=false;return route.abort("failed");}
    if(mode!=="human"||tab!==holder||data.sequence!==sequence++||data.viewport.width!==960||data.viewport.height!==540)throw new Error("Input ownership/sequence/geometry mismatch");
    if(pendingInput)return json({outcome:"reserved",sequence:data.sequence});
    const args=data.arguments;
    if(data.operation==="navigate"&&rejectFirstNavigation){rejectFirstNavigation=false;return json({outcome:"rejected",sequence:data.sequence});}
    if(data.operation==="click")await native.mouse.click(args.x,args.y);
    else if(data.operation==="text")await native.keyboard.insertText(args.text);
    else if(data.operation==="press")await native.keyboard.press(args.key);
    else if(data.operation==="scroll")await native.mouse.wheel(args.delta_x,args.delta_y);
    else if(data.operation==="navigate"){site=args.url;await native.goto(site);}
    else if(data.operation==="reload")await native.reload();
    else if(data.operation==="back")await native.goBack();
    return json({outcome:"applied",sequence:data.sequence});
  }
  if(path==="/chat/browser/control/take"){calls.push([path,data]);takeCalls++;mode="human";holder=tab;revision++;sequence=1;leaseSerial++;return json(state(tab));}
  if(path==="/chat/browser/control/pause"){
    calls.push([path,data]);pauseCalls++;
    if(pendingInput)return json({error:"browser_control_changed"},409);
    mode="paused";holder=null;revision++;return json(state(tab));
  }
  if(path==="/chat/browser/control/heartbeat"){calls.push([path,data]);return json(state(tab));}
  if(path==="/chat/browser/control/close"){
    calls.push([path,data]);await native.close();native=null;mode="idle";holder=null;
    // A positively closed native browser can retain paused controller metadata.
    idleControl={mode:"paused",revision:++revision,can_take:true};return json(state(tab));
  }
  if(path==="/chat/browser/logins/list"){
    calls.push([path,data]);if(data.sequence!==sequence++)throw new Error("Vault sequence mismatch");
    return json({items:savedLogin?[savedLogin]:[]});
  }
  if(path==="/chat/browser/logins"){
    calls.push([path,data]);if(data.sequence!==sequence++)throw new Error("Vault save sequence mismatch");
    if(data.password!==secret)throw new Error("Explicit owner vault form not relayed");
    savedLogin={id:"login-1",kind:"login",label:data.label,identifier_type:data.identifier_type,
      identifier:data.identifier,origin:"https://example.org",created_at:"2026-10-08T12:00:00Z"};return json({item:savedLogin});
  }
  if(path==="/chat/messages"||path==="/chat/browser/return"){
    calls.push([path,data]);mode="agent";holder=null;revision++;
    const turn={seq:turns.length+1,request_id:data.request_id,text:data.text||"I’m returning the browser to you. Continue from the current page.",
      status:"running",output:null,attachments:[],shared_files:[]};turns.push(turn);
    return json({turns,older_before:null,accepted_request_id:turn.request_id});
  }
  const file={"/":"index.html","/browser":"index.html","/library":"index.html","/chat.js":"chat.js","/chat.css":"chat.css","/format.js":"format.js",
    "/browser-view.js":"browser-view.js","/browser-view.css":"browser-view.css","/navigation.js":"navigation.js","/navigation.css":"navigation.css","/library.js":"library.js"}[path];
  if(!file)return route.fulfill({status:404});
  return route.fulfill({contentType:file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":"text/html",body:await readFile(new URL(file,staticRoot))});
});
const page=await context.newPage();page.on("pageerror",error=>errors.push(error.message));
const navigate=async name=>{const link=page.getByRole("navigation",{name:"Main navigation"}).getByRole("link",{name,exact:true});if(!await link.isVisible())await page.getByRole("button",{name:"Open menu",exact:true}).click();await link.click();};
async function clickNative(selector){
  await expect(page.getByRole("button",{name:"Type",exact:true})).toBeEnabled();
  const before=inputCalls;
  const target=await native.locator(selector).boundingBox(),image=await page.locator("#assistant-browser img").boundingBox();
  const scale=Math.min(image.width/960,image.height/540);
  await page.mouse.click(image.x+(image.width-960*scale)/2+(target.x+target.width/2)*scale,
    image.y+(image.height-540*scale)/2+(target.y+target.height/2)*scale);
  await expect.poll(()=>inputCalls).toBe(before+1);
  await expect(page.getByRole("button",{name:"Type",exact:true})).toBeEnabled();
}
async function type(text){await page.getByLabel("Type into selected page field",{exact:true}).fill(text);await page.getByRole("button",{name:"Type",exact:true}).click();}
try{
  await page.goto(origin+"/browser");
  await expect(page.getByRole("button",{name:"Reconnect browser",exact:true})).toBeVisible();
  await expect(page.getByText("The browser connection is unavailable. Reconnect to check it again.",{exact:true})).toBeVisible();
  if(!await page.evaluate(()=>browserView.controlEnabled))throw new Error("Initial status failure erased authenticated browser capability");
  if(openCalls||native)throw new Error("Failed status check eagerly launched a native browser");
  const failedChecks=statusCalls;statusUnavailable=false;
  await page.getByRole("button",{name:"Reconnect browser",exact:true}).click();
  await expect(page.getByRole("button",{name:"Open browser",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Open browser",exact:true})).toBeEnabled();
  if(statusCalls<=failedChecks||reconnectMethods.some(method=>method!=="GET")||openCalls||native)throw new Error("Reconnection retried a browser action instead of checking status");
  await page.waitForTimeout(500);if(openCalls||native)throw new Error("Browser route eagerly launched a native page");
  await page.getByRole("button",{name:"Open browser window",exact:true}).click();
  await expect(page.locator("#assistant-browser img")).toBeVisible();
  if(openCalls!==1)throw new Error("Explicit open sent duplicate launches");
  await page.getByRole("textbox",{name:"Website URL",exact:true}).fill("https://example.org/login");
  // The status request can finish after Go takes focus but before its submit.
  await page.getByRole("button",{name:"Go",exact:true}).focus();
  await page.evaluate(()=>refreshBrowser());
  await expect(page.getByRole("textbox",{name:"Website URL",exact:true})).toHaveValue("https://example.org/login");
  await page.getByRole("button",{name:"Go",exact:true}).click();
  await expect(page.getByText("That action was not applied. Check the page before trying another action.",{exact:true})).toBeVisible();
  await page.evaluate(()=>refreshBrowser());
  await expect(page.getByRole("textbox",{name:"Website URL",exact:true})).toHaveValue("https://example.org/login");
  if(inputCalls!==1||native.url()!=="about:blank")throw new Error("Rejected navigation was automatically retried");
  await page.getByRole("button",{name:"Go",exact:true}).click();await expect(native.getByRole("heading",{name:"Example sign-in"})).toBeVisible();
  if(calls.find(([path,data])=>path==="/chat/browser/control/input"&&data.operation==="navigate")?.[1].arguments.url!=="https://example.org/login")throw new Error("Navigation did not submit the user's literal URL");
  await expect.poll(()=>page.locator(".browser-view-site").textContent()).toBe("https://example.org/login");
  // The same native page receives scaled clicks, text and key gestures.
  await clickNative("#account");await type("synthetic-account");await expect(native.locator("#account")).toHaveValue("synthetic-account");
  await clickNative("#password");await type(secret);await expect(native.locator("#password")).toHaveValue(secret);
  await page.getByRole("button",{name:"Enter",exact:true}).click();await expect(native.locator("#result")).toHaveText("Signed in");
  await expect(native.locator("#password")).toHaveValue("");
  // A pre-admission loss never replays text or silently rewinds its sequence.
  await clickNative("#account");loseInput=true;await type("UNSENT-INPUT");
  await expect(page.getByText("Previous input wasn’t confirmed. Check the page before continuing.",{exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Type",exact:true})).toBeDisabled();
  await page.getByRole("button",{name:"Reconnect controls",exact:true}).click();
  await expect(page.getByRole("button",{name:"Type",exact:true})).toBeEnabled();
  await expect(native.locator("#account")).toHaveValue("synthetic-account");
  await type("-continued");await expect(native.locator("#account")).toHaveValue(/-continued/);
  const continuedValue=await native.locator("#account").inputValue();
  if(continuedValue.replace("-continued","")!=="synthetic-account")throw new Error("Lost input was replayed during recovery");
  // An unresolved reservation must block reconnection and every later gesture.
  pendingInput=true;await type("PENDING-INPUT");
  const takesBeforeHold=takeCalls,inputsBeforeHold=inputCalls;
  await page.getByRole("button",{name:"Reconnect controls",exact:true}).click();
  await expect(page.getByRole("button",{name:"Type",exact:true})).toBeDisabled();
  if(takeCalls!==takesBeforeHold||inputCalls!==inputsBeforeHold)throw new Error("Unresolved input was overridden or replayed");
  await expect(native.locator("#account")).toHaveValue(continuedValue);
  pendingInput=false; // Synthetic native ACK settles as rejected; owner retries recovery only.
  await page.getByRole("button",{name:"Reconnect controls",exact:true}).click();
  await expect(page.getByRole("button",{name:"Type",exact:true})).toBeEnabled();
  await expect(native.locator("#account")).toHaveValue(continuedValue);
  // Letterboxing cannot become an unintended click in the page.
  await page.locator(".browser-view-viewport").evaluate(node=>{node.style.width="360px";node.style.height="360px";node.style.aspectRatio="1";});
  const rect=await page.locator("#assistant-browser img").boundingBox(),before=inputCalls;
  await page.mouse.click(rect.x+180,rect.y+4);await page.waitForTimeout(100);
  if(inputCalls!==before)throw new Error("Letterbox accepted input");
  await page.locator(".browser-view-viewport").evaluate(node=>node.removeAttribute("style"));
  await page.getByRole("button",{name:"Saved logins",exact:true}).click();
  await page.getByLabel("Login name",{exact:true}).fill("Example");await page.getByLabel("Account",{exact:true}).fill("synthetic-account");
  await page.locator(".browser-logins").getByLabel("Password",{exact:true}).fill(secret);
  await page.getByRole("button",{name:"Save login for this site",exact:true}).click();
  await expect(page.locator(".browser-control-status")).toHaveText("Login saved for this website.");
  if(await page.locator(".browser-logins input[type=password]").inputValue())throw new Error("Saved login password remained in form");
  await navigate("Chat");await page.getByRole("textbox",{name:"Message your assistant"}).fill("Use this current page");
  await expect(page.locator("#browser-context-chip")).toBeVisible();await page.getByRole("button",{name:"Send",exact:true}).click();
  await expect.poll(()=>calls.some(([path])=>path==="/chat/messages")).toBe(true);
  const message=calls.find(([path])=>path==="/chat/messages")[1];
  if(message.browser_context?.generation!=="generation-1")throw new Error("Actual run omitted current browser handoff");
  if(JSON.stringify(message).includes(secret))throw new Error("Secret entered a chat dispatch");
  await page.getByRole("textbox",{name:"Message your assistant"}).fill(draft);
  await navigate("Browser");await page.getByRole("button",{name:"Take control",exact:true}).click();
  await expect(page.getByRole("button",{name:"Return to agent",exact:true})).toBeDisabled();
  turns[0]={...turns[0],status:"completed",output:"Done"};
  await expect(page.getByRole("button",{name:"Return to agent",exact:true})).toBeEnabled();
  await page.getByRole("button",{name:"Return to agent",exact:true}).click();
  await expect(page.getByRole("textbox",{name:"Message your assistant"})).toHaveValue(draft);
  const returned=calls.find(([path])=>path==="/chat/browser/return")?.[1];
  if(!returned||JSON.stringify(returned).includes(secret)||Object.hasOwn(returned,"attachments"))throw new Error("Return copied secrets or draft files");
  turns[1]={...turns[1],status:"completed",output:"Continued"};
  await navigate("Browser");await page.getByRole("button",{name:"Take control",exact:true}).click();
  if(process.env.RADHOUSE_BROWSER_SCREENSHOTS){await mkdir(process.env.RADHOUSE_BROWSER_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.RADHOUSE_BROWSER_SCREENSHOTS+"/browser-control-desktop.png",fullPage:true});}
  await page.setViewportSize({width:390,height:844});await expect(page.locator("#assistant-browser img")).toBeVisible();
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error("Browser controls overflow on mobile");
  if(process.env.RADHOUSE_BROWSER_SCREENSHOTS){await mkdir(process.env.RADHOUSE_BROWSER_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.RADHOUSE_BROWSER_SCREENSHOTS+"/browser-control-mobile.png",fullPage:true});}
  await page.getByRole("button",{name:"Close browser",exact:true}).click();
  await expect(page.getByRole("button",{name:"Open browser",exact:true})).toBeVisible();await expect(page.locator("#assistant-browser img")).toBeHidden();
  if(await page.evaluate(()=>lastBrowserStatus.control?.mode)!=="paused")throw new Error("Idle regression omitted retained paused controller metadata");
  await expect(page.getByRole("button",{name:"Take control",exact:true})).toBeHidden();
  await expect(page.locator(".browser-control-status")).toHaveText("");
  await page.evaluate(()=>{browserView.actionNotice="That action was not applied. Check the page before trying another action.";browserView._renderControlState();});
  await page.evaluate(()=>refreshBrowser());
  await expect(page.locator(".browser-control-status")).toHaveText("");
  await expect(page.locator("#assistant-browser img")).not.toHaveAttribute("src",/.+/);
  const count=openCalls;await page.waitForTimeout(2200);if(openCalls!==count||native)throw new Error("Closed browser was automatically reopened");
  await navigate("Chat");await expect(page.locator("#browser-context-label")).toHaveText("Use previous page: Example sign-in");
  await page.locator("#use-browser-context").check();await page.getByRole("textbox",{name:"Message your assistant"}).fill("About that previous page");
  await page.getByRole("button",{name:"Send",exact:true}).click();await expect.poll(()=>turns.length).toBe(3);
  const lastMessage=calls.filter(([path])=>path==="/chat/messages").at(-1)[1];
  if(lastMessage.browser_context||!lastMessage.use_previous_browser)throw new Error("Previous locator claimed native continuity");
  turns[2]={...turns[2],status:"failed",error:"reply_failed",output:"I found the relevant page, but the remaining lookup did not finish."};
  await expect(page.getByText(turns[2].output,{exact:true})).toBeVisible();
  await expect(page.getByText("Reply ended before finishing.",{exact:true})).toBeVisible();
  const stored=await page.evaluate(async()=>{
    const local=JSON.stringify({...localStorage});
    const db=await new Promise((resolve,reject)=>{const req=indexedDB.open("radhouse-chat-drafts",1);req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});
    const stores=[...db.objectStoreNames];let values=[];
    for(const name of stores){values.push(await new Promise(resolve=>{const tx=db.transaction(name),req=tx.objectStore(name).getAll();req.onsuccess=()=>resolve(req.result);}));}
    db.close();return local+JSON.stringify(values);
  });
  if(stored.includes(secret)||JSON.stringify(turns).includes(secret))throw new Error("Secret persisted in drafts/history");
  await page.getByRole("button",{name:"Sign out",exact:true}).click();await expect(page.locator("#browser-context-chip")).toBeHidden();
  active=true;controlSupported=false;mode="idle";
  await page.goto(origin+"/browser");
  await expect(page.getByText("Browser control needs the upgraded Hermes runtime. You can still watch an active agent browser.",{exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"Open browser",exact:true})).toBeDisabled();
  if(openCalls!==count||native)throw new Error("An unqualified runtime launched a browser");
  if(errors.length)throw new Error(errors.join("; "));
  console.log(JSON.stringify({result:"passed",openCalls,inputCalls,frameCalls,pauseCalls,realNativeInput:true,inputLossRecoverable:true,pendingAckBlocked:true,draftPreserved:true,secretNotInChatOrStorage:true,mobileNoOverflow:true}));
}finally{await browser.close();}
