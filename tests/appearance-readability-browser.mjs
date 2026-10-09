// Real shared styles, decorated controls and pinned xterm; no live VM or owner state.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href);
const root=new URL('../src/radhouse/chat/static/',import.meta.url),origin='http://127.0.0.1:61397';
const catalog=JSON.parse(await readFile(new URL('agent-profile/catalog.json',root),'utf8'));
const browser=await chromium.launch({headless:true,executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH});
const context=await browser.newContext({viewport:{width:1280,height:1100}}),page=await context.newPage(),errors=[];
page.on('pageerror',error=>errors.push(error.message));
const fixture=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/chat.css"><link rel="stylesheet" href="/browser-view.css"><link rel="stylesheet" href="/navigation.css"><link rel="stylesheet" href="/owner-terminal.css"><link rel="stylesheet" href="/agent-profile.css"><link rel="stylesheet" href="/vendor/xterm/xterm.css">
<script src="/navigation.js" defer></script><script src="/vendor/xterm/xterm.js" defer></script><script src="/vendor/xterm/addon-fit.js" defer></script><script src="/owner-terminal.js" defer></script><script src="/agent-profile.js" defer></script><script src="/fixture.js" defer></script></head>
<body><div class="shell"><header><a class="brand" href="/">Radhouse</a><button id="logout">Sign out</button></header><nav id="management-nav" hidden><a href="/agent">Your Agent</a></nav>
<main><section class="workspace-page"><h1>Your Agent</h1><div id="profile"></div><div id="button-checks"><button class="primary" id="fixture-send">Send</button><button class="primary" id="fixture-open">Open browser</button><button class="primary" id="fixture-signin">Sign in</button></div><div id="terminal"></div></section></main></div></body></html>`;
const bootstrap=`window.profile=new RadhouseAgentProfile({container:document.getElementById('profile'),request:async path=>path.includes('catalog')?${JSON.stringify(catalog)}:{schema:'radhouse.agent-profile.v1',revision:0,name:'',intro:'',theme:'hearthside',portrait:'ember',accent:'fern',surface:'paper',stateMotion:false,iconMotion:false,portraitSize:80}});
document.addEventListener('click',event=>{if(event.target.closest('button.primary'))event.preventDefault();},true);
profile.setVisible(true);void profile.load();RadhouseNavigation.update({username:'fixture',management:{read:true}});
for(const id of ['fixture-send','fixture-open'])RadhouseIcons.decorate(document.getElementById(id),id==='fixture-send'?'send':'browser',document.getElementById(id).textContent);
window.terminalView=new OwnerTerminalView(document.getElementById('terminal'),{tab:'11111111-1111-4111-8111-111111111111',request:async()=>({state:'open',terminal_id:'22222222-2222-4222-8222-222222222222',generation:'33333333-3333-4333-8333-333333333333',attach_epoch:1,next_cursor:0,last_sequence:0,last_outcome:'none',data_b64:''})});
terminalView.visible=true;terminalView._apply({state:'open',terminal_id:'22222222-2222-4222-8222-222222222222',generation:'33333333-3333-4333-8333-333333333333',attach_epoch:1,last_sequence:0});terminalView.term.write('bash-5.2$ ls\\r\\nhermes workspaces\\r\\n\\x1b[30mANSI_BLACK_WORD\\x1b[0m\\r\\nbash-5.2$ ');`;
await context.route(origin+'/**',async route=>{
 const path=new URL(route.request().url()).pathname;
 if(path==='/agent')return route.fulfill({contentType:'text/html',body:fixture});
 if(path==='/fixture.js')return route.fulfill({contentType:'text/javascript',body:bootstrap});
 const name=path.startsWith('/workspace-assets/')?path.slice(18):path.slice(1);
 return route.fulfill({contentType:name.endsWith('.css')?'text/css':name.endsWith('.webp')?'image/webp':'text/javascript',body:await readFile(new URL(name,root))});
});
const measure=async selector=>page.locator(selector).evaluate(element=>{
 const luminance=rgb=>{const c=rgb.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>rgb.startsWith('color(')?v:v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
 const style=getComputedStyle(element),label=element.querySelector('.rh-action-label')||element,fg=getComputedStyle(label).color;
 const bg=style.backgroundColor,a=luminance(fg),b=luminance(bg);
 return {buttonForeground:style.color,foreground:fg,background:bg,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),opacity:Number(style.opacity)};
});
try {
 await page.goto(origin+'/agent');await expect(page.getByRole('tab',{name:'Appearance',exact:true})).toBeVisible();
 await page.getByRole('tab',{name:'Appearance',exact:true}).click();
 await expect.poll(()=>page.locator('.xterm-rows').textContent()).toContain('hermes workspaces');
 const baseline=[];
 for(const surface of ['Warm paper','Evening']){
  await page.getByRole('radio',{name:surface,exact:true}).check();
  const terminal=await page.locator('.xterm-rows span').first().evaluate(e=>({foreground:getComputedStyle(e).color,background:getComputedStyle(document.querySelector('.owner-terminal-viewport')).backgroundColor}));
  baseline.push({surface,save:await measure('.agent-profile-actions .primary'),terminal});
 }
 console.log('Contrast observations:',JSON.stringify(baseline));
 // Each palette must remain readable at rest, hover, pressed, disabled and focused.
 for(const surface of ['Warm paper','Evening'])for(const accent of ['Fern','Clay','Tide','Plum']){
  await page.getByRole('radio',{name:surface,exact:true}).check();await page.getByRole('radio',{name:accent,exact:true}).check();
  for(const selector of ['.agent-profile-actions .primary','#fixture-send','#fixture-open','#fixture-signin']){
   const control=page.locator(selector);
   for(const disabled of [false,true]){
    await control.evaluate((e,value)=>{e.disabled=value;},disabled);await page.mouse.move(0,0);await page.waitForTimeout(200);
    for(const state of ['rest','hover','pressed','focus']){
     if(state==='hover')await control.hover();
     if(state==='pressed'&&!disabled)await page.mouse.down();
     if(state==='focus'&&!disabled){await page.mouse.up();await control.focus();}
     await expect(page.locator('html')).toHaveAttribute('data-rh-surface',surface==='Evening'?'night':'paper');
     const value=await measure(selector);
     expect(value.opacity,`${surface}/${accent}/${selector}/${state}/disabled=${disabled}`).toBe(1);
     expect(value.contrast,JSON.stringify({surface,accent,selector,state,disabled,...value})).toBeGreaterThanOrEqual(4.5);
    }
    await page.mouse.up();
   }
  }
  const value=await page.locator('.xterm-rows span').first().evaluate(e=>{
   const fg=getComputedStyle(e).color,bg=getComputedStyle(document.querySelector('.owner-terminal-viewport')).backgroundColor;
   const lum=color=>{const c=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>color.startsWith('color(')?v:v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
   const a=lum(fg),b=lum(bg);return {fg,bg,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
  });
  expect(value.contrast,JSON.stringify({surface,accent,terminal:value})).toBeGreaterThanOrEqual(7);
  const black=page.locator('.xterm-rows span').filter({hasText:'ANSI_BLACK_WORD'});
  await expect(black).toHaveCount(1);
  const ansi=await black.evaluate(e=>{
   const fg=getComputedStyle(e).color,bg=getComputedStyle(document.querySelector('.owner-terminal-viewport')).backgroundColor;
   const lum=color=>{const c=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>color.startsWith('color(')?v:v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;};
   const a=lum(fg),b=lum(bg);return {fg,bg,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
  });
  expect(ansi.contrast,JSON.stringify({surface,accent,ansi})).toBeGreaterThanOrEqual(7);
 }
 await expect(page.locator('.agent-accent-options .agent-window-preview')).toHaveCount(4);
 await expect(page.locator('.agent-surface-options .agent-window-preview')).toHaveCount(3);
 // Card selection remains native keyboard-accessible without extra preview controls.
 await page.getByRole('radio',{name:'Warm paper',exact:true}).focus();await page.keyboard.press('ArrowRight');
 await expect(page.getByRole('radio',{name:'Evening',exact:true})).toBeChecked();
 await page.getByRole('radio',{name:'Follow device',exact:true}).check();
 await page.emulateMedia({colorScheme:'dark'});await expect(page.locator('html')).toHaveAttribute('data-rh-surface','night');
 await page.emulateMedia({colorScheme:'light'});await expect(page.locator('html')).toHaveAttribute('data-rh-surface','paper');
 for(const width of [1280,390,320]){
  await page.setViewportSize({width,height:1100});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const cards=await page.locator('.agent-window-preview').evaluateAll(nodes=>nodes.map(e=>({width:e.getBoundingClientRect().width,visible:e.getBoundingClientRect().height>0})));
  expect(cards.every(c=>c.visible&&c.width>=80)).toBe(true);
 }
 await page.evaluate(()=>{document.getElementById('button-checks').hidden=true;document.getElementById('terminal').hidden=true;document.querySelector('.workspace-page').scrollTop=0;profile.updateActions();});
 await page.setViewportSize({width:1280,height:1100});await page.mouse.move(0,0);
 await page.screenshot({path:'/private/tmp/radhouse-appearance-previews-light.png',fullPage:true});
 await page.getByRole('radio',{name:'Evening',exact:true}).check();await page.mouse.move(0,0);
 await page.screenshot({path:'/private/tmp/radhouse-appearance-previews-dark.png',fullPage:true});
 await page.setViewportSize({width:390,height:1100});await page.locator('.workspace-page').evaluate(e=>{e.scrollTop=0;});await page.screenshot({path:'/private/tmp/radhouse-appearance-previews-mobile.png',fullPage:true});
 await page.getByRole('radio',{name:'Warm paper',exact:true}).check();
 await page.evaluate(()=>{document.getElementById('terminal').hidden=false;});await page.locator('#terminal').scrollIntoViewIfNeeded();
 await expect(page.locator('.owner-terminal-viewport')).toBeVisible();
 expect(await page.locator('#terminal').evaluate(e=>e.getBoundingClientRect().height)).toBeGreaterThan(400);
 await page.locator('#terminal').screenshot({path:'/private/tmp/radhouse-terminal-readable-light.png'});
 expect(errors).toEqual([]);
 console.log('Appearance readability: four palettes/two surfaces, enabled/disabled/hover/pressed/focus controls, real xterm text, visual choices and 1280/390/320px passed.');
} finally {await context.close();await browser.close();}
