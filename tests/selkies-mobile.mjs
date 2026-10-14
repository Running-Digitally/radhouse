// Focused mobile pilot: the existing Selkies assist/IME path and real stream.
// OS keyboard appearance remains actual-device acceptance, not emulation.
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const {chromium, expect} = await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const links=JSON.parse(await readFile(process.env.RADHOUSE_SELKIES_LINKS,'utf8'));
const base=new URL(links.desktop).origin;
const root=new URLSearchParams(new URL(links.desktop).hash.slice(1)).get('token');
const output=process.env.RADHOUSE_SELKIES_OUTPUT;
await mkdir(output,{recursive:true,mode:0o700});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:3});
const page=await context.newPage();const checks=[];
async function api(token,path,body){const r=await context.request.fetch(base+'/qualification/'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token},data:body});return {status:r.status(),value:await r.json()};}
function active(){const f=JSON.parse(execFileSync('docker',['exec',process.env.RADHOUSE_SELKIES_CONTAINER,'python','-c','import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:18081/state").read().decode())'],{encoding:'utf8'}));const pages=Object.values(f.pages);return pages.filter(p=>p.focused).at(-1)||pages.at(-1);}
async function until(test){for(let n=0;n<60;n++){if(test())return;await page.waitForTimeout(100);}throw new Error('synthetic_mobile_postcondition_failed');}
async function ready(p,attached=false){await p.waitForFunction(a=>{const w=document.querySelector('#stream')?.contentWindow;return w?.document.querySelector('#videoStream')?.videoWidth>0&&(!a||w.radhouseInput?.status().ready);},attached,{timeout:20000});}
function core(p=page){return p.frames().find(f=>f.parentFrame());}
async function text(value,composing=false){await core().locator('#keyboard-input-assist').evaluate((field,{value,composing})=>{field.value=value;field.dispatchEvent(new InputEvent('input',{bubbles:true,data:value,inputType:composing?'insertCompositionText':'insertText',isComposing:composing}));},{value,composing});}
async function key(name){if(!await page.locator('#input-tools').evaluate(e=>e.open))await page.locator('#input-tools summary').click();await page.locator('[data-key="'+name+'"]').click();}
try {
 const nav=await api(root,'agent',{tool:'browser_navigate',arguments:{url:'http://127.0.0.1:18081/?mobile=pilot'}});assert.equal(nav.status,200);assert.equal(nav.value.result.success,true);
 const minted=page.waitForResponse(r=>new URL(r.url()).pathname==='/qualification/session');await page.goto(links.desktop);const token=(await(await minted).json()).token;
 await ready(page);await expect(page.locator('#take')).toBeVisible();await expect(page.locator('#keyboard')).toBeHidden();
 await page.locator('#take').click();await expect(page.locator('#owner')).toHaveText('You have control');await ready(page,true);await expect(page.locator('#keyboard')).toBeEnabled();checks.push('same controlling capability supports phone takeover');
 const f=active(),r=f.rects.name;const point=await page.evaluate(({x,y})=>{const i=document.querySelector('#stream'),o=i.getBoundingClientRect(),v=i.contentDocument.querySelector('#videoStream'),b=v.getBoundingClientRect(),s=Math.min(b.width/v.videoWidth,b.height/v.videoHeight);return{x:o.x+b.x+(b.width-v.videoWidth*s)/2+x*s,y:o.y+b.y+(b.height-v.videoHeight*s)/2+y*s};},{x:f.offset.x+r.x+r.width/2,y:f.offset.y+r.y+r.height/2});
 await page.touchscreen.tap(point.x,point.y);await page.locator('#keyboard').click();
 assert.equal(await core().locator('#keyboard-input-assist').evaluate(e=>document.activeElement===e),true);
 await text('Mobile ');await until(()=>active().name==='Mobile ');
 const assist=core().locator('#keyboard-input-assist');await assist.dispatchEvent('compositionstart',{data:''});await text('a',true);await text('é',true);await assist.dispatchEvent('compositionend',{data:'é'});await until(()=>active().name==='Mobile é');
 await key('backspace');await until(()=>active().name==='Mobile ');checks.push('upstream assist sends text, composition and deletion through real stream');
 await page.keyboard.press('Escape');await expect(page.locator('#keyboard')).toBeHidden();
 if(!await page.locator('#input-tools').evaluate(e=>e.open))await page.locator('#input-tools summary').click();await page.locator('#keyboard-override').click();await expect(page.locator('#keyboard')).toBeVisible();checks.push('hardware-keyboard detection has explicit override');
 await key('tab');await key('escape');const beforeAddress=active().marker;await key('address');await text('http://127.0.0.1:18081/?mobile=address');await key('enter');await until(()=>active().marker!==beforeAddress);checks.push('fixed address-bar and navigation soft keys work');
 await page.setViewportSize({width:844,height:390});await ready(page,true);await page.setViewportSize({width:390,height:844});await ready(page,true);checks.push('orientation preserves live browser and control');
 await page.locator('#return').click();await expect(page.locator('#owner')).toHaveText('Agent has control',{timeout:15000});await ready(page);assert.equal(await core().evaluate(()=>window.radhouseInput.show(true)),false);assert.equal(await core().locator('#keyboard-input-assist').inputValue(),'');await expect(page.locator('#keyboard')).toBeHidden();checks.push('return clears assist and removes mobile input authority');
 const viewer=await context.newPage();await viewer.goto(links.phone);await ready(viewer);await expect(viewer.locator('#take')).toBeHidden();await expect(viewer.locator('#keyboard')).toBeHidden();assert.equal(await core(viewer).evaluate(()=>window.radhouseInput.show(true)),false);assert.equal(await core(viewer).evaluate(()=>window.radhouseInput.press('enter')),false);checks.push('view-only capability cannot enable mobile keyboard or soft keys');
 await page.screenshot({path:output+'/mobile-pilot.png'});
 const result={passed:true,checks,real_phone_tested:false,os_keyboard_appearance_verified:false,synthetic_composition_and_remote_value_verified:true};await writeFile(output+'/mobile-result.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
} finally {await browser.close();}
