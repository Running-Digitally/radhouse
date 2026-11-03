import {chromium, expect} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';

const root=new URL('../src/radhouse/chat/static/',import.meta.url);
const origin='http://responsibilities.fixture';
const id='58e8f3dd-cd82-48a4-9df9-63c3a15b310f';
const state={active:true,scope:{sources:'Recent text in this conversation, up to seven days.',
  preparation:'Prepare useful suggestions',confirmation:'You confirm what counts',excluded:'Attachments, browser and external actions'},
  coverage:{checked_at:Date.now()/1000,outcome:'ready'},last_review:{state:'ready',created_at:Date.now()/1000},
  suggestions:[{id,source_request_id:id,state:'suggested',title:'Prepare the draft',quote:'I intend to send the draft tomorrow.',
    reason:'This may be a commitment you want to keep track of.',preparation:'Review the draft and prepare a short checklist. <script>window.untrusted=true</script>'}]};
const mutations=[],errors=[];
const browser=await chromium.launch({headless:true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
try {
  const context=await browser.newContext({viewport:{width:1120,height:900}});
  await context.route(origin+'/**',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(request.method()==='POST') {
      expect(request.headers()['x-radhouse-csrf']).toBe('synthetic-csrf');
      const body=request.postDataJSON();mutations.push(body);
      if(url.pathname.endsWith(id))state.suggestions[0].state=body.decision;
      else state.active=body.active;
      await route.fulfill({json:{status:'saved'}});return;
    }
    if(url.pathname==='/auth/session'){await route.fulfill({json:{csrf_token:'synthetic-csrf'}});return;}
    if(url.pathname==='/chat/responsibilities/commitments'){await route.fulfill({json:state});return;}
    const files={'/responsibilities':'responsibilities.html','/responsibilities.js':'responsibilities.js','/responsibilities.css':'responsibilities.css'};
    if(!files[url.pathname]){await route.fulfill({status:404,body:'not found'});return;}
    const type=url.pathname.endsWith('.js')?'application/javascript':url.pathname.endsWith('.css')?'text/css':'text/html';
    await route.fulfill({contentType:type,body:await fs.readFile(new URL(files[url.pathname],root),'utf8')});
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin+'/responsibilities');
  await expect(page.getByRole('button',{name:'Confirm commitment'})).toBeVisible();
  await expect(page.getByText('I intend to send the draft tomorrow.')).toBeVisible();
  expect(await page.evaluate(()=>window.untrusted)).toBeUndefined();
  const evidence=process.env.RADHOUSE_UI_EVIDENCE_DIR;
  if(evidence){await fs.mkdir(evidence,{recursive:true});await page.screenshot({path:path.join(evidence,'desktop.png'),fullPage:true});}
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(evidence)await page.screenshot({path:path.join(evidence,'mobile.png'),fullPage:true});
  await page.getByRole('button',{name:'Confirm commitment'}).click();
  await expect(page.getByText('confirmed',{exact:true})).toBeVisible();
  expect(mutations[0]).toEqual({decision:'confirmed'});
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await expect(page.getByRole('button',{name:'Enable suggestions'})).toBeVisible();
  expect(mutations[1]).toEqual({active:false});
  expect(errors).toEqual([]);
  console.log('PASS: desktop/mobile responsibility scope, evidence, confirmation, pause and text safety');
}finally{await browser.close();}
