// Live synthetic test: every intervention traverses the actual Selkies input
// and video connection. The loopback fixture supplies geometry and assertions;
// it is never used to perform the intervention.
import assert from "node:assert/strict";
import {readFile, mkdir, writeFile} from "node:fs/promises";
import {execFileSync} from "node:child_process";
import {pathToFileURL} from "node:url";

const {chromium, expect} = await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const links = JSON.parse(await readFile(process.env.RADHOUSE_SELKIES_LINKS, "utf8"));
const container = process.env.RADHOUSE_SELKIES_CONTAINER;
const output = process.env.RADHOUSE_SELKIES_OUTPUT;
await mkdir(output, {recursive: true, mode: 0o700});
const browser = await chromium.launch({channel: "chrome", headless: true});
const context = await browser.newContext({viewport: {width: 1500, height: 1100}, permissions: ["clipboard-read", "clipboard-write"]});
const failures = [], checks = [];
const feedbackSamples=[];
let diagnosticPage, diagnosticToken;
const check = name => checks.push(name);

function fixture() {
  return JSON.parse(execFileSync("docker", ["exec", container, "python", "-c",
    'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:18081/state").read().decode())'], {encoding: "utf8"}));
}
function active() {
  const pages = Object.values(fixture().pages);
  return pages.find(p => p.focused) || pages.at(-1);
}
async function until(predicate) {
  for (let n=0; n<50; n++) { if (predicate()) return; await new Promise(r => setTimeout(r, 100)); }
  throw new Error("synthetic_fixture_assertion_timed_out");
}
async function open(page, url) {
  page.on("pageerror", e => failures.push(e.message));
  await page.addInitScript(() => {
    const Original = window.WebSocket;
    window.trialSockets = [];
    window.WebSocket = class extends Original {
      constructor(...args) { super(...args); window.trialSockets.push(this); }
    };
  });
  const response = page.waitForResponse(r => new URL(r.url()).pathname === "/qualification/session");
  await page.goto(url);
  const session = await (await response).json();
  assert.ok(session.token);
  return session.token;
}
async function api(page, token, path, body) {
  const r = await page.request.fetch(new URL("/qualification/"+path, links.desktop).href, {
    method: body === undefined ? "GET" : "POST", headers: {Authorization: "Bearer "+token},
    data: body,
  });
  return {status: r.status(), value: await r.json()};
}
async function ready(page, interactive=false) {
  await page.waitForFunction(interactive => {
    const frame = document.querySelector("#stream");
    if (!frame || frame.contentWindow.location.href !== frame.src) return false;
    const v = frame.contentDocument?.querySelector("#videoStream");
    return v && v.readyState >= 2 && v.videoWidth > 0
      && (!interactive || frame.contentWindow.webrtcInput?.isInputAttached());
  }, interactive, {timeout: 20000});
}
async function remotePoint(page, id) {
  const state = active(), rect = state.rects[id];
  const x = state.offset.x+rect.x+rect.width/2, y = state.offset.y+rect.y+rect.height/2;
  return page.evaluate(({x,y}) => {
    const frame = document.getElementById("stream"), outer = frame.getBoundingClientRect();
    const video = frame.contentDocument.getElementById("videoStream"), r = video.getBoundingClientRect();
    const scale = Math.min(r.width/video.videoWidth, r.height/video.videoHeight);
    return {x: outer.x+r.x+(r.width-video.videoWidth*scale)/2+x*scale,
      y: outer.y+r.y+(r.height-video.videoHeight*scale)/2+y*scale};
  }, {x,y});
}
async function click(page, id) { const p = await remotePoint(page,id); await page.mouse.click(p.x,p.y); }
function core(page) { return page.frames().find(f=>f.parentFrame()); }

