// Real UI code, owned browser, synthetic transfer endpoints and originals.
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {pathToFileURL} from "node:url";
import assert from "node:assert/strict";
import {cover,closeBrowser} from "./browser-coverage.mjs";
const modulePath=process.env.RADHOUSE_PLAYWRIGHT_MODULE || new URL("../web/node_modules/@playwright/test/index.mjs",import.meta.url).pathname;
const {chromium,expect}=await import(pathToFileURL(modulePath));
const assets=new URL("../src/radhouse/chat/static/",import.meta.url);
const file={file_id:"00000000-0000-4000-8000-000000000001",name:"<img src=x onerror=alert(1)>.txt",private:true,origin:"browser",source:"user",download_url:"/original"};
let chooser={id:"a".repeat(32),destination:"https://example.org/upload",multiple:false};
let fail=false,requests=[],privateUploads=[];
const html=`<!doctype html><meta charset="utf-8"><button id="show">Check website file chooser</button><p id="notice"></p>
<input id="library-search"><select id="library-source"><option value="all">All</option></select>
<button id="library-more">More</button><button id="library-refresh">Refresh</button><p id="library-status"></p><div id="library-files"></div>
<script src="/workspace-assets/browser-files.js"></script><script src="/library.js"></script><script>
const request=async(path,body,method)=>{const r=await fetch(path,{method:method || (body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok)throw Error('fixture');return r.json()};
const view={generation:'generation',control:{mode:'human'},_human:()=>view.control.mode==='human',_binding:()=>({generation:'generation',revision:1,lease_id:'lease'}),request,_renderControlState:()=>document.getElementById('notice').textContent=view.actionNotice};
const files=new RadhouseBrowserFiles(view,async(blob,privateFile)=>{await request('/device',{name:blob.name,private:privateFile});return '${file.file_id}'});
document.getElementById('show').onclick=()=>{files.lastPoll=0;files.update({files_enabled:true})};
const library=new RadhouseLibrary({request,card:()=>document.createElement('article'),openMessage:()=>{}});library.load();
window.fixture={files,view,library};
</script>`;
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/'){res.setHeader('Content-Type','text/html');res.end(html);return;}
 if(url.pathname.endsWith('.js')){res.setHeader('Content-Type','text/javascript');res.end(await readFile(new URL(url.pathname.split('/').at(-1),assets)));return;}
 const chunks=[];for await(const chunk of req)chunks.push(chunk);
 const body=chunks.length?JSON.parse(Buffer.concat(chunks)):null;
 res.setHeader('Content-Type','application/json');
 if(url.pathname==='/chat/library'){res.end(JSON.stringify({files:[file],next_cursor:null}));return;}
 if(url.pathname==='/chat/browser/files'){res.end(JSON.stringify({chooser}));return;}
 if(url.pathname==='/device'){privateUploads.push(body);res.end('{}');return;}
 if(url.pathname==='/chat/browser/files/upload'){requests.push(body);res.statusCode=fail?409:200;if(!fail)chooser=null;res.end(JSON.stringify({applied:!fail}));return;}
 if(url.pathname.endsWith('/share')){file.private=false;res.end(JSON.stringify({private:false}));return;}
 res.statusCode=404;res.end('{}');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage();await cover(page);
 await page.goto(`http://127.0.0.1:${server.address().port}/`);
 await expect(page.getByText('Private',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Share with assistant'}).click();
 await expect(page.getByText('Shared with assistant',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Check website file chooser'}).click();
 const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
 await expect(dialog.getByText('Upload to https://example.org',{exact:true})).toBeVisible();
 await expect(dialog.locator('img')).toHaveCount(0);
 await dialog.getByRole('button',{name:file.name,exact:true}).click();
 await expect(dialog).not.toBeVisible();assert.equal(requests.length,1);
 assert.equal(requests[0].destination,'https://example.org/upload');assert.equal(requests[0].file_id,file.file_id);
 chooser={id:'b'.repeat(32),destination:'https://example.org/upload',multiple:false};
 await page.getByRole('button',{name:'Check website file chooser'}).click();await expect(dialog).toBeVisible();
 await dialog.locator('input[type=file]').setInputFiles({name:'device.txt',mimeType:'text/plain',buffer:Buffer.from('synthetic device original')});
 await expect(dialog).not.toBeVisible();assert.equal(requests.length,2);assert.equal(privateUploads[0].private,true);
 chooser={id:'c'.repeat(32),destination:'https://example.org/upload',multiple:false};fail=true;
 await page.getByRole('button',{name:'Check website file chooser'}).click();await expect(dialog).toBeVisible();
 await dialog.getByRole('button',{name:file.name,exact:true}).click();
 await expect(dialog.getByText(/Upload wasn’t confirmed/)).toBeVisible();assert.equal(requests.length,3);
 await page.evaluate(()=>{fixture.view.control.mode='agent';fixture.files.update({files_enabled:true})});
 await expect(dialog).not.toBeVisible();assert.equal(requests.length,3);
 console.log('PASS: Library sharing, device/Library picker, inert filenames, destination binding, failed upload and control loss');
} finally {await closeBrowser(browser);await new Promise(resolve=>server.close(resolve));}
