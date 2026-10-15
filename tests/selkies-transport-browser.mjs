// Actual pinned Selkies core; synthetic status only, no model or live app.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,webkit,expect}=await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const packageRoot=process.env.RADHOUSE_SELKIES_WEB;
if(!packageRoot)throw Error('Provide the qualified Selkies web asset directory');
const origin='http://127.0.0.1:61487',prefix='/chat/browser/stream/',results=[];
for(const [name,engine] of [['chromium',chromium],['webkit',webkit]]){
 const browser=await engine.launch({headless:true,...(name==='chromium'?{channel:'chrome'}:{})});
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 await context.addInitScript(()=>{
  const key=(location.origin+location.pathname).replace(/[^a-zA-Z0-9._-]/g,'_')+'_stream_mode';
  localStorage.setItem(key,'webrtc');sessionStorage.setItem('selkies_mode_flip','1');
 });
 await context.route(origin+'/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith(prefix+'api/'))return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({mode:'websockets',authenticated:true})});
  const file=path.slice(prefix.length);
  if(file==='index.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><script src="./transport.js"></script><script type="module" src="./selkies-core.js"></script></head><body><div id="app"></div></body></html>'});
  if(file==='transport.js')return route.fulfill({contentType:'text/javascript',body:await readFile(new URL('../runtime/selkies/web/transport.js',import.meta.url))});
  if(file==='selkies-core.js')return route.fulfill({contentType:'text/javascript',body:await readFile(packageRoot+'/selkies-core.js')});
  return route.fulfill({status:404});
 });
 const page=await context.newPage();const modes=[];
 page.on('console',message=>{if(message.text().startsWith('Streaming mode determined to be:'))modes.push(message.text());});
 try{
  await page.goto(origin+prefix+'index.html#token='+'x'.repeat(43));
  await expect.poll(()=>modes).toContain('Streaming mode determined to be: websockets');
  expect(await page.locator('#stream').count()).toBe(0);
  expect(await page.evaluate(()=>window.__SELKIES_STREAMING_MODE__)).toBe('websockets');
  await page.reload();
  await expect.poll(()=>modes.length).toBeGreaterThanOrEqual(2);
  expect(modes.every(m=>m==='Streaming mode determined to be: websockets')).toBe(true);
  results.push({engine:name,persisted_webrtc_ignored:true,reload_keeps_fixed_transport:true,actual_pinned_core:true});
 }finally{await browser.close();}
}
console.log(JSON.stringify({passed:results.length,results}));