async function latency(page) {
  for(let sample=0;sample<20;sample++) {
    const state=active(), r=state.rects.bits;
    await page.evaluate(({expected,x,y})=>{
      const frame=document.getElementById('stream'), video=frame.contentDocument.getElementById('videoStream');
      const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;
      const ctx=canvas.getContext('2d',{willReadFrequently:true});
      let started=null, settled=false;
      frame.contentWindow.addEventListener('pointerdown',()=>{started=performance.now();},{once:true,capture:true});
      window.trialFeedback=new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>{settled=true;reject(new Error('rendered_feedback_timeout'));},5000);
        function presented(){
          if(settled)return;
          if(started!==null){
            ctx.drawImage(video,0,0);let value=0;
            for(let bit=0;bit<16;bit++){const p=ctx.getImageData(Math.round(x+bit*16+8),Math.round(y+8),1,1).data;if(p[0]>p[2])value|=1<<bit;}
            if(value===expected){settled=true;clearTimeout(timeout);resolve(performance.now()-started);return;}
          }
          video.requestVideoFrameCallback(presented);
        }
        video.requestVideoFrameCallback(presented);
      });
    },{expected:(state.sequence+1)&65535,x:state.offset.x+r.x,y:state.offset.y+r.y});
    await click(page,'feedback');
    feedbackSamples.push(await page.evaluate(()=>window.trialFeedback));
    await until(()=>active().sequence===state.sequence+1);
  }
}

