// Saved presentation against the real shell/controller with an isolated HTTP fixture.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import {cover,closeBrowser} from "./browser-coverage.mjs";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect:baseExpect}=await import(moduleUrl);
const expect=baseExpect.configure({timeout:10000});
const root=new URL("../src/radhouse/chat/static/",import.meta.url),origin="http://127.0.0.1:61393";
const catalog=JSON.parse(await readFile(new URL("agent-profile/catalog.json",root),"utf8"));
const initial={schema:"radhouse.agent-profile.v1",revision:0,name:"",intro:"",theme:"hearthside",portrait:"ember",accent:"fern",surface:"paper",stateMotion:true,iconMotion:true,portraitSize:80};
let saved={...initial},failure=null,posts=[],profileReads=0,authenticated=true;
const fixture=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/chat.css"><link rel="stylesheet" href="/navigation.css"><link rel="stylesheet" href="/browser-view.css"><link rel="stylesheet" href="/owner-terminal.css"><link rel="stylesheet" href="/admin.css"><link rel="stylesheet" href="/workspace-assets/agent-profile.css">
<script src="/workspace-assets/agent-portrait.js" defer></script><script src="/navigation.js" defer></script><script src="/workspace-assets/agent-profile.js" defer></script><script src="/fixture.js" defer></script></head>
<body><div class="shell"><header><a class="brand" href="/">Radhouse</a><button id="logout">Sign out</button></header>
<nav id="management-nav" aria-label="Main navigation" hidden><a href="/">Chat</a><a href="/library">Library</a><a href="/browser">Browser</a><a href="/terminal">Terminal</a><a href="/about-you">About You</a><a href="/settings" id="settings-link" data-management>Settings</a><a href="/infrastructure" data-management>Infrastructure</a></nav>
<main class="workspace-page"><h1>Your Agent</h1><div id="profile"></div></main></div></body></html>`;
const fixtureScript=`window.profileChanges=[];
window.profile=new RadhouseAgentProfile({container:document.getElementById("profile"),
request:async(path,body,initial,signal)=>{const result=await fetch(path,{method:body===undefined?"GET":"POST",headers:body===undefined?{}:{"Content-Type":"application/json","X-Radhouse-CSRF":"fixture"},body:body===undefined?undefined:JSON.stringify(body),signal});const value=await result.json();if(!result.ok){const error=new Error(value.error);error.status=result.status;throw error;}return value;},
onAuthRequired:()=>{window.authExpired=true;RadhouseNavigation.update(null);},onChange:value=>profileChanges.push(value)});
RadhouseNavigation.update({username:"fixture",management:{read:true,write:false}});
RadhouseNavigation.setAgentState("idle","Ready for your next message");profile.setVisible(true);void profile.load();`;
const browser=await chromium.launch({headless:true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})}),context=await browser.newContext({viewport:{width:1280,height:900}});
const loadedPortraits=new Set(),errors=[];
await context.route(`${origin}/**`,async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  const json=(value,status=200)=>({status,contentType:"application/json",body:JSON.stringify(value)});
  if(path==="/agent"){await route.fulfill({status:200,contentType:"text/html",body:fixture});return;}
  if(path==="/fixture.js"){await route.fulfill({status:200,contentType:"text/javascript",body:fixtureScript});return;}
  if(path==="/chat/agent-profile"){
    if(!authenticated){await route.fulfill(json({error:"authentication_required"},401));return;}
    if(request.method()==="GET"){profileReads++;await route.fulfill(json(saved));return;}
    const body=request.postDataJSON();posts.push({body,csrf:request.headers()["x-radhouse-csrf"]});
    if(failure){await route.fulfill(json({error:failure},failure==="agent_profile_conflict"?409:503));return;}
    if(body.revision!==saved.revision){await route.fulfill(json({error:"agent_profile_conflict"},409));return;}
    saved={...body,name:body.name.trim(),intro:body.intro.trim(),revision:saved.revision+1};await route.fulfill(json(saved));return;
  }
  const filename=path.startsWith("/workspace-assets/")?path.slice("/workspace-assets/".length):path.slice(1);
  if(!["chat.css","navigation.css","navigation.js","browser-view.css","owner-terminal.css","admin.css","agent-portrait.js","agent-profile.js","agent-profile.css","agent-profile/catalog.json","agent-profile/echo/neutral.png","agent-profile/echo/a-curious.mp4","agent-profile/echo/b-thoughtful.mp4","agent-profile/echo/c-playful.mp4",...catalog.profiles.map(entry=>"agent-profile/portraits/"+entry.id+".webp")].includes(filename)){await route.fulfill({status:404});return;}
  if(filename.endsWith(".webp"))loadedPortraits.add(filename.split("/").at(-1));
  await route.fulfill({status:200,contentType:filename.endsWith(".js")?"text/javascript":filename.endsWith(".css")?"text/css":filename.endsWith(".json")?"application/json":filename.endsWith(".mp4")?"video/mp4":filename.endsWith(".png")?"image/png":"image/webp",body:await readFile(new URL(filename,root)),
    headers:{"Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'","Cache-Control":"no-store"}});
});
const page=await context.newPage();await cover(page);page.on("pageerror",error=>errors.push(error.message));
const status=()=>page.locator(".agent-profile-status");
const save=()=>page.getByRole("button",{name:"Save changes",exact:true});
const appearance=()=>page.getByRole("tab",{name:"Appearance",exact:true});
const identity=()=>page.getByRole("tab",{name:"Identity",exact:true});
const radio=(name)=>page.getByRole("radio",{name});
const noOverflow=async()=>expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
try{
  await page.goto(`${origin}/agent`);
  await expect(page.locator("#agent-profile-name")).toBeVisible();await expect(save()).toBeDisabled();
  await expect(page.locator("#agent-profile-link .rh-action-label")).toHaveText("Your Agent");
  await expect(page.locator("#agent-profile-link")).toHaveAttribute("aria-current","page");
  await expect(page.locator(".rh-header-name")).toHaveText("Your Agent");
  await expect(page.locator(".rh-header-portrait>svg")).toBeHidden();await expect(page.locator("#agent-profile-link>svg")).toBeHidden();
  await expect(page.locator(".rh-header-status")).toHaveAttribute("aria-label","Ready for your next message");
  expect(posts.length).toBe(0);expect(profileReads).toBe(1);
  expect([...loadedPortraits].every(file=>["ember.webp","moss.webp","aster.webp","lumi.webp"].includes(file))).toBe(true);
  await expect(page.locator(".agent-intro-disclosure")).not.toHaveAttribute("open","");
  // Native radio keys and tab keys stay accessible; the selected theme loads only its characters.
  await radio("Hearthside").focus();await page.keyboard.press("ArrowRight");
  await expect(radio("Kiln Club")).toBeChecked();await expect(radio("Miro")).toBeChecked();
  await radio("Nori").check();await page.locator("#agent-profile-name").fill("Bramble");
  await expect(page.locator(".rh-header-name")).toHaveText("Bramble");
  await expect(page.locator("#agent-profile-link .rh-action-label")).toHaveText("Bramble");
  await appearance().click();
  for(const size of [48,80,128]){
    await radio(size+" px").check();
    expect((await page.locator(".rh-header-portrait").boundingBox()).width).toBe(size);
    expect((await page.locator(".agent-profile-preview>img").boundingBox()).width).toBe(size);
  }
  await radio("80 px").check();await radio("Clay").check();await radio("Evening").check();
  await page.getByRole("switch",{name:"Playful interface icons"}).uncheck();
  await expect(page.locator("html")).toHaveAttribute("data-icon-animation","off");
  await expect(page.locator("html")).toHaveAttribute("data-agent-state-motion","on");
  expect(await page.locator('.rh-header-status [data-part="sleep1"]').evaluate(node=>getComputedStyle(node).animationName)).toBe("rh-sleep");
  await page.getByRole("switch",{name:"Agent state animation"}).uncheck();
  await expect(page.locator("html")).toHaveAttribute("data-agent-state-motion","off");
  await expect(page.locator("html")).toHaveAttribute("data-rh-surface","night");
  const chromeContrast=await page.evaluate(()=>{
    const checks=document.createElement("section");checks.id="chrome-surface-checks";
    checks.innerHTML='<div class="owner-terminal"><div class="owner-terminal-header"><h2>Terminal</h2></div></div><div class="browser-view"><div class="browser-address"><button class="rh-action">Back</button></div></div><section class="admin-section"><dl><dt>Session</dt><dd>Read only</dd></dl></section><div id="empty"><p>Start a chat</p></div><p class="turn-error">Could not send</p><div class="library-file"><div class="library-file-meta"><a href="/fixture">Download</a></div></div><div id="notice"><span>Connection warning</span><button class="rh-action">Dismiss</button></div><button id="latest">Latest message</button>';
    document.querySelector("main").append(checks);
    const luminance=rgb=>{const colors=rgb.match(/[\d.]+/g).slice(0,3).map(value=>Number(value)/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4);return colors[0]*.2126+colors[1]*.7152+colors[2]*.0722;};
    const contrast=(fg,bg)=>{const a=luminance(fg),b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
    const terminal=checks.querySelector(".owner-terminal"),address=checks.querySelector(".browser-address"),admin=checks.querySelector(".admin-section");
    const paper=getComputedStyle(document.documentElement).backgroundColor;
    const values=[contrast(getComputedStyle(terminal.querySelector("h2")).color,getComputedStyle(terminal).backgroundColor),contrast(getComputedStyle(address.querySelector("button")).color,getComputedStyle(address).backgroundColor),contrast(getComputedStyle(admin.querySelector("dt")).color,getComputedStyle(admin).backgroundColor),
      contrast(getComputedStyle(checks.querySelector("#empty p")).color,paper),contrast(getComputedStyle(checks.querySelector(".turn-error")).color,paper),contrast(getComputedStyle(checks.querySelector(".library-file-meta a")).color,getComputedStyle(checks.querySelector(".library-file")).backgroundColor),contrast(getComputedStyle(checks.querySelector("#notice button")).color,getComputedStyle(checks.querySelector("#notice")).backgroundColor),contrast(getComputedStyle(checks.querySelector("#latest")).color,getComputedStyle(checks.querySelector("#latest")).backgroundColor)];
    checks.remove();return values;
  });
  for(const value of chromeContrast)expect(value).toBeGreaterThanOrEqual(4.5);
  await save().click();await expect(status()).toHaveText("Saved.");
  await radio("Tide").check();await page.getByRole("button",{name:"Discard",exact:true}).click();
  await expect(appearance()).toHaveAttribute("aria-selected","true");await expect(appearance()).toBeFocused();await expect(radio("Clay")).toBeChecked();
  expect(posts.at(-1).csrf).toBe("fixture");expect(posts.at(-1).body).toMatchObject({schema:initial.schema,revision:0,name:"Bramble",theme:"kiln",portrait:"nori",accent:"clay",surface:"night",stateMotion:false,iconMotion:false});
  await page.reload();await expect(page.locator("#agent-profile-name")).toHaveValue("Bramble");await expect(save()).toBeDisabled();
  await page.locator("#agent-profile-name").fill("Unpublished");await page.getByRole("button",{name:"Discard",exact:true}).click();
  await expect(page.locator("#agent-profile-name")).toHaveValue("Bramble");await expect(page.locator(".rh-header-name")).toHaveText("Bramble");
  // Markup is rendered as literal text and never supplies an element or executable handler.
  const markup='<img src=x onerror=evil()>';
  await page.locator("#agent-profile-name").fill(markup);await page.locator(".agent-intro-disclosure summary").click();
  await page.locator("#agent-profile-intro").fill('مرحبا 👩‍💻 <script>evil()</script>');await save().click();await expect(status()).toHaveText("Saved.");
  await expect(page.locator(".agent-profile-preview h2")).toHaveText(markup);
  expect(await page.locator(".agent-profile-preview script,.agent-profile-preview h2 img").count()).toBe(0);
  // Failed/conflicting saves keep the draft and cannot overwrite another tab's revision.
  await page.locator("#agent-profile-name").fill("Keep this draft");failure="service_unavailable";
  await save().click();await expect(status()).toContainText("Your draft is kept");await expect(page.locator("#agent-profile-name")).toHaveValue("Keep this draft");
  failure="agent_profile_conflict";await save().click();await expect(status()).toContainText("changed in another tab");
  await expect(page.locator("#agent-profile-name")).toHaveValue("Keep this draft");failure=null;
  saved={...saved,revision:saved.revision+1,name:"Other tab"};await page.getByRole("button",{name:"Discard",exact:true}).click();
  await expect(page.locator("#agent-profile-name")).toHaveValue("Other tab");
  // Actual storage events reload a clean tab and preserve a dirty tab's work.
  const other=await context.newPage();other.on("pageerror",error=>errors.push(error.message));await cover(other);
  await other.goto(`${origin}/agent`);await expect(other.locator("#agent-profile-name")).toHaveValue("Other tab");
  await appearance().click();
  await other.locator("#agent-profile-name").fill("From the other tab");await other.getByRole("button",{name:"Save changes",exact:true}).click();
  await expect(page.locator("#agent-profile-name")).toHaveValue("From the other tab");await expect(appearance()).toHaveAttribute("aria-selected","true");await identity().click();
  await page.locator("#agent-profile-name").fill("Protected draft");
  await other.locator("#agent-profile-name").fill("Second saved name");await other.getByRole("button",{name:"Save changes",exact:true}).click();
  await expect(status()).toContainText("Your draft is kept");await expect(page.locator("#agent-profile-name")).toHaveValue("Protected draft");
  await page.getByRole("button",{name:"Discard",exact:true}).click();await expect(page.locator("#agent-profile-name")).toHaveValue("Second saved name");
  await appearance().click();await radio("Follow device").check();await page.emulateMedia({colorScheme:"dark"});await expect(page.locator("html")).toHaveAttribute("data-rh-surface","night");
  await page.emulateMedia({colorScheme:"light"});await expect(page.locator("html")).toHaveAttribute("data-rh-surface","paper");
  await page.getByRole("switch",{name:"Agent state animation"}).check();await page.getByRole("switch",{name:"Playful interface icons"}).check();
  await page.emulateMedia({reducedMotion:"reduce"});await expect(page.locator("html")).toHaveAttribute("data-icon-animation","off");await expect(page.locator("html")).toHaveAttribute("data-agent-state-motion","off");
  await page.emulateMedia({reducedMotion:"no-preference"});await expect(page.locator("html")).toHaveAttribute("data-icon-animation","on");await expect(page.locator("html")).toHaveAttribute("data-agent-state-motion","on");
  await page.getByRole("tab",{name:"Appearance",exact:true}).focus();await page.keyboard.press("ArrowLeft");await expect(identity()).toBeFocused();await expect(identity()).toHaveAttribute("aria-selected","true");
  await page.locator("#agent-profile-name").fill("Mobile companion");
  for(const width of [390,320]){
    await page.setViewportSize({width,height:844});await noOverflow();
    await appearance().click();
    for(const size of [48,80,128]){
      await radio(size+" px").check();await noOverflow();
      const portrait=await page.locator(".rh-header-portrait").boundingBox();
      expect(portrait.width).toBe(size);
      const brand=await page.locator("header .brand").boundingBox();expect(portrait.y).toBeGreaterThanOrEqual(brand.y+brand.height);
    }
    await radio("80 px").check();await identity().click();
    const geometry=await page.locator(".rh-header-portrait").boundingBox();
    expect(Math.abs(geometry.x+geometry.width/2-width/2)).toBeLessThan(1);
    await page.locator("#navigation-toggle").click();await expect(page.locator("#agent-profile-link")).toBeFocused();
    expect(await page.locator("main").evaluate(node=>node.inert)).toBe(true);
    await page.keyboard.press("Escape");await expect(page.locator("#navigation-toggle")).toBeFocused();
    expect(await page.locator("main").evaluate(node=>node.inert)).toBe(false);
    await page.locator(".agent-profile-preview").scrollIntoViewIfNeeded();await noOverflow();
  }
  await page.locator("main").evaluate(node=>{node.scrollTop=0;});await page.mouse.move(315,840);await page.locator("#agent-profile-name").focus();
  await expect.poll(()=>page.locator("#navigation-toggle").evaluate(node=>node.getAnimations({subtree:true}).length)).toBe(0);
  await page.screenshot({path:"/private/tmp/radhouse-saved-agent-mobile.png",fullPage:true});
  await page.setViewportSize({width:1280,height:900});await page.locator("main").evaluate(node=>{node.scrollTop=0;});await page.mouse.move(1275,895);await page.screenshot({path:"/private/tmp/radhouse-saved-agent-desktop.png",fullPage:true});
  await page.locator("#agent-profile-name").fill("W".repeat(32));await expect(save()).toBeEnabled();
  expect(await page.locator("#agent-profile-link").evaluate(node=>node.scrollWidth<=node.clientWidth)).toBe(true);
  await page.locator("#agent-profile-name").fill("🙂".repeat(32));await expect(save()).toBeEnabled();
  await page.locator("#agent-profile-name").fill("🙂".repeat(33));await expect(save()).toBeDisabled();await expect(status()).toHaveText("Use up to 32 characters.");
  // Echo has the same selectable dimensions as static portraits, with durable Save.
  await page.getByRole("button",{name:"Discard",exact:true}).click();await identity().click();
  await radio("Signal Station").check();await radio("Echo").check();await appearance().click();
  await page.emulateMedia({reducedMotion:"reduce"});
  for(const width of [1280,390,320]){
    await page.setViewportSize({width,height:900});
    for(const size of [48,80,128]){
      await radio(size+" px").check();await noOverflow();
      expect((await page.locator(".rh-header-portrait").boundingBox()).width).toBe(size);
      expect((await page.locator(".agent-profile-preview>.rh-animated-portrait").boundingBox()).width).toBe(size);
    }
  }
  await save().click();await expect(status()).toHaveText("Saved.");
  await page.evaluate(()=>profile.load());await appearance().click();await expect(radio("128 px")).toBeChecked();
  await radio("80 px").check();await save().click();await expect(status()).toHaveText("Saved.");
  await page.setViewportSize({width:1280,height:900});await page.screenshot({path:"/private/tmp/radhouse-echo-profile-desktop.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:"/private/tmp/radhouse-echo-profile-mobile.png",fullPage:true});
  // An expired session clears identity/drafts and hides the shared shell.
  authenticated=false;
  await page.evaluate(()=>profile.load());await expect(page.locator("#profile .agent-profile-editor")).toBeEmpty();
  await expect(page.locator(".rh-header-identity")).toBeHidden();expect(await page.evaluate(()=>profile.profile)).toBeNull();
  // A response arriving after sign-out cannot put private profile text back into the shell.
  await page.evaluate(async value=>{
    let complete;const response=new Promise(resolve=>{complete=resolve;});
    profile.request=async()=>response;
    const pending=profile.load();profile.clear();complete(value);await pending;
  },saved);
  await expect(page.locator("#profile .agent-profile-editor")).toBeEmpty();
  expect(await page.evaluate(()=>profile.profile)).toBeNull();expect(await page.locator("video").count()).toBe(0);await expect(page.locator(".rh-header-name")).toHaveText("Your Agent");
  expect(errors).toEqual([]);console.log("Saved agent identity/appearance: persistence, safe text, conflicts, two-tab drafts, motion, keyboard/focus, eight dark-surface contrast checks, 390/320px and auth races passed.");
}finally{await closeBrowser(browser);}
