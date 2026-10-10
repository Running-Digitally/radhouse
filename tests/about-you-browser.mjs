// Real Chromium with synthetic HTTP responses; no owner profile or native initialization.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE?pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href:new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const browser=await chromium.launch({headless:true,
  ...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
const origin="http://127.0.0.1:61491",staticRoot=new URL("../src/radhouse/chat/static/",import.meta.url);
const escaped="<img src=x onerror=window.injected=true> is a saved note, not executable markup.";
let calls=[],failure=null,hold=false,held=null;
let entries=[escaped,"One whole\nmultiline note with bare § intact."];
const snapshot=()=>({schema:"radhouse.saved-memory.v1",checked_at:"2026-10-08T17:00:00+00:00",
  sources:[{target:"user",source_filename:"USER.md",state:"available",entries,
    file_modified_at:"2026-10-07T16:00:00+00:00",complete:true},
  {target:"memory",source_filename:"MEMORY.md",state:"missing",entries:[],file_modified_at:null,complete:true}]});
const context=await browser.newContext({viewport:{width:1100,height:900}}),page=await context.newPage(),errors=[];
page.on("pageerror",error=>errors.push(error.message));
await page.addInitScript(()=>{
  const realFetch=fetch;
  window.ignoreAbort=false;
  window.fetch=(path,options)=>realFetch(path,window.ignoreAbort?{...options,signal:undefined}:options);
});
await context.route(origin+"/**",async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  if(path==="/chat/about-you") {
    calls.push({method:request.method(),body:request.postData()});
    const value=snapshot(),status=failure||200;
    if(hold){hold=false;await new Promise(resolve=>{held=resolve;});}
    return route.fulfill({status,contentType:"application/json",body:JSON.stringify(status===200?value:{error:status===401?"authentication_required":"memory_unavailable"}),headers:{"Cache-Control":"no-store"}});
  }
  if(path==="/bootstrap.js")return route.fulfill({contentType:"text/javascript",body:`
    window.authRequired=0;
    window.aboutYou=new window.RadhouseAboutYou({container:document.getElementById("notes"),
      onAuthRequired:()=>{window.authRequired++;},
      request:async(path,_body,_anonymous,signal)=>{
        const response=await fetch(path,{credentials:"same-origin",cache:"no-store",signal});
        const value=await response.json();
        if(!response.ok)throw Object.assign(new Error(value.error),{status:response.status});
        return value;
      }});`});
  if(["/about-you.js","/about-you.css","/chat.css"].includes(path))return route.fulfill({
    contentType:path.endsWith(".js")?"text/javascript":"text/css",body:await readFile(new URL(path.slice(1),staticRoot))});
  return route.fulfill({contentType:"text/html; charset=utf-8",body:'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/chat.css"><link rel="stylesheet" href="/about-you.css"><script src="/about-you.js" defer></script><script src="/bootstrap.js" defer></script></head><body><main style="max-width:850px;margin:auto;padding:20px"><h1>About You</h1><div id="notes"></div></main></body></html>'});
});
try {
  await page.goto(origin+"/about-you");await expect(page.getByRole("heading",{name:"About You",exact:true})).toBeVisible();
  if(calls.length)throw new Error("Constructing the page read notes before explicit loading");
  await page.evaluate(()=>aboutYou.load());
  await expect(page.getByRole("heading",{name:"User notes",exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:"Agent notes",exact:true})).toBeVisible();
  await expect(page.locator(".about-you-notes li")).toHaveText(entries);
  await expect(page.getByText("No saved notes file yet.",{exact:true})).toBeVisible();
  if(await page.locator("#notes img").count()||await page.evaluate(()=>window.injected))throw new Error("Saved note executed markup");
  await expect(page.locator(".about-you-source-meta").first()).toContainText("USER.md · Last changed");
  await expect(page.locator(".about-you-source-meta").last()).toHaveText("MEMORY.md");
  await expect(page.locator(".about-you-status")).toContainText("Checked");
  // A response that ignores cancellation still cannot repaint notes after sign-out.
  hold=true;await page.evaluate(()=>{window.ignoreAbort=true;void aboutYou.load();});
  await expect.poll(()=>typeof held).toBe("function");
  await page.evaluate(()=>aboutYou.clear());held();held=null;
  await page.waitForTimeout(100);await expect(page.locator(".about-you-notes li")).toHaveCount(0);
  await expect(page.locator(".about-you-status")).toHaveText("");
  failure=503;await page.evaluate(()=>aboutYou.load());
  await expect(page.getByRole("heading",{name:"About You",exact:true})).toBeVisible();
  await expect(page.locator(".about-you-status")).toHaveText("Saved notes are unavailable right now. Refresh to try again.");
  failure=null;entries=["Fresh saved note", "A long note "+"x".repeat(6000)];
  await page.getByRole("button",{name:"Refresh",exact:true}).click();
  await expect(page.locator(".about-you-notes li")).toHaveText(entries);
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error("Saved notes overflow the mobile page");
  failure=401;await page.evaluate(()=>aboutYou.load());
  expect(await page.evaluate(()=>authRequired)).toBe(1);
  await expect(page.locator(".about-you-notes li")).toHaveCount(0);
  if(calls.some(call=>call.method!=="GET"||call.body!==null))throw new Error("The saved-note page sent a mutation");
  if(await page.evaluate(()=>localStorage.length))throw new Error("The page stored private notes locally");
  if(errors.length)throw new Error(errors.join("; "));
  console.log(JSON.stringify({result:"passed",httpReads:calls.length,readOnly:true,escapedContent:true,
    lateResponseSuppressed:true,refreshRecovery:true,authExpiryClearsNotes:true,mobileNoOverflow:true}));
} finally {held?.();await browser.close();}
