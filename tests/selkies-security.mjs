// Installed synthetic regressions; retain only booleans/counts, never values or capabilities.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const links=JSON.parse(await readFile(process.env.RADHOUSE_SELKIES_LINKS,'utf8'));
const base=new URL(links.desktop).origin;
const root=new URLSearchParams(new URL(links.desktop).hash.slice(1)).get('token');
const phoneRoot=new URLSearchParams(new URL(links.phone).hash.replace(/^#phone&/,'')).get('token');
const b=await chromium.launch({channel:'chrome',headless:true});
const context=await b.newContext({viewport:{width:1500,height:1100}});
const checks=[];
async function api(token,path,body) {
 const r=await context.request.fetch(base+'/qualification/'+path,{method:body===undefined?'GET':'POST',
  headers:{Authorization:'Bearer '+token},data:body});return {status:r.status(),value:await r.json()};
}
async function navigate(url){const r=await api(root,'agent',{tool:'browser_navigate',arguments:{url}});assert.equal(r.status,200);assert.equal(r.value.result.success,true);}
try {
 const initial=await api(root,'state');assert.equal(initial.value.mode,'agent');
 const modes=['main','spoof','frame','shadow','otp'];
 if (!initial.value.public_web) modes.push('oop','nested-oop');
 for(const mode of modes) {
  await navigate('http://127.0.0.1:18081/guard.html?mode='+mode);
  await new Promise(r=>setTimeout(r,600));
  const snap=await api(root,'agent',{tool:'browser_snapshot',arguments:{full:true}});
  assert.equal(snap.status,409,mode);assert.equal(snap.value.error,'sensitive_fields_present',mode);
  const state=await api(root,'state');assert.equal(state.value.mode,'agent');assert.equal(state.value.boundary_blocked,false);
  checks.push('snapshot denies synthetic sensitive field: '+mode);
  await navigate('http://127.0.0.1:18081/');
 }
 await navigate('http://127.0.0.1:18081/guard.html?mode=visibility');
 const honest=await api(root,'agent',{tool:'browser_snapshot',arguments:{full:true}});
 assert.equal(honest.status,200);assert.equal(honest.value.result.success,true);
 checks.push('page cannot spoof isolated visible-tab selection');
 await navigate('http://127.0.0.1:18081/');
 const page=await context.newPage();const minted=page.waitForResponse(r=>new URL(r.url()).pathname==='/qualification/session');
 await page.goto(links.desktop);const original=(await (await minted).json()).token;
 await page.locator('#take').click();await expect(page.locator('#owner')).toHaveText('You have control');
 const clone=await context.newPage();await clone.addInitScript(t=>sessionStorage.setItem('radhouse-trial-viewer',t),original);
 const newSession=clone.waitForResponse(r=>new URL(r.url()).pathname==='/qualification/session');
 await clone.goto(base+'/');const cloned=await (await newSession).json();
 assert.notEqual(cloned.token,original);assert.equal(cloned.state.controlling,false);
 const refused=await api(cloned.token,'take',{request_id:crypto.randomUUID(),revision:cloned.state.revision});assert.equal(refused.status,409);
 await page.locator('#return').click();await expect(page.locator('#owner')).toHaveText('Agent has control');
 await clone.close();await page.close();checks.push('copied sessionStorage cannot duplicate document lease ownership');
 let count=0;
 for(let batch=0;batch<3;batch++) {
  await new Promise(r=>setTimeout(r,16000));
  for(let n=0;n<8;n++) {const s=await api(phoneRoot,'session',{});assert.equal(s.status,200);assert.equal(s.value.state.viewing_only,true);count++;}
 }
 checks.push('24 closed phone sessions reclaim idle capacity without role escalation');
 const result={passed:true,checks,session_churn:count,oop_tested:!initial.value.public_web};
 await writeFile(process.env.RADHOUSE_SELKIES_OUTPUT+'/security-result.json',JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify(result));
} finally {await b.close();}
