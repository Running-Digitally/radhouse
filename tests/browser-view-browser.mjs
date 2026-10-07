// The observer receives real CDP screencast frames from the agent's one page.
// This is a local fixture proof, not qualification of the production driver.
import {readFile, mkdir} from "node:fs/promises";
import {createServer} from "node:http";
import {createHash} from "node:crypto";
import {pathToFileURL} from "node:url";
const modulePath = process.env.RADHOUSE_PLAYWRIGHT_MODULE || new URL("../web/node_modules/@playwright/test/index.mjs", import.meta.url).pathname;
const {chromium, expect: baseExpect} = await import(pathToFileURL(modulePath).href);
const expect = baseExpect.configure({timeout: 10000});
const script = await readFile(new URL("../src/radhouse/chat/static/browser-view.js", import.meta.url));
const style = await readFile(new URL("../src/radhouse/chat/static/browser-view.css", import.meta.url));
let latest = null, frameNumber = 0, requests = 0, mode = "normal", generation = "generation-1";
let held = [];
const hash = buffer => createHash("sha256").update(buffer).digest("hex");
const server = createServer((request, response) => {
  if (request.url === "/browser-view.js") {response.writeHead(200,{"Content-Type":"text/javascript"});response.end(script);return;}
  if (request.url === "/browser-view.css") {response.writeHead(200,{"Content-Type":"text/css"});response.end(style);return;}
  if (request.url?.startsWith("/chat/browser/frame?run_id=")) {
    requests++;
    const captured = latest;
    const send = () => {
      if (mode === "unauthorized") {response.writeHead(401);response.end();return;}
      if (mode === "unavailable") {response.writeHead(503);response.end();return;}
      response.writeHead(200, {"Content-Type":"image/jpeg", "Cache-Control":"no-store",
        "X-Radhouse-Browser-Generation": mode === "mismatch" ? "wrong-generation" : generation,
        "X-Radhouse-Browser-Frame-Id": String(frameNumber), "X-Radhouse-Browser-Received-At": String(Date.now()/1000)});
      response.end(mode === "oversize" ? Buffer.alloc(512*1024+1) : captured);
    };
    if (mode === "hold") held.push(send); else send();
    return;
  }
  response.writeHead(200, {"Content-Type":"text/html"});
  response.end(`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/browser-view.css"><style>body{margin:16px;font:16px system-ui}</style><div id="browser"></div><script src="/browser-view.js"></script><script>window.viewer=new BrowserView(document.getElementById('browser'));window.authEvents=0;document.addEventListener('browser-auth-required',()=>window.authEvents++);</script>`);
});
await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
const errors = [];
try {
  browser = await chromium.launch({headless:true});
  const agentContext = await browser.newContext({viewport:{width:960,height:540}});
  const agentPage = await agentContext.newPage();
  const cdp = await agentContext.newCDPSession(agentPage);
  await cdp.send("Page.enable");
  cdp.on("Page.screencastFrame", event => {
    latest = Buffer.from(event.data,"base64"); frameNumber++;
    void cdp.send("Page.screencastFrameAck", {sessionId:event.sessionId}).catch(()=>{});
  });
  await cdp.send("Page.startScreencast", {format:"jpeg",quality:65,maxWidth:960,maxHeight:540,everyNthFrame:1});
  await agentPage.setContent('<body style="margin:0;background:#113355;color:white;font:40px system-ui"><h1>Agent page: first step</h1><input aria-label="Agent input"></body>');
  await expect.poll(()=>latest?.length || 0).toBeGreaterThan(100);
  const viewerContext = await browser.newContext({viewport:{width:1200,height:900}});
  const page = await viewerContext.newPage();
  await page.addInitScript(() => {
    window.blobUrls = new Set(); window.lateFetch = false;
    const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = blob => {const url=create(blob);window.blobUrls.add(url);return url;};
    URL.revokeObjectURL = url => {window.blobUrls.delete(url);revoke(url);};
    const fetch = window.fetch.bind(window);
    window.fetch = (input,options) => fetch(input, window.lateFetch ? {...options,signal:undefined} : options);
  });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(origin);
  const update = (run="run-1", gen=generation) => page.evaluate(({run,gen}) => window.viewer.update({state:"live",run_id:run,generation:gen,url:"https://example.org/page"}),{run,gen});
  const img = page.locator(".browser-view-viewport img");
  const status = page.locator(".browser-view-status");
  const displayedHash = () => page.evaluate(async () => {
    const src=document.querySelector('.browser-view-viewport img').getAttribute('src');
    if (!src) return null;
    const bytes=await (await fetch(src)).arrayBuffer();
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
  });

  // The pixels are produced by Page.startScreencast on the page the agent edits.
  await update(); await expect(img).toBeVisible(); await expect(status).toHaveText("Live browser");
  const first = await displayedHash();
  const beforeChange = frameNumber;
  await agentPage.evaluate(()=>{document.body.style.background="#663311";document.querySelector('h1').textContent='Agent page: next step';});
  await expect.poll(()=>frameNumber).toBeGreaterThan(beforeChange);
  await expect.poll(displayedHash).not.toBe(first);
  await expect.poll(displayedHash).toBe(hash(latest));
  if (await img.evaluate(node=>node.naturalWidth) < 100) throw new Error("Actual streamed page frame was not decoded");

  // Hiding the viewer stops reads and leaves the agent's page available.
  await page.getByRole("button",{name:"Hide browser",exact:true}).click();
  await expect(img).toBeHidden();
  let count = requests; await page.waitForTimeout(1100);
  if (requests !== count) throw new Error("Hidden viewer kept polling");
  await agentPage.getByRole("textbox",{name:"Agent input"}).fill("Agent continues while hidden");
  await page.getByRole("button",{name:"Show browser",exact:true}).click();
  await expect.poll(()=>requests).toBeGreaterThan(count); await expect(img).toBeVisible();

  // Browsers in background do no frame requests; visibility resumes one loop.
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
  count=requests; await page.waitForTimeout(1100);
  if (requests!==count) throw new Error("Background viewer kept polling");
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));});
  await expect.poll(()=>requests).toBeGreaterThan(count);

  // An upstream failure removes stale pixels and reconnects without intervention.
  mode="unavailable"; await expect(status).toHaveText("Browser view is unavailable"); await expect(img).toBeHidden();
  mode="normal"; await expect(img).toBeVisible(); await expect(status).toHaveText("Live browser");
  for (const invalid of ["mismatch","oversize"]) {
    mode=invalid; await expect(status).toHaveText("Browser view is unavailable"); await expect(img).toBeHidden();
    mode="normal"; await expect(img).toBeVisible();
  }

  // URL metadata stays text even if an upstream fixture returns markup.
  await page.evaluate(()=>window.viewer.update({state:'live',run_id:'run-1',generation:'generation-1',url:'<img src=x onerror=window.injected=true>'}));
  await expect(page.locator(".browser-view-site")).toHaveText("<img src=x onerror=window.injected=true>");
  if (await page.evaluate(()=>window.injected)) throw new Error("URL metadata was executed");
  await page.setViewportSize({width:390,height:844});
  if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error("Mobile viewer overflows");
  if (process.env.RADHOUSE_BROWSER_SCREENSHOTS) {
    await mkdir(process.env.RADHOUSE_BROWSER_SCREENSHOTS,{recursive:true});
    await page.screenshot({path:process.env.RADHOUSE_BROWSER_SCREENSHOTS+"/browser-mobile.png",fullPage:true});
  }

  // Ignore abort deliberately: late old frames must still fail the epoch check.
  mode="hold"; await page.evaluate(()=>{window.lateFetch=true;window.viewer._cancel();window.viewer._schedule(0);});
  await expect.poll(()=>held.length).toBeGreaterThan(0);
  await page.evaluate(()=>window.viewer.stop());
  mode="normal"; for (const release of held.splice(0)) release();
  await page.waitForTimeout(250);
  await expect(page.locator("#browser")).toBeHidden(); await expect(img).not.toHaveAttribute("src", /.+/);
  if (await page.evaluate(()=>window.blobUrls.size)) throw new Error("Logout retained frame object URLs");

  // A new run/generation cannot display a late response from the previous run.
  await update(); await expect(img).toBeVisible();
  mode="hold"; await page.evaluate(()=>{window.viewer._cancel();window.viewer._schedule(0);});
  await expect.poll(()=>held.length).toBeGreaterThan(0);
  generation="generation-2"; await update("run-2",generation);
  mode="normal"; for (const release of held.splice(0)) release();
  await expect(img).toBeVisible();
  if (await page.evaluate(()=>window.viewer.run)!=="run-2") throw new Error("New run identity lost");

  // Server auth expiry clears pixels, emits one signal and stops all polling.
  mode="unauthorized"; await expect.poll(()=>page.evaluate(()=>window.authEvents)).toBe(1);
  await expect(page.locator("#browser")).toBeHidden(); await expect(img).not.toHaveAttribute("src",/.+/);
  count=requests; await page.waitForTimeout(1100);
  if (requests!==count || await page.evaluate(()=>window.blobUrls.size)) throw new Error("Expired auth retained frames or polling");
  await page.evaluate(()=>window.viewer.destroy());
  if (errors.length) throw new Error(errors.join("; "));
  console.log("Browser viewer proof passed: same-page CDP frames, hide/background cleanup, reconnect, scope changes and auth expiry.");
} finally {
  for (const release of held.splice(0)) release();
  if (browser) await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
