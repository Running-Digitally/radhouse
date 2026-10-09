// Real pinned xterm in Chromium, with synthetic owner HTTP and no host/profile access.
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE?pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href:new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const browser=await chromium.launch({headless:true,
  ...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
const origin="http://127.0.0.1:61493",staticRoot=new URL("../src/radhouse/chat/static/",import.meta.url);
const id="11111111-1111-4111-8111-111111111111",generation="22222222-2222-4222-8222-222222222222";
let state="closed",epoch=1,sequence=0,calls=[],bytes=Buffer.alloc(0),failInput=false,command="",holdResize=false,heldResize=null;
const status=()=>({state,terminal_id:state==="closed"?null:id,generation:state==="closed"?null:generation,
  attach_epoch:state==="closed"?0:epoch,next_cursor:bytes.length,last_sequence:sequence,last_outcome:sequence?"written":"none"});
const context=await browser.newContext({viewport:{width:1100,height:900}}),page=await context.newPage(),errors=[];
page.on("pageerror",error=>errors.push(error.message));
await context.route(origin+"/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith("/chat/terminal/")) {
    const operation=path.split("/").at(-1),body=route.request().postDataJSON();calls.push({operation,body});
    if(operation==="open") { if(state==="open")epoch++;else {state="open";bytes=Buffer.from("READY_é\r\n$ ");} }
    if(operation==="input") {
      if(body.attach_epoch!==epoch||body.sequence!==sequence+1)throw new Error("Stale/out-of-order terminal input");
      sequence=body.sequence;
      if(failInput) {failInput=false;return route.abort("failed");}
      const input=Buffer.from(body.data_b64,"base64").toString();command+=input;
      if(command.endsWith("\r")){bytes=Buffer.concat([bytes,Buffer.from(command+"\nHELLO_RESULT\r\n$ ")]);command="";}
    }
    if(operation==="close") {state="closed";bytes=Buffer.alloc(0);}
    if(operation==="resize" && holdResize) {
      holdResize=false; await new Promise(resolve=>{heldResize=resolve;});
      return route.fulfill({status:401,contentType:"application/json",body:JSON.stringify({error:"authentication_required"})});
    }
    let value=status();
    if(operation==="output") {
      if(body.cursor===bytes.length)await new Promise(resolve=>setTimeout(resolve,100));
      value={...value,data_b64:bytes.subarray(body.cursor).toString("base64"),next_cursor:bytes.length,truncated:false};
    }
    if(operation==="context-scrub") value={kind:"terminal_excerpt",label:"Agent VM terminal",
      ...Object.fromEntries(["terminal_id","generation","captured_at","source","text","truncated"].map(key=>[key,body[key]])),text:body.text.replaceAll("synthetic-secret","[REDACTED]")};
    return route.fulfill({contentType:"application/json",body:JSON.stringify(value)});
  }
  if(path==="/bootstrap.js")return route.fulfill({contentType:"text/javascript",body:`
    window.authRequired=0;
    window.view=new window.OwnerTerminalView(document.getElementById('terminal'),{tab:'33333333-3333-4333-8333-333333333333',onAuthRequired:()=>{window.authRequired++;},
    request:async(path,body,method,signal)=>{const response=await fetch(path,{method,body:JSON.stringify(body),headers:{'Content-Type':'application/json'},signal});
    const value=await response.json();if(!response.ok)throw Object.assign(new Error(value.error),{status:response.status});return value;}});
    void view.show();`});
  if(path!=="/")return route.fulfill({contentType:path.endsWith(".css")?"text/css":"text/javascript",body:await readFile(new URL(path.slice(1),staticRoot))});
  return route.fulfill({contentType:"text/html; charset=utf-8",body:'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/vendor/xterm/xterm.css"><link rel="stylesheet" href="/owner-terminal.css"><script src="/vendor/xterm/xterm.js" defer></script><script src="/vendor/xterm/addon-fit.js" defer></script><script src="/owner-terminal.js" defer></script><script src="/bootstrap.js" defer></script></head><body><main style="max-width:950px;margin:auto;padding:20px"><div id="terminal"></div></main></body></html>'});
});
try {
  await page.goto(origin+"/");await expect(page.getByRole("button",{name:"Open terminal",exact:true})).toBeVisible();
  if(calls.some(call=>call.operation==="open"))throw new Error("Page entry spawned a shell");
  if(await page.evaluate(()=>view.prepareContext())!==null)throw new Error("Context was enabled by default");
  await page.getByRole("button",{name:"Open terminal",exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>view.term?.buffer.active.getLine(0)?.translateToString(true))).toBe("READY_é");
  await page.locator(".xterm-helper-textarea").pressSequentially("echo hello");await page.keyboard.press("Enter");
  await expect.poll(()=>page.evaluate(()=>view.term.buffer.active.getLine(2)?.translateToString(true))).toBe("HELLO_RESULT");
  const opened=calls.filter(call=>call.operation==="open").length;
  await page.evaluate(()=>view.hide());await page.evaluate(()=>view.show());
  if(calls.filter(call=>call.operation==="open").length!==opened)throw new Error("Hide/show respawned shell");
  await page.reload();await expect.poll(()=>page.evaluate(()=>view.available)).toBe(true);
  if(calls.filter(call=>call.operation==="open").length!==opened)throw new Error("Reload spawned shell");
  await page.evaluate(()=>{
    Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(150);const hiddenPolls=calls.filter(call=>call.operation==="output").length;
  await page.waitForTimeout(150);
  if(calls.filter(call=>call.operation==="output").length!==hiddenPolls)throw new Error("Hidden page kept renewing terminal presence");
  await page.evaluate(()=>{
    Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(()=>calls.filter(call=>call.operation==="output").length).toBeGreaterThan(hiddenPolls);
  await page.evaluate(async()=>{await new Promise(resolve=>view.term.write("\r\n"+Array.from({length:25},(_,i)=>'line '+i).join('\r\n')+'\r\nsynthetic-secret',resolve));view.contextEnabled=true;});
  const excerpt=await page.evaluate(()=>view.prepareContext());
  if(excerpt.source!=="recent"||excerpt.text.split("\n").length>20||!excerpt.text.includes("[REDACTED]")||excerpt.text.includes("synthetic-secret"))throw new Error("Context was not bounded/scrubbed");
  // Rendering wraps must not manufacture a newline inside a known secret.
  await page.evaluate(async()=>{
    view.term.reset();view.term.resize(12,28);
    await new Promise(resolve=>view.term.write('prefix\r\nsynthetic-secret\r\nend',resolve));
  });
  const wrapped=await page.evaluate(()=>view.prepareContext());
  if(!wrapped.text.includes("[REDACTED]")||wrapped.text.includes("synthetic-\nsecret"))throw new Error("Wrapped context defeated the secret mask");
  await page.evaluate(()=>view.term.select(0,0,7));
  const selection=await page.evaluate(()=>view.prepareContext());
  if(selection.source!=="selection")throw new Error("Selection context was ignored");
  await page.evaluate(()=>{
    view.term.getSelection=()=>"x".repeat(8120)+"synthetic-secret"+"y".repeat(100)+"\nSAFE_LINE";
  });
  const clipped=await page.evaluate(()=>view.prepareContext());
  if(clipped.text!=="SAFE_LINE"||!clipped.truncated)throw new Error("Byte clipping retained a secret fragment");
  holdResize=true;await page.evaluate(()=>{void view._resize();});
  await expect.poll(()=>heldResize!==null).toBe(true);
  await page.evaluate(()=>view.dispose());await page.evaluate(()=>view.show());
  await page.getByRole("button",{name:"Reconnect terminal",exact:true}).click();
  heldResize();await page.waitForTimeout(150);
  if(await page.evaluate(()=>authRequired!==0||!view.term||view.inputUnconfirmed))throw new Error("Stale resize 401 invalidated the replacement terminal/auth session");
  const before=calls.filter(call=>call.operation==="input").length;failInput=true;
  await page.locator(".xterm-helper-textarea").focus();await page.keyboard.type("danger");
  await expect(page.locator(".owner-terminal-status")).toContainText("Input was not confirmed");
  await page.waitForTimeout(150);
  if(calls.filter(call=>call.operation==="input").length!==before+1)throw new Error("Uncertain input was retried or queued keys applied");
  await page.getByRole("button",{name:"Reconnect terminal",exact:true}).click();
  await page.getByRole("button",{name:"Close terminal",exact:true}).click();
  await expect(page.getByRole("button",{name:"Open terminal",exact:true})).toBeVisible();
  await page.evaluate(()=>view.dispose());
  if(await page.evaluate(()=>view.term!==null||view.contextEnabled||view.available))throw new Error("Sign-out retained private terminal state");
  if(errors.length)throw new Error(errors.join("; "));
  console.log("Owner terminal: lazy open, real xterm Unicode/input, Hide/reload preservation, bounded/scrubbed context, uncertain ACK fencing, Close/dispose passed.");
} finally {await context.close();await browser.close();}
