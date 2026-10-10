// Real DOM regression: two saved-login rows cannot consume an unsent sequence.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const browser=await chromium.launch({headless:true}),origin="http://127.0.0.1:61485";
try {
  const native=await browser.newPage({viewport:{width:960,height:540}});
  await native.setContent("<body>Disposable browser page</body>");
  const jpeg=await native.screenshot({type:"jpeg"});
  const page=await browser.newPage({viewport:{width:1200,height:900}});
  await page.route(origin+"/**",async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==="/browser-view.js")return route.fulfill({contentType:"text/javascript",body:await readFile(new URL("../src/radhouse/chat/static/browser-view.js",import.meta.url))});
    if(path==="/chat/browser/frame")return route.fulfill({contentType:"image/jpeg",body:jpeg,headers:{
      "X-Radhouse-Browser-Generation":"generation-1","X-Radhouse-Browser-Frame-Id":"frame-1",
      "X-Radhouse-Browser-Width":"960","X-Radhouse-Browser-Height":"540"}});
    return route.fulfill({contentType:"text/html",body:'<div id="browser"></div><script src="/browser-view.js"></script>'});
  });
  await page.goto(origin);
  await page.evaluate(()=>{
    window.calls=[];
    const items=[1,2].map(id=>({id:"login-"+id,label:"Account "+id,identifier:"owner-"+id,origin:"https://example.org"}));
    const request=async(path,body,method)=>{
      window.calls.push({path,body:structuredClone(body),method});
      if(path.endsWith("/list"))return {items};
      if(method==="DELETE")return new Promise(resolve=>{window.releaseRemoval=()=>resolve({removed:true});});
      return {outcome:"applied",sequence:body.sequence};
    };
    window.viewer=new window.BrowserView(document.getElementById("browser"),{persistent:true,request,tab:()=>"a8b1f224-53a5-4a0a-bc67-5e51c4f5e2a6"});
    viewer.controlEnabled=true;
    viewer.update({state:"live",generation:"generation-1",url:"https://example.org",control:{mode:"human",revision:1,
      lease_id:"lease-1",lease_expires_at:Date.now()/1000+60,next_sequence:1},can_return:true,vault_enabled:true});
  });
  await expect(page.locator("#browser img")).toBeVisible();
  await page.getByRole("button",{name:"Saved logins",exact:true}).click();
  const removals=page.getByRole("button",{name:"Remove",exact:true});
  await expect(removals).toHaveCount(2);
  // Queue the two DOM click handlers without making focus loss hide the panel.
  await removals.nth(0).evaluate(button=>button.dispatchEvent(new MouseEvent("click",{bubbles:true})));
  await expect(removals.nth(0)).toBeDisabled();await expect(removals.nth(1)).toBeDisabled();
  // A queued/programmatic click must also be guarded before sequence allocation.
  await removals.nth(1).evaluate(button=>button.dispatchEvent(new MouseEvent("click",{bubbles:true})));
  expect(await page.evaluate(()=>calls.filter(call=>call.method==="DELETE").length)).toBe(1);
  expect(await page.evaluate(()=>viewer.sequence)).toBe(2);
  await page.evaluate(()=>releaseRemoval());
  await expect.poll(()=>page.evaluate(()=>viewer.actionPending)).toBe(false);
  await page.evaluate(()=>viewer._input("navigate",{url:"https://example.org/next"}));
  expect(await page.evaluate(()=>calls.find(call=>call.path.endsWith("/input")).body.sequence)).toBe(3);
  await page.getByRole("button",{name:"Saved logins",exact:true}).click();
  await expect(removals).toHaveCount(2);
  const before=await page.evaluate(()=>viewer.sequence);
  await page.evaluate(()=>{viewer.inputUnconfirmed=true;viewer._renderControlState();});
  await expect(removals.nth(0)).toBeDisabled();await expect(removals.nth(1)).toBeDisabled();
  await removals.nth(1).evaluate(button=>button.dispatchEvent(new MouseEvent("click",{bubbles:true})));
  expect(await page.evaluate(()=>viewer.sequence)).toBe(before);
  expect(await page.evaluate(()=>calls.filter(call=>call.method==="DELETE").length)).toBe(1);
  console.log(JSON.stringify({result:"passed",twoRowConcurrency:true,unsentSequenceNotAllocated:true,nextInputSequence:3,unconfirmedInputBlocksRemoval:true}));
} finally {await browser.close();}
