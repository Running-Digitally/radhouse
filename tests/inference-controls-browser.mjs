// Real Chromium + loopback HTTP fixtures; no provider or production access.
import {createServer} from "node:http";
import {readFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import assert from "node:assert/strict";
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href : new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
const browser=await chromium.launch({headless:true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
const root=new URL("../src/radhouse/chat/static/",import.meta.url);
const unknown={state:"unknown",choices:[],can_disable:false,can_enable:false};
const known={state:"supported",choices:["low","high"],can_disable:true,can_enable:true};
const row=(id,thinking=unknown)=>({id,label:id,available:true,reason:null,thinking});
let payload={schema:"radhouse.inference.v1",state:"available",checked_at:"2026-10-08T20:00:00+00:00",engine:{id:"fixture-engine",label:"Fixture engine"},current_model:"alpha",models:[row("alpha",known),row("beta")]};
let unavailable=false; const calls=[],errors=[];
const fixture=await readFile(new URL("inference-controls.js",root));
const style=await readFile(new URL("inference-controls.css",root));
const html='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/inference-controls.css"><main><h1>Fixture conversation</h1><div id="inference"></div><textarea aria-label="Message"></textarea></main><script src="/inference-controls.js"></script><script src="/fixture.js"></script>';
const setup='window.controls=new RadhouseInference({container:document.getElementById("inference"),request:async(path,_body,_auth,signal)=>{const response=await fetch(path,{signal});if(!response.ok){const error=new Error("unavailable");error.status=response.status;throw error;}return response.json();}});void controls.load();';
const server=createServer((request,response)=>{
  const url=new URL(request.url,"http://127.0.0.1");
  if(url.pathname==="/chat/inference"){calls.push(url.pathname+url.search);response.writeHead(unavailable?503:200,{"Content-Type":"application/json","Cache-Control":"no-store"});response.end(JSON.stringify(unavailable?{error:"fixture_unavailable"}:payload));return;}
  const files={"/":[html,"text/html"],"/inference-controls.js":[fixture,"text/javascript"],"/inference-controls.css":[style,"text/css"],"/fixture.js":[setup,"text/javascript"]};
  const file=files[url.pathname]; response.writeHead(file?200:404,{"Content-Type":file?.[1]||"text/plain","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'"});response.end(file?.[0]||"Missing");
});
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
const origin="http://127.0.0.1:"+server.address().port;
try{
  const context=await browser.newContext({viewport:{width:1100,height:800}});
  const page=await context.newPage();page.on("pageerror",error=>errors.push(error.message));
  await page.goto(origin);const model=page.getByRole("combobox",{name:"Model",exact:true}),thinking=page.getByRole("combobox",{name:"Thinking",exact:true});
  await expect(model.locator("option")).toHaveCount(3);assert.equal(calls.length,1);
  await expect(thinking).toBeVisible();await thinking.selectOption("off");
  assert.deepEqual(await page.evaluate(()=>controls.selection()),{model:null,thinking:"off"});
  await thinking.selectOption("on");assert.equal((await page.evaluate(()=>controls.selection())).thinking,"on");
  assert.equal(await thinking.locator('option[value="max"]').count(),0);
  await model.selectOption("beta");await expect(thinking).toBeHidden();
  await expect(page.getByText("Thinking settings aren’t available for this model.")).toBeVisible();
  assert.deepEqual(await page.evaluate(()=>controls.selection()),{model:"beta",thinking:"default"});
  await model.selectOption("alpha");await thinking.selectOption("high");
  payload={...payload,models:[row("beta")]};
  await page.getByRole("button",{name:"Refresh models"}).click();
  await expect(model.locator('option[value="alpha"]')).toHaveAttribute("disabled", "");
  assert.deepEqual(await page.evaluate(()=>controls.selection()),{model:"alpha",thinking:"high"});
  assert.equal(calls.at(-1),"/chat/inference?refresh=true");
  await model.selectOption("");assert.equal(await page.evaluate(()=>controls.selection()),null);
  payload={...payload,current_model:"beta",models:[row("beta")]};
  await page.getByRole("button",{name:"Refresh models"}).click();await expect(model.locator("option")).toHaveCount(2);
  await model.selectOption("beta");await model.focus();await page.keyboard.press("Tab");
  await expect(page.getByRole("button",{name:"Refresh models"})).toBeFocused();
  unavailable=true;await page.getByRole("button",{name:"Refresh models"}).click();
  await expect(page.getByText("Model choices couldn’t be checked. You can use Default.")).toBeVisible();
  await expect(model).toBeEnabled();await expect(model.locator('option[value="beta"]')).toHaveAttribute("disabled", "");
  await model.selectOption("");assert.equal(await page.evaluate(()=>controls.selection()),null);
  await page.evaluate(()=>controls.setDisabled(true));await expect(model).toBeDisabled();await expect(page.getByRole("button",{name:"Refresh models"})).toBeDisabled();
  await page.evaluate(()=>controls.setDisabled(false));
  unavailable=false;payload={...payload,models:[row("beta"),row("bool",{state:"supported",choices:[],can_disable:true,can_enable:true})]};
  await page.getByRole("button",{name:"Refresh models"}).click();await expect(model.locator("option")).toHaveCount(3);
  await model.selectOption("bool");await expect(thinking.locator("option")).toHaveCount(3);
  await expect(thinking.locator('option[value="low"]')).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});await expect(model).toBeInViewport();await expect(thinking).toBeInViewport();await expect(page.getByRole("button",{name:"Refresh models"})).toBeInViewport();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.evaluate(()=>controls.clear());assert.equal(await page.evaluate(()=>controls.selection()),null);await expect(thinking).toBeHidden();
  assert.deepEqual(errors,[]);await context.close();
  console.log("PASS real Chromium inference controls: dynamic rows, unsupported/unknown controls, boolean toggle, explicit refresh, retained unavailable choice, Default recovery, keyboard and mobile.");
}finally{
  await browser.close();await new Promise(resolve=>server.close(resolve));
}
