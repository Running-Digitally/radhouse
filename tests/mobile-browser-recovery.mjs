// Synthetic authenticated workspace in Chromium and WebKit. Simulate an explicit
// autoplay-policy rejection; verify a trusted local tap never injects remote input.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,webkit,expect}=await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const root=new URL('../src/radhouse/chat/static/',import.meta.url),runtime=new URL('../runtime/selkies/web/',import.meta.url),origin='http://127.0.0.1:61486';
const results=[];
for(const [name,engine] of [['chromium',chromium],['webkit',webkit]]){
 const browser=await engine.launch({headless:true,...(name==='chromium'?{channel:'chrome'}:{})});
 const c=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 let foreign=true,rev=3,moves=[],errors=[];
 const state=()=>({state:'live',generation:'generation-1',url:'https://example.org/',title:'Example',viewport:{width:1280,height:900},agent_active:false,
  stream:{path:'/chat/browser/stream/index.html',token:(foreign?'v':'h').repeat(43)},control:{mode:'human',revision:rev,can_take:false,...(!foreign?{lease_id:'phone-lease',lease_expires_at:Date.now()/1000+60,next_sequence:1,observation_mode:'private',observation_epoch:0}:{})},page_context:{current:{url:'https://example.org/',title:'Example'},previous:null},can_return:true,vault_enabled:false});
 await c.addInitScript(()=>{
  if(window===window.top){window.trustedPlaybackTaps=0;document.addEventListener('click',event=>{if(event.isTrusted&&event.target.closest?.('.browser-playback-start'))window.trustedPlaybackTaps++;},true);}
 });
 await c.route(origin+'/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname,json=v=>route.fulfill({contentType:'application/json',body:JSON.stringify(v)});
  if(path==='/auth/session')return json({username:'alice',csrf_token:'synthetic',features:{browser:true,browser_control:true,browser_streaming:true,documents:true}});
  if(path==='/chat/history'||path==='/chat/reply')return json({turns:[],older_before:null});
  if(path==='/chat/browser/preferences')return json({revision:0,search_engine:'google',history:[]});
  if(path==='/chat/library')return json({files:[],next_cursor:null});
  if(path==='/chat/browser')return json(state());
  if(path==='/chat/browser/control/take'){
   const body=req.postDataJSON();expect(body.move_here).toBe(true);moves.push(body);foreign=false;rev++;return json(state());
  }
  if(path==='/chat/browser/control/heartbeat')return json(state());
  if(path==='/chat/browser/stream/index.html')return route.fulfill({contentType:'text/html',body:`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><script>
   const baseline=parent.trustedPlaybackTaps;let playing=false;window.remoteInput=0;
   document.addEventListener('pointerdown',()=>remoteInput++);
   Object.defineProperty(HTMLMediaElement.prototype,'readyState',{get(){return 2}});
   Object.defineProperty(HTMLMediaElement.prototype,'paused',{get(){return !playing}});
   Object.defineProperty(HTMLVideoElement.prototype,'requestVideoFrameCallback',{value:undefined});
   HTMLMediaElement.prototype.play=function(){
    if(parent.trustedPlaybackTaps<=baseline)return Promise.reject(new DOMException('Synthetic policy rejection','NotAllowedError'));
    playing=true;this.dispatchEvent(new Event('playing'));return Promise.resolve();
   };
   </script><video id="videoStream"></video><script type="module" src="/chat/browser/stream/bridge.js"></script>`});
  if(path==='/chat/browser/stream/mobile-input.js')return route.fulfill({contentType:'text/javascript',body:`export function installMobileInput(notify){window.radhouseInput={hide(){},show(){return true},press(){return true}};notify({ready:true,touch:true,hardware:false,focused:false});}`});
  if(path==='/chat/browser/stream/bridge.js')return route.fulfill({contentType:'text/javascript',body:await readFile(new URL('stream-bridge.js',runtime))});
  let file=path.startsWith('/workspace-assets/')?path.slice(18):path.slice(1);
  if(path==='/'||path==='/browser')file='index.html';
  if(!/^[\w.-]+$/.test(file))return route.fulfill({status:404});
  try{return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:await readFile(new URL(file,root))});}catch{return route.fulfill({status:404});}
 });
 const page=await c.newPage();page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(origin+'/browser');
  await expect(page.getByRole('button',{name:'Move control here',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Close browser',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Tap to view browser',exact:true})).toBeVisible();
  await expect(page.locator('.browser-connection')).toHaveText('Tap to view');
  await page.getByRole('button',{name:'Tap to view browser',exact:true}).click();
  await expect(page.locator('.browser-connection')).toHaveText('Live');
  expect(await page.frameLocator('.browser-stream-frame').locator('video').evaluate(e=>({muted:e.muted,inline:e.hasAttribute('playsinline'),input:window.remoteInput}))).toEqual({muted:true,inline:true,input:0});
  expect(moves.length).toBe(0);
  await page.getByRole('button',{name:'Move control here',exact:true}).click();
  await expect(page.locator('.browser-privacy').getByRole('button',{name:'Private',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.getByRole('button',{name:'Tap to view browser',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Tap to view browser',exact:true}).click();
  await expect(page.locator('.browser-connection')).toHaveText('Live');
  await expect(page.getByRole('button',{name:'Keys',exact:true})).toBeEnabled();
  expect(moves.length).toBe(1);expect(errors).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  results.push({engine:name,policy_rejection_visible:true,trusted_tap_resumes:true,play_does_not_take_control:true,no_remote_input_from_play:true,explicit_move_private:true,new_role_requires_fresh_playback:true});
 }finally{await browser.close();}
}
console.log(JSON.stringify({passed:results.length,results}));
