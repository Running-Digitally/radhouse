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
let replyState="completed";
const answer="Begin with one small step.\n\n```js\nconst morning = 'quiet';\n```";
const staticNames=["index.html","chat.css","chat.js","format.js","browser-view.js","browser-view.css","navigation.js","navigation.css","library.js"];
await context.route(origin+"/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  const json=value=>route.fulfill({contentType:"application/json",body:JSON.stringify(value)});
  if(path==="/auth/session")return json({username:"alice",csrf_token:"fixture",management:{read:true,write:false},features:{browser:true,browser_control:true,documents:true}});
  if(path==="/chat/history" || path==="/chat/reply")return json({turns:[{seq:1,request_id:"fixture-answer",text:"Help me begin the morning with a little more space.",status:replyState,output:replyState==="completed"?answer:"",attachments:[]}],older_before:null});
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
  await expect(copy.locator(".rh-action-label")).toHaveText("Copy");
  await expect(page.locator(".message-label .rh-icon[data-icon=agent]")).toHaveAttribute("data-agent-state","complete");
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
  const code=page.locator('.code-header button[data-copy-kind="code"]');await code.press("Enter");
  await expect(code.locator("svg")).toHaveAttribute("data-icon","check");
  await expect(code).toBeFocused();
  assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),"const morning = 'quiet';");
  for(const [state,iconState] of [["awaiting_dispatch","waiting"],["running","thinking"]]){
    replyState=state;await page.reload();
    await expect(page.locator("#reply-status .rh-icon")).toHaveAttribute("data-agent-state",iconState);
    await expect(page.locator(".pending .rh-icon")).toHaveAttribute("data-agent-state",iconState);
  }
  replyState="completed";
  // Inspect the presentation fixture with the actual BrowserView/formatter/icons.
  await page.goto(origin+"/brand/interface-preview.html");
  await expect(page.getByRole("button",{name:"Open browser",exact:true})).toBeVisible();
  const initialRequests=browserRequests.length;
  await page.getByRole("button",{name:"Open browser",exact:true}).click();
  await expect(page.locator("#preview-browser img")).toBeVisible();
  assert.equal(browserRequests.length,initialRequests,"Specimen must use only its in-memory adapter");
  const sample=name=>page.locator(`[data-sample="${name}"]`);
  const animated=async locator=>locator.evaluate(node=>node.getAnimations({subtree:true}).filter(animation=>animation.playState==="running").map(animation=>({duration:animation.effect.getTiming().duration,frames:animation.effect.getKeyframes()})));
  // Measure the center through a full pending turn, at real and enlarged sizes.
  // CSS pixel pivots caused an orbit whenever the SVG was not exactly 24px.
  const spinnerCenters=await page.locator('#states [data-state="pending"] .rh-icon').evaluate(svg=>{
    const animation=svg.getAnimations()[0];animation.pause();
    const result=[];
    for(const size of [18,20,21,24,72]){
      svg.style.width=svg.style.height=size+"px";const points=[];
      for(const time of [0,225,450,675]){
        animation.currentTime=time;getComputedStyle(svg).transform;
        const center=new DOMPoint(12,12).matrixTransform(svg.getScreenCTM());points.push({x:center.x,y:center.y});
      }
      result.push({size,drift:Math.max(...points.map(point=>Math.hypot(point.x-points[0].x,point.y-points[0].y)))});
    }
    svg.style.removeProperty("width");svg.style.removeProperty("height");animation.play();return result;
  });
  for(const {size,drift} of spinnerCenters)assert.ok(drift<.1,`Pending spinner center drifts ${drift}px at ${size}px`);
  for(const id of ["desktop-browser","desktop-terminal-context"]){
    const icon=page.locator(`#${id} .rh-icon`);const rect=await icon.boundingBox();
    assert.equal(rect.width,20);assert.equal(rect.height,20);
  }
  const share=sample("terminal-context");await share.click();
  assert.ok((await animated(share.locator('[data-part="packet"]'))).length,"Simplified context icon still sends its packet");
  const refresh=sample("refresh");await refresh.hover();
  assert.ok((await animated(refresh)).some(a=>a.duration===500 && a.frames.some(frame=>frame.strokeDashoffset)),"Refresh hover re-inks the arc");
  await refresh.click();assert.ok((await animated(refresh)).some(a=>a.duration===760 && a.frames.some(frame=>frame.transform?.includes("360deg"))));
  for(const name of ["menu","chat","library","clipboard","browser","about-you"]){
    const button=sample(name);await button.hover();
    assert.ok((await animated(button)).some(a=>a.frames.some(frame=>frame.strokeDashoffset)),`${name} writes its lines`);
  }
  const keyboard=sample("keyboard");await keyboard.hover();
  assert.equal(await keyboard.locator('[data-part^="key"]').evaluateAll(nodes=>nodes.filter(node=>node.getAnimations().length).length),4);
  await keyboard.click();assert.equal(await keyboard.locator('[data-part^="key"]').evaluateAll(nodes=>nodes.filter(node=>node.getAnimations().length).length),8);
  const eye=sample("eye");await eye.hover();assert.ok((await animated(eye)).some(a=>a.duration===520 && a.frames.some(frame=>frame.transform==="scaleY(0.04)" || frame.transform==="scaleY(.04)")));
  const eyeSvg=await eye.locator("svg").elementHandle();
  await eye.evaluate(node=>RadhouseIcons.decorate(node,"eye","Show view"));
  assert.equal(await eyeSvg.evaluate(node=>node===document.querySelector('[data-sample="eye"] svg')),true,"Label changes preserve the animated eye");
  const infra=sample("infrastructure");await infra.click();
  assert.ok((await animated(infra)).some(a=>a.duration===760));
  assert.ok((await animated(infra)).some(a=>a.duration===240 && a.frames.some(frame=>frame.opacity===.15 || frame.opacity==="0.15")));
  const key=sample("key");await key.click();assert.ok((await animated(key)).some(a=>a.frames.some(frame=>frame.transform?.includes("-35deg"))));
  const close=sample("close");await close.click();const closeAnimations=await animated(close);
  assert.ok(closeAnimations.some(a=>a.frames.some(frame=>frame.transform==="scale(0.02)" || frame.transform==="scale(.02)")),"Close collapses into a point");
  assert.ok(closeAnimations.every(a=>a.frames.every(frame=>!frame.transform?.includes("rotate"))),"Close never rotates");
  assert.ok((await animated(close.locator('[data-part="star"]'))).length,"Close has a star flare");
  const check=sample("check");await check.click();assert.ok((await animated(check)).some(a=>a.duration===650 && a.frames.some(frame=>frame.strokeDashoffset)),"Check is drawn by hand");
  for(const state of ["thinking","idle","working","waiting","paused","complete","error"]){
    await page.locator("#agent-state").selectOption(state);await expect(page.locator("#agent-stage .rh-icon")).toHaveAttribute("data-agent-state",state);
  }
  await page.getByRole("button",{name:"Play agent journey",exact:true}).click();
  await expect(page.locator("#agent-stage .rh-icon")).toHaveAttribute("data-agent-state","thinking");
  await expect(page.locator("#agent-stage .rh-icon")).toHaveAttribute("data-agent-state","working",{timeout:3500});
  await page.locator("#agent-state").selectOption("thinking");
  await expect(page.getByRole("button",{name:"Play agent journey",exact:true})).toBeEnabled();
  const smoke=page.locator('#agent-stage [data-part="smoke1"]');
  assert.ok((await animated(smoke)).length,"Thinking produces chimney smoke");
  await expect(page.locator("#future-context")).not.toBeChecked();
  await page.locator("#future-context").check();await expect(page.locator("#future-context-note")).toContainText("On");
  await page.getByRole("button",{name:"Hide terminal",exact:true}).click();await expect(page.locator("#future-terminal-note")).toContainText("session retained");
  await page.getByRole("button",{name:"Close terminal",exact:true}).click();await expect(page.locator("#future-terminal-note")).toContainText("session ended");
  // Manual switch cancels in-flight motion, keeps static state cues, and persists.
  const toggle=page.getByRole("switch",{name:"Icon animation",exact:true});
  await toggle.uncheck();await expect(page.locator("html")).toHaveAttribute("data-icon-animation","off");
  await expect.poll(()=>smoke.evaluate(node=>node.getAnimations().length)).toBe(0);
  assert.ok(Number(await smoke.evaluate(node=>getComputedStyle(node).opacity))>0,"Smoke remains a static state cue");
  await close.click();assert.equal((await animated(close)).length,0);
  await page.reload();await expect(toggle).not.toBeChecked();
  // Cross-tab preferences propagate; reduced motion always takes precedence.
  const sibling=await context.newPage();await sibling.goto(origin+"/brand/interface-preview.html");
  await sibling.getByRole("switch",{name:"Icon animation",exact:true}).check();await expect(toggle).toBeChecked();await sibling.close();
  await page.emulateMedia({reducedMotion:"reduce"});await expect(toggle).toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-icon-animation","off");
  await expect(page.locator(".rh-appearance-note")).toContainText("reduced motion");
  await refresh.hover();await refresh.click();assert.equal((await animated(refresh)).length,0);
  await page.emulateMedia({reducedMotion:"no-preference"});await expect(page.locator("html")).toHaveAttribute("data-icon-animation","on");
  await page.getByRole("button",{name:"Open browser",exact:true}).click();
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
  console.log("Interface checks passed: acknowledged clipboard, semantic motion, agent states, persisted/cross-tab Appearance preference, reduced motion, 390/320px layout and touch targets.");
}finally{await browser.close();}
