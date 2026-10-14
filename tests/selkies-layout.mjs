// The actual viewer files against a synthetic transport; no live browser input.
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium, expect}=await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const web=new URL('../runtime/selkies/web/',import.meta.url);
const output=process.env.RADHOUSE_SELKIES_OUTPUT;
if(output)await mkdir(output,{recursive:true,mode:0o700});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({isMobile:true,hasTouch:true,viewport:{width:390,height:844}});
const page=await context.newPage();
const state={controlling:true,viewing_only:false,can_take:false,mode:'human',public_web:true,stream_token:'synthetic-stream'};
await page.route('http://localhost:18123/**',async route=>{
 const path=new URL(route.request().url()).pathname;
 if(path.startsWith('/qualification/assets/')) {
  const name=path.split('/').at(-1);assert(['styles.css','viewer.js'].includes(name));
  return route.fulfill({body:await readFile(new URL(name,web)),contentType:name.endsWith('.css')?'text/css':'text/javascript'});
 }
 if(path.startsWith('/qualification/'))return route.fulfill({json:path.endsWith('/session')?{token:'synthetic-session',state}:state});
 if(path.startsWith('/stream/'))return route.fulfill({contentType:'text/html',body:`<script>window.radhouseInput={hide(){},show(){return true},press(){return true}};setTimeout(()=>parent.postMessage({type:'mobileInputStatus',ready:true,touch:true,hardware:false,focused:false},location.origin),50)</script><body style="background:#12151c;color:white">Synthetic browser</body>`});
 return route.fulfill({body:await readFile(new URL('index.html',web)),contentType:'text/html'});
});
const checks=[];
async function bounds(){
 return page.evaluate(()=>{
  const pane=document.querySelector('.browser-pane').getBoundingClientRect();
  const panel=document.querySelector('#key-actions').getBoundingClientRect();
  const buttons=[...document.querySelectorAll('#key-actions button')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,right:r.right,width:r.width,height:r.height,contentsFit:e.scrollWidth<=e.clientWidth+1};});
  return {pane:{x:pane.x,right:pane.right},panel:{x:panel.x,right:panel.right},buttons,width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,streamHeight:document.querySelector('#viewport').getBoundingClientRect().height};
 });
}
try {
 await page.goto('http://localhost:18123/#token=synthetic-root');await expect(page.locator('#input-tools')).toBeVisible();await expect(page.locator('#input-tools')).toBeEnabled();
 for(const [width,height,font] of [[320,720,15],[375,812,15],[390,844,15],[430,932,15],[844,390,15],[390,360,15],[320,360,15],[320,720,24]]) {
  await page.setViewportSize({width,height});await page.evaluate(font=>document.documentElement.style.fontSize=font+'px',font);
  if(await page.locator('#input-tools').getAttribute('aria-expanded')==='true')await page.locator('#input-tools').click();
  const closedHeight=(await bounds()).streamHeight;
  await page.locator('#input-tools').click();await expect(page.locator('#key-actions')).toBeVisible();
  const b=await bounds();assert.equal(b.buttons.length,7);assert(b.scrollWidth<=b.width+1,'page overflows horizontally');
  assert(b.panel.x>=b.pane.x&&b.panel.right<=b.pane.right,'key panel is clipped by pane');
  for(const button of b.buttons){assert(button.x>=b.panel.x&&button.right<=b.panel.right);assert(button.width>0&&button.height>=44);assert(button.contentsFit,'key label clipped');}
  assert(b.streamHeight<=closedHeight+1&&b.streamHeight>=96,'stream fails to fit remaining height');
  for(const button of await page.locator('#key-actions button').all()) {
   await button.scrollIntoViewIfNeeded();const r=await button.boundingBox();
   assert(r.y>=-1&&r.y+r.height<=height+1,'key cannot scroll into the available viewport');
  }
  checks.push({width,height,font,all_seven_keys_inside_pane:true,all_keys_reachable:true,no_horizontal_overflow:true});
  if(output&&width===390)await page.screenshot({path:output+'/layout-'+height+'.png',fullPage:true});
 }
 state.controlling=false;state.mode='agent';state.can_take=true;
 await expect(page.locator('#key-actions')).toBeHidden();await expect(page.locator('#input-tools')).toBeHidden();
 const result={passed:true,checks,authority_loss_closes_panel:true,scope:'actual viewer layout with synthetic transport; short viewport simulates keyboard space, not OS keyboard appearance'};
 if(output)await writeFile(output+'/layout-result.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
}finally{await browser.close();}
