// Real DOM, clipboard and motion checks with synthetic authenticated content.
import {readFile,mkdir} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import assert from "node:assert/strict";
const modulePath=process.env.RADHOUSE_PLAYWRIGHT_MODULE || new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).pathname;
const {chromium,expect}=await import(pathToFileURL(modulePath).href);
const browser=await chromium.launch({headless:true});
const origin="http://127.0.0.1:61486",root=new URL("../",import.meta.url);
const evidence=process.env.RADHOUSE_DESIGN_EVIDENCE;
if(evidence)await mkdir(evidence,{recursive:true});
const context=await browser.newContext({viewport:{width:1280,height:900},permissions:["clipboard-read","clipboard-write"]});
const page=await context.newPage(),errors=[],browserRequests=[];
page.on("pageerror",error=>errors.push(error.message));
const answer="Begin with one small step.\n\n```js\nconst morning = 'quiet';\n```";
const staticNames=["index.html","chat.css","chat.js","format.js","browser-view.js","browser-view.css","navigation.js","navigation.css","library.js"];
await context.route(origin+"/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  const json=value=>route.fulfill({contentType:"application/json",body:JSON.stringify(value)});
  if(path==="/auth/session")return json({username:"alice",csrf_token:"fixture",management:{read:true,write:false},features:{browser:true,browser_control:true,documents:true}});
  if(path==="/chat/history" || path==="/chat/reply")return json({turns:[{seq:1,request_id:"fixture-answer",text:"Help me begin the morning with a little more space.",status:"completed",output:answer,attachments:[]}],older_before:null});
  if(path.startsWith("/chat/browser")){browserRequests.push(path);return json({state:"idle"});}
  let file=path==="/" ? "src/radhouse/chat/static/index.html" : null;
  const name=path.split("/").at(-1);
  if(staticNames.includes(name))file="src/radhouse/chat/static/"+name;
  if(["interface-preview.html","interface-preview.js","radhouse-mark.svg","favicon.svg"].includes(name))file="brand/"+name;
  if(!file)return route.fulfill({status:404});
  return route.fulfill({contentType:name.endsWith(".js")?"text/javascript":name.endsWith(".css")?"text/css":name.endsWith(".svg")?"image/svg+xml":"text/html",body:await readFile(new URL(file,root))});
});
try{
  await page.goto(origin);
  const copy=page.getByRole("button",{name:"Copy answer",exact:true});
  await expect(copy).toBeVisible();
  for(const name of ["Chat","Library","Browser","Settings","Infrastructure"]){
    const link=page.getByRole("navigation",{name:"Main navigation"}).getByRole("link",{name,exact:true});
    await expect(link.locator("svg")).toHaveAttribute("aria-hidden","true");
  }
  assert.ok(browserRequests.every(path=>path==="/chat/browser"),"Chat may check context status but must not allocate or read browser frames");
  // A delayed real clipboard write must not show success before acknowledgement.
  await page.evaluate(()=>{
    const original=navigator.clipboard.writeText.bind(navigator.clipboard);window.originalWrite=original;
    navigator.clipboard.writeText=text=>new Promise((resolve,reject)=>{window.releaseCopy=()=>original(text).then(resolve,reject);});
  });
  await copy.click();await expect(copy).toHaveAttribute("aria-busy","true");await expect(copy).toBeDisabled();
  await expect(copy.locator("svg")).toHaveAttribute("data-icon","clipboard");
  await page.evaluate(()=>window.releaseCopy());
  const copied=page.getByRole("button",{name:"Copied",exact:true});
  await expect(copied).toHaveAttribute("data-state","success");await expect(copied.locator("svg")).toHaveAttribute("data-icon","check");
  assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),answer);
  await expect(page.locator("#radhouse-copy-status")).toHaveText("Answer copied.");
  if(evidence)await page.screenshot({path:evidence+"/chat-copy-success.png"});
  await expect(copy).toBeVisible({timeout:4000});await expect(copy.locator("svg")).toHaveAttribute("data-icon","clipboard");
  await page.evaluate(()=>{navigator.clipboard.writeText=()=>Promise.reject(new Error("denied"));});
  await copy.click();
  const failure=page.getByRole("button",{name:"Copy unavailable",exact:true});
  await expect(failure).toHaveAttribute("data-state","error");await expect(failure.locator("svg")).toHaveAttribute("data-icon","warning");
  await expect(page.locator("#radhouse-copy-status")).toHaveText("Copy unavailable. Select the text to copy it.");
  await expect(copy).toBeVisible({timeout:4000});await expect(copy).not.toHaveAttribute("title",/.+/);
  await page.evaluate(()=>{navigator.clipboard.writeText=window.originalWrite;});
  await copy.focus();await page.keyboard.press("Tab");await page.keyboard.press("Shift+Tab");await expect(copy).toBeFocused();
  assert.equal(await copy.evaluate(node=>getComputedStyle(node).outlineStyle),"solid");
  const code=page.locator('.code-header button[data-label="Copy code"]');await code.press("Enter");
  await expect(code.locator("svg")).toHaveAttribute("data-icon","check");
  await expect(code).toBeFocused();
  assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),"const morning = 'quiet';");
  // Inspect the presentation fixture with the actual BrowserView/formatter/icons.
  await page.goto(origin+"/brand/interface-preview.html");
  await expect(page.getByRole("button",{name:"Open browser",exact:true})).toBeVisible();
  const initialRequests=browserRequests.length;
  await page.getByRole("button",{name:"Open browser",exact:true}).click();
  await expect(page.locator("#preview-browser img")).toBeVisible();
  assert.equal(browserRequests.length,initialRequests,"Specimen must use only its in-memory adapter");
  const refresh=page.locator('[data-sample="refresh"]');
  await refresh.hover();await page.waitForTimeout(200);
  assert.notEqual(await refresh.locator("svg").evaluate(node=>getComputedStyle(node).transform),"none");
  await refresh.click();
  assert.equal(await refresh.locator("svg").evaluate(node=>node.getAnimations().some(animation=>animation.effect.getTiming().duration===480)),true);
  const back=page.locator('[data-sample="back"]');await back.click();
  assert.equal(await back.locator("svg").evaluate(node=>node.getAnimations().some(animation=>animation.effect.getTiming().duration===360)),true);
  const agent=page.locator('[data-sample="agent"]');await agent.click();
  assert.equal(await agent.locator("svg path").nth(1).evaluate(node=>node.getAnimations().some(animation=>animation.effect.getTiming().duration===420)),true);
  // Reduced motion suppresses both hover transforms and click animation.
  await page.waitForTimeout(600);await page.emulateMedia({reducedMotion:"reduce"});
  await refresh.hover();await refresh.click();
  assert.equal(await refresh.locator("svg").evaluate(node=>getComputedStyle(node).transform),"none");
  assert.equal(await refresh.locator("svg").evaluate(node=>node.getAnimations().length),0);
  await agent.hover();await agent.click();
  assert.equal(await agent.locator("svg path").nth(1).evaluate(node=>getComputedStyle(node).transform),"none");
  assert.equal(await agent.locator("svg path").nth(1).evaluate(node=>node.getAnimations().length),0);
  await page.emulateMedia({reducedMotion:"no-preference"});
  await page.mouse.move(0,0);await page.waitForTimeout(200);
  if(evidence)await page.screenshot({path:evidence+"/interface-specimen-desktop.png",fullPage:true});
  for(const width of [390,320]){
    await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Overflow at ${width}px`);
    for(const name of ["Back","Refresh","Go","Return to agent","Close browser"]){
      const button=page.locator("#preview-browser").getByRole("button",{name,exact:true});
      const rect=await button.boundingBox();assert.ok(rect.height>=44 && rect.width>=40,`${name} needs a generous touch target`);
    }
    if(evidence && width===390)await page.screenshot({path:evidence+"/interface-specimen-mobile.png",fullPage:true});
  }
  assert.deepEqual(errors,[]);
  console.log("Interface checks passed: delayed/denied/keyboard clipboard, named SVGs, distinct hover/click, reduced motion, 390/320px layout and touch targets.");
}finally{await browser.close();}