try {
  const desktop = await context.newPage();
  const desktopToken = await open(desktop,links.desktop);
  diagnosticPage=desktop;diagnosticToken=desktopToken;
  await ready(desktop);
  await expect(desktop.locator("#connection")).toHaveText("Live browser");
  const marker = active().marker;
  const baseline=await api(desktop,desktopToken,"agent",{tool:"browser_snapshot",arguments:{}});
  assert.equal(baseline.status,200);
  assert.ok(JSON.stringify(baseline.value.result).includes("Browser intervention fixture"));
  check("desktop stream renders the native browser");
  await desktop.locator("#draft").fill("Draft survives browser intervention");
  await desktop.locator("#take").click();
  await expect(desktop.locator("#owner")).toHaveText("You have control");
  await ready(desktop,true);
  let state = (await api(desktop,desktopToken,"state")).value;
  const oldInputToken = state.stream_token;
  await click(desktop,"name");
  await desktop.keyboard.type("Desktop entry");
  await until(()=>active().name==="Desktop entry");
  await click(desktop,"notes");
  await desktop.keyboard.press("Meta+a");
  await desktop.keyboard.type("Desktop correction");
  await until(()=>active().notes==="Desktop correction");
  check("direct typing and Mac select-all traverse Selkies");

  await desktop.evaluate(()=>navigator.clipboard.writeText("Deliberate paste"));
  await desktop.keyboard.press("Meta+a");
  await desktop.keyboard.press("Meta+v");
  await until(()=>active().notes==="Deliberate paste");
  check("deliberate Mac paste reaches the remote field");
  await desktop.locator("#draft").click();
  await desktop.keyboard.type(" plus local text");
  assert.equal(active().notes,"Deliberate paste");
  await expect(desktop.locator("#draft")).toHaveValue("Draft survives browser intervention plus local text");
  check("chat focus does not inject remote keys");
  await latency(desktop);
  check("input-to-rendered feedback measured through the actual stream");

  const other = await context.newPage();
  const otherToken = await open(other,links.desktop);
  const race = await api(other,otherToken,"take",{request_id:crypto.randomUUID(),revision:state.revision});
  assert.equal(race.status,409);
  await other.close();
  check("a second desktop tab cannot steal the lease");

  const phoneContext = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:3});
  const phone = await phoneContext.newPage();
  const phoneToken = await open(phone,links.phone);
  await ready(phone);
  await expect(phone.locator("#take")).toBeHidden();
  await expect(phone.locator("#return")).toBeHidden();
  assert.equal((await api(phone,phoneToken,"take",{request_id:crypto.randomUUID(),revision:state.revision})).status,409);
  const before = active().sequence;
  const sent = await phone.evaluate(async token=>{
    const ws=new WebSocket((location.protocol === "https:" ? "wss://" : "ws://")+location.host+"/stream/api/websockets?token="+encodeURIComponent(token));
    return await new Promise((resolve,reject)=>{ws.onerror=()=>reject(new Error("phone_socket_failed"));ws.onmessage=event=>{
      if(typeof event.data==="string"&&event.data.startsWith("AUTH_SUCCESS,")){
        for(const message of ["kd,97","ku,97","m,100,400,1,0","m,100,400,0,0","r,777x777"])ws.send(message);
        setTimeout(()=>{ws.close();resolve(true);},200);
      }
    };});
  },phoneToken);
  assert.equal(sent,true);
  await new Promise(r=>setTimeout(r,400));
  assert.equal(active().sequence,before);
  await phone.locator("#zoom").click();
  await phone.screenshot({path:output+"/phone-zoom.png"});
  await phone.setViewportSize({width:844,height:390});
  await phone.locator("#fit").click();
  await ready(phone);
  check("phone capability rejects valid input and takeover; local zoom/orientation work");

  await desktop.bringToFront();
  await click(desktop,"password");
  await desktop.keyboard.type("RADHOUSE_TEST_SECRET_CANARY");
  await until(()=>active().sensitive);
  await desktop.locator("#return").click();
  await expect(desktop.locator("#notice")).toHaveText("Finish sign-in or clear the password and code fields before returning control.");
  await expect(desktop.locator("#owner")).toHaveText("You have control");
  await click(desktop,"sign-in");
  await until(()=>!active().sensitive);
  check("private sign-in blocks handback until sensitive fields clear");

  // Hold a real key on the human connection while requesting handback.
  await click(desktop,"notes");
  await desktop.keyboard.down("Shift");
  state=(await api(desktop,desktopToken,"state")).value;
  assert.equal((await api(desktop,desktopToken,"return",{revision:state.revision,lease_id:state.lease_id})).status,200);
  await expect(desktop.locator("#owner")).toHaveText("Agent has control");
  await desktop.keyboard.up("Shift");
  await ready(desktop);
  assert.equal(active().marker,marker);
  const observed = await api(desktop,desktopToken,"agent",{tool:"browser_snapshot",arguments:{}});
  assert.equal(observed.status,200);
  assert.ok(JSON.stringify(observed.value.result).includes("Deliberate paste"));
  assert.ok(!JSON.stringify(observed.value.result).includes("RADHOUSE_TEST_SECRET_CANARY"));
  check("handback releases held input and admits a fresh observation of the same browser");

  // A formerly authorized credential remains invalid after handback.
  const stale = await desktop.evaluate(async token=>{
    const socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://")+location.host+"/stream/api/websockets?token="+encodeURIComponent(token));
    return await new Promise(resolve=>{socket.onopen=()=>{socket.send("kd,97");socket.send("ku,97");};socket.onclose=()=>resolve(true);setTimeout(()=>{socket.close();resolve(false);},2000);});
  },oldInputToken);
  assert.equal(stale,true);
  assert.equal(active().notes,"Deliberate paste");
  check("old human stream cannot reconnect and inject after handback");
  await desktop.reload();
  await ready(desktop);
  assert.equal(active().marker,marker);
  assert.equal(active().notes,"Deliberate paste");
  check("viewer reload preserves the same browser without replay or automatic takeover");
  await desktop.screenshot({path:output+"/desktop-handover.png",fullPage:true});
  assert.deepEqual(failures,[]);
  await phoneContext.close();
  const sorted=[...feedbackSamples].sort((a,b)=>a-b);
  const feedback={samples:feedbackSamples.map(v=>Math.round(v)),p50_ms:Math.round(sorted[Math.ceil(sorted.length*.5)-1]),p95_ms:Math.round(sorted[Math.ceil(sorted.length*.95)-1]),max_ms:Math.round(sorted.at(-1)),clock:"one client browser performance clock",environment:process.env.RADHOUSE_SELKIES_ENVIRONMENT || "local Linux amd64 Docker fixture under emulation"};
  await writeFile(output+"/browser-result.json",JSON.stringify({passed:true,checks,feedback,real_phone_tested:false,physical_keyboard_tested:false},null,2)+"\n");
  console.log(JSON.stringify({passed:true,checks,feedback}));
} catch(error) {
  for(const [index,page] of context.pages().entries()) await page.screenshot({path:output+"/failure-"+index+".png",fullPage:true});
  if(diagnosticPage&&diagnosticToken)console.log(JSON.stringify({diagnostics:(await api(diagnosticPage,diagnosticToken,"diagnostics")).value,
    client:await core(diagnosticPage).evaluate(()=>({attached:window.webrtcInput?.isInputAttached(),socketStates:window.trialSockets.map(s=>s.readyState)}))}));
  throw error;
} finally { await browser.close(); }
