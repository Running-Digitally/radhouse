import {readFile,mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const root=new URL('../src/radhouse/chat/static/',import.meta.url),origin='http://127.0.0.1:61484';
const browser=await chromium.launch({headless:true,channel:'chrome'});
let mode='agent',visibility='private',rev=3,agentActive=true,requestCount=0;
const c=await browser.newContext({viewport:{width:1360,height:900}}),errors=[];
await c.route(origin+'/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;
 const json=v=>route.fulfill({contentType:'application/json',body:JSON.stringify(v)});
 const state=()=>({state:'live',generation:'generation-1',url:'https://example.org/',title:'Example',viewport:{width:1280,height:900},agent_active:agentActive,
  stream:{path:'/chat/browser/stream/index.html',token:(mode==='human'?'h':'v').repeat(43)},control:{mode,revision:rev,can_take:mode==='agent',...(mode==='human'?{lease_id:'lease-1',lease_expires_at:Date.now()/1000+60,next_sequence:1,observation_mode:visibility,observation_epoch:rev}:{})},page_context:{current:{url:'https://example.org/',title:'Example'},previous:null},can_return:true,vault_enabled:false});
 if(path==='/auth/session')return json({username:'alice',csrf_token:'synthetic',features:{browser:true,browser_control:true,browser_streaming:true,documents:true}});
 if(path==='/chat/history'||path==='/chat/reply')return json({turns:[],older_before:null});
 if(path==='/chat/browser/preferences')return json({revision:0,search_engine:'google',history:[]});
 if(path==='/chat/library')return json({files:[],next_cursor:null});
 if(path==='/chat/browser'){requestCount++;return json(state());}
 if(path==='/chat/browser/control/take'){mode='human';visibility='private';rev++;return json(state());}
 if(path==='/chat/browser/control/visibility'){visibility=req.postDataJSON().mode;rev++;return json(state());}
 if(path==='/chat/browser/control/heartbeat')return json(state());
 if(path==='/chat/browser/stream/index.html')return route.fulfill({contentType:'text/html',body:`<body style="background:#eef;color:#223">Synthetic live browser<script>window.radhouseInput={hide(){},show(){return true},press(){return true}};parent.postMessage({type:'mobileInputStatus',ready:true,touch:true,hardware:false,focused:false},location.origin);parent.postMessage({type:'framePresented'},location.origin);</script>`});
 let file=path.startsWith('/workspace-assets/')?path.slice(18):path.slice(1);
 if(path==='/'||path==='/browser')file='index.html';
 if(!/^[\w.-]+$/.test(file))return route.fulfill({status:404});
 try{return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html',body:await readFile(new URL(file,root))});}catch{return route.fulfill({status:404});}
});
const page=await c.newPage();page.on('pageerror',e=>errors.push(e.message));
const results=[];
try{
 await page.goto(origin);await expect(page.locator('main')).toHaveClass(/has-browser-preview/);
 await page.locator('#message').fill('Keep this draft while switching');
 const frame=await page.locator('.browser-stream-frame').elementHandle();
 await page.locator('#browser-preview-open').click();
 await expect(page.locator('main')).toHaveClass(/workspace-browser/);
 expect(await page.locator('.browser-stream-frame').evaluate((e,old)=>e===old,frame)).toBe(true);
 const viewConnection=new URL(await page.locator('.browser-stream-frame').getAttribute('src'),origin).searchParams.get('connection');
 await page.getByRole('button',{name:'Take control privately',exact:true}).click();
 await expect(page.locator('.browser-privacy')).toBeVisible();
 const controlConnection=new URL(await page.locator('.browser-stream-frame').getAttribute('src'),origin).searchParams.get('connection');
 expect(controlConnection).not.toBe(viewConnection);
 await expect(page.locator('.browser-privacy')).toBeVisible();
 await expect(page.getByRole('button',{name:'Private',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.locator('.browser-privacy').getByRole('button',{name:'Let agent observe',exact:true}).click();
 await expect(page.locator('.browser-privacy-text, .browser-privacy [role=status]')).toContainText('Agent can read');
 await page.evaluate(()=>browserView.update({...lastBrowserStatus,control:{...lastBrowserStatus.control,revision:lastBrowserStatus.control.revision-1,observation_mode:'private'}}));
 await expect(page.locator('.browser-privacy').getByRole('button',{name:'Let agent observe',exact:true})).toHaveAttribute('aria-pressed','true');
 expect(new URL(await page.locator('.browser-stream-frame').getAttribute('src'),origin).searchParams.get('connection')).toBe(controlConnection);
 await page.getByRole('button',{name:'Private',exact:true}).click();
 await expect(page.getByRole('button',{name:'Private',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.locator('#browser-minimize').click();
 await expect(page.locator('#message')).toHaveValue('Keep this draft while switching');
 expect(await page.locator('.browser-stream-frame').evaluate((e,old)=>e===old,frame)).toBe(true);
 results.push('desktop preview expansion, same stream, privacy switch, minimize and draft retention');
 await page.locator('#browser-preview-open').click();
 for(const [width,height]of [[320,640],[375,667],[390,844],[430,932],[844,390],[390,360],[320,360]]){
  await page.setViewportSize({width,height});
  expect(await page.locator('header').evaluate(e=>e.getBoundingClientRect().height)).toBeLessThanOrEqual(72);
  await page.getByRole('button',{name:'Keys',exact:true}).click();
  const bounds=await page.locator('.browser-stream-keys button').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,height:r.height}}));
  if(bounds.some(b=>b.left<0||b.right>width+1||b.width<43||b.height<43))throw Error('Keys clipped at '+width+'x'+height+':'+JSON.stringify(bounds));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.getByRole('button',{name:'Keys',exact:true}).click();
  await page.locator('#browser-chat-toggle').click();
  await expect(page.locator('#message')).toBeVisible();
  await expect(page.locator('#message')).toHaveValue('Keep this draft while switching');
  await page.locator('#browser-chat-toggle').click();
  results.push('responsive keys/chat drawer '+width+'x'+height);
 }
 expect(errors).toEqual([]);
 console.log(JSON.stringify({passed:results.length,checks:results,status_requests:requestCount}));
}finally{await browser.close();}
