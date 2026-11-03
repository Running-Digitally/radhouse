import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = (await readFile(new URL('../../runtime/selkies/web/mobile-input.js', import.meta.url), 'utf8'))
  .replace(/^import .*;$/gm, '').replace('export function', 'function');
function fixture() {
  let echoUntil = 0, clock = 0, attached = true;
  const waits = [], inputs = [], keys = [], window = {}, document = {hidden:false};
  const field = {value:'',style:{},blur(){document.activeElement=null;},focus(){document.activeElement=field;},
    dispatchEvent(){if(clock >= echoUntil)inputs.push(field.value);field.value='';}};
  window.webrtcInput = {isInputAttached:()=>attached};
  window.matchMedia = ()=>({matches:true,addEventListener(){}});
  window.addEventListener = document.addEventListener = ()=>{};
  window.dispatchEvent = event=>{keys.push(event.key);if(event.key==='Ctrl+l')echoUntil=clock+250;};
  document.getElementById = ()=>field;
  const context = vm.createContext({window,document,URL,Object,JSON,Map,Promise,
    InputEvent:class{},KeyboardEvent:class{constructor(type,values){Object.assign(this,values);}},
    setInterval(){},setTimeout(resolve,delay){waits.push(()=>{clock+=delay;resolve();});},
    hardwareKeyboard:()=>({attached:()=>false,reset(){},subscribe(){}}),
    parseChord:value=>value,chordEvents:key=>[{type:'keydown',key,code:key,state:{}}]});
  vm.runInContext(source+';installMobileInput(()=>{});',context);
  return {api:window.radhouseInput,inputs,keys,document,window,
    revoke(){attached=false;},finish(){assert.equal(waits.length,1);waits.shift()();}};
}
test('address text follows the pinned shortcut echo window and Enter follows text',async()=>{
  const f=fixture(),pending=f.api.navigate('https://example.org/');
  assert.deepEqual(f.inputs,[]);assert.deepEqual(f.keys,['Ctrl+l']);
  f.finish();assert.equal(await pending,true);
  assert.deepEqual(f.inputs,['https://example.org/']);assert.deepEqual(f.keys,['Ctrl+l','Enter']);
});
for(const reason of ['revoked','hidden','dismissed','replaced','newer-input','focus-moved']){
  test('pending address is cancelled when '+reason,async()=>{
    const f=fixture(),pending=f.api.navigate('https://example.org/');
    if(reason==='revoked')f.revoke();
    if(reason==='hidden')f.document.hidden=true;
    if(reason==='dismissed')f.api.hide();
    if(reason==='replaced')f.window.webrtcInput={isInputAttached:()=>true};
    if(reason==='newer-input')f.api.press('escape');
    if(reason==='focus-moved')f.document.activeElement=null;
    f.finish();assert.equal(await pending,false);assert.deepEqual(f.inputs,[]);
    assert.equal(f.keys.includes('Enter'),false);
  });
}
test('invalid destinations do not send any input',async()=>{
  const f=fixture();
  for(const url of ['javascript:alert(1)','https://user:secret@example.org/','file:///tmp/test','not a URL'])
    assert.equal(await f.api.navigate(url),false);
  assert.deepEqual(f.keys,[]);
});
