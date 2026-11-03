import {chromium, expect} from '../web/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';

const root=new URL('../src/radhouse/chat/static/',import.meta.url);
const origin='http://responsibilities.fixture';
const id='58e8f3dd-cd82-48a4-9df9-63c3a15b310f';
const state={active:true,scope:{sources:'Recent text in this conversation, up to seven days.',
  followups_supported:true,preparation:'Prepare useful suggestions',confirmation:'You confirm what counts',excluded:'Attachments, browser and external actions'},
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
      if(url.pathname.endsWith(id)) {
        const item=state.suggestions[0];
        if(body.decision==='confirmed_followup') {
          item.state='confirmed';item.followup={state:'active',revision:1,progress:'',next_review_at:Date.now()/1000,last_review_at:null,latest_note:null,
            research:{enabled:false,question:'',coverage:null}};
        } else if(body.action) {
          expect(body.revision).toBe(item.followup.revision);
          item.followup.revision++;
          if(body.action==='progress')item.followup.progress=body.progress;
          if(body.action==='snooze')item.followup.state='snoozed';
          if(body.action==='resume')item.followup.state='active';
          if(body.action==='complete')item.followup.state='completed';
          if(body.action==='research')item.followup.research={enabled:Boolean(body.question),question:body.question,coverage:null};
        } else item.state=body.decision;
      } else state.active=body.active;
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
  await expect(page.getByRole('button',{name:'Confirm and follow up'})).toBeVisible();
  await expect(page.getByText('I intend to send the draft tomorrow.')).toBeVisible();
  expect(await page.evaluate(()=>window.untrusted)).toBeUndefined();
  const evidence=process.env.RADHOUSE_UI_EVIDENCE_DIR;
  if(evidence){await fs.mkdir(evidence,{recursive:true});await page.screenshot({path:path.join(evidence,'desktop.png'),fullPage:true});}
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(evidence)await page.screenshot({path:path.join(evidence,'mobile.png'),fullPage:true});
  await page.getByRole('button',{name:'Confirm and follow up'}).click();
  await expect(page.getByText('confirmed',{exact:true})).toBeVisible();
  expect(mutations[0]).toEqual({decision:'confirmed_followup'});
  await expect(page.getByRole('button',{name:'Mark complete'})).toBeVisible();
  await page.getByLabel('Progress or a correction').fill('The opening paragraph is finished.');
  await page.getByRole('button',{name:'Save progress'}).click();
  await expect(page.getByLabel('Progress or a correction')).toHaveValue('The opening paragraph is finished.');
  expect(mutations[1]).toEqual({action:'progress',revision:1,progress:'The opening paragraph is finished.'});
  await page.getByRole('button',{name:'Snooze 1 day',exact:true}).click();
  await expect(page.getByRole('button',{name:'Resume now'})).toBeVisible();
  await page.getByRole('button',{name:'Resume now'}).click();
  await expect(page.getByRole('button',{name:'Resume now'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Enable public research'})).toBeVisible();
  await page.getByLabel('Public research question').fill('What makes a clear technical draft?');
  await page.getByRole('button',{name:'Enable public research'}).click();
  await expect(page.getByRole('button',{name:'Stop public research'})).toBeVisible();
  expect(mutations.at(-1)).toEqual({action:'research',revision:4,question:'What makes a clear technical draft?'});
  const followup=state.suggestions[0].followup;
  followup.research.coverage={coverage:'partial',checked_at:Date.now()/1000,provider:'keenable',source_count:1};
  followup.latest_note={action:'update',reason:'Public source supports this next step.',preparation:'Consider the audience first.',quote:'send the draft',
    citations:[{source_id:'a'.repeat(64),title:'Public writing guide <img onerror=alert(1)>',url:'https://example.org/guide',quote:'Identify the audience before drafting.',retrieved_at:Date.now()/1000}]};
  await page.reload();
  await expect(page.getByText(/Limited research: 1 source/)).toBeVisible();
  const citation=page.getByRole('link',{name:/Public writing guide/});
  await expect(citation).toHaveAttribute('rel','noopener noreferrer');
  await expect(page.locator('article aside img')).toHaveCount(0);
  if(evidence)await page.screenshot({path:path.join(evidence,'public-research-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1120,height:900});
  if(evidence)await page.screenshot({path:path.join(evidence,'public-research-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'Stop public research'}).click();
  await expect(page.getByRole('button',{name:'Enable public research'})).toBeVisible();
  expect(mutations.at(-1)).toEqual({action:'research',revision:5,question:''});
  if(evidence)await page.screenshot({path:path.join(evidence,'active-followup.png'),fullPage:true});
  await page.getByRole('button',{name:'Mark complete'}).click();
  await expect(page.getByText('completed',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Save progress'})).toHaveCount(0);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await expect(page.getByRole('button',{name:'Resume reviews'})).toBeVisible();
  expect(mutations.at(-1)).toEqual({active:false});
  expect(errors).toEqual([]);
  console.log('PASS: desktop/mobile responsibility scope, evidence, confirmation, progress, snooze, completion, pause and text safety');
}finally{await browser.close();}
