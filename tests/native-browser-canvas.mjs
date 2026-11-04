// Synthetic browser service: exercise the actual canvas in both mobile engines.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {cover, closeBrowser} from './browser-coverage.mjs';
const moduleURL = process.env.RADHOUSE_PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href
  : new URL('../web/node_modules/@playwright/test/index.mjs',import.meta.url).href;
const {chromium,webkit,expect} = await import(moduleURL);
const root = new URL('../src/radhouse/chat/static/',import.meta.url);
const origin = 'https://canvas.example.test', tab = '11111111-2222-4333-8444-555555555555';
const results = [];
// The merged-main coverage gate owns Chromium. The separate simulator gate
// supplies WebKit explicitly; never silently skip a requested engine.
const engines = process.env.RADHOUSE_CANVAS_WEBKIT === '1'
  ? [['chromium',chromium],['webkit',webkit]] : [['chromium',chromium]];
for (const [name,engine] of engines) {
  const browser = await engine.launch({headless:true});
  const context = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  let mode='agent', active=true, revision=1, failure=false, readFailure=false, expired=false, mutations=[], loads=0;
  const state = () => ({state:'live',generation:'generation-one',title:'Example page',url:'https://example.org/',
    agent_active:active,can_return:true,stream:{path:'/chat/browser/stream/index.html',token:mode.repeat(43).slice(0,43)},
    control:{mode,revision,can_take:mode==='agent',...(mode==='human'?{lease_id:'lease-one',lease_expires_at:Date.now()/1000+60,observation_mode:'private'}:{})}});
  await context.addInitScript(() => {window.fixtureHidden=true;Object.defineProperty(document,'hidden',{get:()=>window.fixtureHidden});window.nativeStates=[];window.ReactNativeWebView={postMessage(raw){window.nativeStates.push(JSON.parse(raw));}};});
  await context.route(origin+'/**',async route => {
    const request=route.request(),path=new URL(request.url()).pathname;
    const json=(value,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
    if(path==='/auth/session')return json({csrf_token:'s'.repeat(43),features:{browser_streaming:true}});
    if(path==='/chat/browser/preferences')return json({search_engine:'duckduckgo'});
    if(path==='/chat/browser')return json(state(),expired?401:readFailure?503:200);
    if(request.method()==='POST') {
      expect(request.headers()['x-radhouse-csrf']).toBe('s'.repeat(43));
      expect(request.headers()['x-radhouse-browser-tab']).toBe(tab);
      mutations.push({path,body:request.postDataJSON()});
      if(failure)return json({error:'unconfirmed'},503);
      if(path.endsWith('/take')){mode='human';active=false;revision++;}
      if(path.endsWith('/visibility'))revision++;
      return json(state());
    }
    if(path==='/chat/browser/stream/index.html') {
      loads++;
      return route.fulfill({contentType:'text/html',body:`<html><body style="margin:0;background:#e4ede2"><h1>Example page</h1><script>
        window.inputs=[];window.radhouseInput={hide(){},show(){return true},press(key){inputs.push(key);return true},navigate(url){inputs.push(url);return true}};
        parent.postMessage({type:'framePresented'},location.origin);
        parent.postMessage({type:'mobileInputStatus',ready:true},location.origin);
        </script></body></html>`});
    }
    const file=path==='/mobile/browser'?'mobile-browser.html':path.slice(1);
    if(!['mobile-browser.html','mobile-browser.js','mobile-browser.css'].includes(file))return route.fulfill({status:404});
    return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:await readFile(new URL(file,root))});
  });
  const page=await context.newPage(), errors=[];
  if (name === 'chromium') await cover(page);
  page.on('pageerror',e=>errors.push(e.message));
  const command = value => page.evaluate(v=>window.RadhouseMobileBrowser.command(v),value);
  const latest = () => page.evaluate(()=>window.nativeStates.at(-1));
  await page.goto(origin+'/mobile/browser?tab='+tab);
  await expect.poll(async()=>(await latest())?.active).toBe(true);
  await expect(page.locator('iframe')).toHaveCount(0);
  await page.evaluate(()=>{window.fixtureHidden=false;document.dispatchEvent(new Event('visibilitychange'));});
  await expect(page.locator('iframe')).toHaveCount(1);
  await expect.poll(async()=>(await latest()).playback).toBe('live');
  expect(await page.locator('iframe').evaluate(f=>f.inert)).toBe(true);
  const readySource=await page.locator('iframe').getAttribute('src');
  active=false;
  await command({action:'refresh'});
  expect((await latest()).active).toBe(false);
  expect((await latest()).previewAvailable).toBe(true);
  expect(await page.locator('iframe').getAttribute('src')).toBe(readySource);
  await command({action:'dismissPreview'});
  expect((await latest()).previewAvailable).toBe(false);
  await expect(page.locator('iframe')).toHaveCount(0);
  await command({action:'refresh'});
  expect((await latest()).previewAvailable).toBe(false);
  active=true;
  await command({action:'refresh'});
  await expect(page.locator('iframe')).toHaveCount(1);
  expect((await latest()).previewAvailable).toBe(true);
  await command({action:'take'});await command({action:'address',value:'example.org'});
  expect(mutations).toHaveLength(0);
  const initial=await page.locator('iframe').getAttribute('src');
  await command({action:'present',mode:'full'});
  expect(await page.locator('iframe').getAttribute('src')).toBe(initial);
  expect(mutations).toHaveLength(0);
  await command({action:'zoom',enabled:true});
  await expect(page.locator('#canvas')).toHaveClass(/zoom/);
  await command({action:'take'});
  await expect.poll(async()=>(await latest()).human).toBe(true);
  await expect.poll(async()=>(await latest()).inputReady).toBe(false);
  expect(await page.locator('iframe').evaluate(f=>f.inert)).toBe(true);
  await command({action:'address',value:'example.org'});
  await expect.poll(()=>page.locator('iframe').evaluate(f=>f.contentWindow.inputs)).toEqual([]);
  await command({action:'zoom',enabled:false});
  await expect.poll(async()=>(await latest()).inputReady).toBe(true);
  expect(await page.locator('iframe').evaluate(f=>f.inert)).toBe(false);
  expect(mutations[0].body).toMatchObject({generation:'generation-one',revision:1,lease_id:null});
  await command({action:'address',value:'agent browser research'});
  await expect.poll(()=>page.locator('iframe').evaluate(f=>f.contentWindow.inputs)).toEqual(['https://duckduckgo.com/?q=agent+browser+research']);
  await command({action:'hideKeyboard'});
  expect((await latest()).notice).toBe('');
  await command({action:'present',mode:'preview'});
  await expect(page.locator('iframe')).toHaveCount(0);
  expect((await latest()).title).toBe('');expect((await latest()).url).toBe('');
  await command({action:'present',mode:'full'});
  await expect(page.locator('iframe')).toHaveCount(1);
  failure=true;
  await command({action:'visibility',mode:'observe'});
  expect((await latest()).uncertain).toBe(true);
  const before=mutations.length;
  await command({action:'visibility',mode:'observe'});
  await command({action:'reconnect'});
  expect(await page.locator('iframe').evaluate(f=>f.inert)).toBe(true);
  expect(mutations).toHaveLength(before);
  readFailure=true;
  await command({action:'refresh'});
  expect((await latest()).uncertain).toBe(true);
  readFailure=false;failure=false;
  await command({action:'refresh'});
  expect((await latest()).uncertain).toBe(false);
  expect(mutations).toHaveLength(before);
  expired=true;
  await command({action:'refresh'});
  await expect(page.locator('iframe')).toHaveCount(0);
  expect(await page.evaluate(()=>nativeStates.some(s=>s.event==='expired'))).toBe(true);
  const messages=await page.evaluate(()=>nativeStates);
  expect(messages.some(v=>'stream' in v||'lease_id' in v||'csrf_token' in v)).toBe(false);
  expect(errors).toEqual([]);
  results.push({engine:name,loads,checks:'live view-only preview, expand without takeover, privacy hiding, saved search engine, no mutation replay, expiry'});
  await closeBrowser(browser);
}
console.log(JSON.stringify(results));
