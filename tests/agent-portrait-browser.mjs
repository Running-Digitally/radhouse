// Qualify real media playback, rest timing, fallback and lifecycle without live services.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect:baseExpect}=await import(moduleUrl);
const expect=baseExpect.configure({timeout:10000});
const root=new URL("../src/radhouse/chat/static/",import.meta.url),origin="http://127.0.0.1:61396";
const browser=await chromium.launch({headless:true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
const requests=[],errors=[];
const fixture='<!doctype html><html><head><link rel="stylesheet" href="/navigation.css"><script src="/workspace-assets/agent-portrait.js" defer></script></head><body><main><img id="portrait" width="160" height="160" alt="Agent portrait"></main></body></html>';
try {
  const context=await browser.newContext({viewport:{width:390,height:844}});
  await context.route(`${origin}/**`,async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==="/"){await route.fulfill({contentType:"text/html",body:fixture,headers:{"Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; img-src 'self'"}});return;}
    const file=path.startsWith("/workspace-assets/")?path.slice(18):path.slice(1);
    if(!["agent-portrait.js","navigation.css","agent-profile/echo/neutral.png","agent-profile/echo/a-curious.mp4","agent-profile/echo/b-thoughtful.mp4","agent-profile/echo/c-playful.mp4"].includes(file)){await route.fulfill({status:404});return;}
    requests.push(file);
    await route.fulfill({contentType:file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":file.endsWith(".png")?"image/png":"video/mp4",body:await readFile(new URL(file,root))});
  });
  const page=await context.newPage();page.on("pageerror",e=>errors.push(e.message));
  await page.goto(origin);
  await page.evaluate(()=>RadhousePortrait.update(document.querySelector("img"),{stateMotion:true},{id:"ember"}));
  expect(requests.some(file=>file.endsWith(".mp4"))).toBe(false);
  await page.emulateMedia({reducedMotion:"reduce"});
  await page.evaluate(()=>RadhousePortrait.update(document.querySelector("img"),{stateMotion:true},{id:"echo"}));
  await expect(page.locator("video")).toBeHidden();
  expect(await page.locator("video").getAttribute("src")).toBeNull();
  expect(await page.locator("#portrait").getAttribute("src")).toContain("neutral.png");
  await page.evaluate(()=>{
    window.clipHistory=[];window.restStarted=performance.now();
    const video=document.querySelector("video");
    video.addEventListener("playing",()=>clipHistory.push({clip:new URL(video.currentSrc).pathname,rest:performance.now()-restStarted}));
    video.addEventListener("ended",()=>{restStarted=performance.now();});
  });
  await page.emulateMedia({reducedMotion:"no-preference"});
  await expect.poll(()=>page.evaluate(()=>clipHistory.length),{timeout:55000}).toBeGreaterThanOrEqual(4);
  const history=await page.evaluate(()=>window.clipHistory);
  expect(new Set(history.slice(0,3).map(item=>item.clip)).size).toBe(3);
  for(let i=0;i<history.length;i++){
    expect(history[i].rest).toBeGreaterThanOrEqual(1950);
    expect(history[i].rest).toBeLessThan(6800);
    if(i)expect(history[i].clip).not.toBe(history[i-1].clip);
  }
  await page.evaluate(()=>{Object.defineProperty(document,"hidden",{configurable:true,get:()=>true});document.dispatchEvent(new Event("visibilitychange"));});
  await expect(page.locator("video")).toBeHidden();
  expect(await page.locator("video").getAttribute("src")).toBeNull();
  await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event("visibilitychange"));RadhousePortrait.update(document.querySelector("img"),{stateMotion:false},{id:"echo"});});
  await expect(page.locator("video")).toBeHidden();expect(await page.locator("video").getAttribute("src")).toBeNull();
  await page.evaluate(()=>RadhousePortrait.clear(document.querySelector("img")));
  expect(await page.locator("video").count()).toBe(0);
  // A blocked asset must retain neutral rather than show a broken/blank portrait.
  let blocked=0;await context.route(`${origin}/workspace-assets/agent-profile/echo/*.mp4`,route=>{blocked++;return route.fulfill({status:404});});
  await page.evaluate(()=>RadhousePortrait.update(document.querySelector("img"),{stateMotion:true},{id:"echo"}));
  await expect.poll(()=>blocked).toBeGreaterThan(0);
  await expect.poll(()=>page.locator("video").getAttribute("src")).toBeNull();
  await expect(page.locator("video")).toBeHidden();
  await expect(page.locator("#portrait")).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({path:"/private/tmp/radhouse-echo-animation-mobile.png"});
  console.log(JSON.stringify({state:"passed",realClips:history,hiddenRelease:true,reducedMotion:true,savedMotionOff:true,errorFallback:true,pageErrors:errors}));
  await context.close();
} finally {await browser.close();}
