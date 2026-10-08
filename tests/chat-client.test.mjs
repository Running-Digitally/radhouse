import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const source = readFileSync(new URL("../src/radhouse/chat/static/chat.js", import.meta.url), "utf8");

async function client() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: "", style: {}, dataset: {}, children: [],
      addEventListener() {}, replaceChildren() {},
      querySelectorAll() { return []; },
      getBoundingClientRect() { return { top: 0 }; },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: element, addEventListener() {}, querySelectorAll() { return []; } },
    window: { addEventListener() {} },
    ResizeObserver: class { observe() {} },
    innerHeight: 800, setInterval() {},
    localStorage: { getItem() { return null; } },
    fetch: async () => ({ ok: false, status: 401, json: async () => ({ error: "authentication_required" }) }),
  });
  vm.runInContext(source, context, { filename: fileURLToPath(new URL("../src/radhouse/chat/static/chat.js", import.meta.url)) });
  // Let the real startup request finish before arranging each history load.
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext(`
    session={username:"alice"};
    draftOperation=async () => null;
    controls=()=>{};
    render=()=>{};
    refreshBrowser=async ()=>{};
    matchMedia=()=>({matches:true});
  `, context);
  return context;
}

test("history cleanup preserves an error when sign-out finishes during persistence", async () => {
  const context = await client();
  vm.runInContext(`
    api=async () => { throw new Error("history_failed"); };
    tell=() => { throw new Error("notice_failed"); };
    persist=async () => { session=null; };
  `, context);
  await assert.rejects(vm.runInContext("openConversation()", context), /notice_failed/);
});

test("history cleanup does not repaint a session that signed out during persistence", async () => {
  const context = await client();
  vm.runInContext(`
    let paints=0;
    api=async () => ({});
    accept=()=>{};
    render=()=>{ paints++; };
    persist=async () => { session=null; };
  `, context);
  await vm.runInContext("openConversation()", context);
  assert.equal(vm.runInContext("paints", context), 1);
});

test("history cleanup completes the current session after saving its draft", async () => {
  const context = await client();
  vm.runInContext(`
    let paints=0;
    api=async () => ({});
    accept=()=>{};
    render=()=>{ paints++; };
    persist=async () => { draftWriteFailed=false; };
    retainedSnapshots.set("alice",{});
  `, context);
  await vm.runInContext("openConversation()", context);
  assert.equal(vm.runInContext("paints", context), 2);
  assert.equal(vm.runInContext("retainedSnapshots.has('alice')", context), false);
  assert.equal(vm.runInContext("openingHistory", context), false);
});


test("message limits count Unicode characters and stop at the accepted boundary", async () => {
  const context = await client();
  assert.equal(vm.runInContext("messageFits('💡'.repeat(16000))", context), true);
  assert.equal(vm.runInContext("messageFits('💡'.repeat(16001))", context), false);
  assert.equal(vm.runInContext("messageFits('x'.repeat(16000))", context), true);
  assert.equal(vm.runInContext("messageFits('x'.repeat(100000))", context), false);
});

test("an older history load cannot enable or save a newer draft restoration", async () => {
  const context = await client();
  vm.runInContext(`
    let saves=0, releaseHistory, releaseDraft;
    api=() => new Promise(resolve => { releaseHistory=resolve; });
    accept=()=>{};
    persist=async () => { saves++; };
    firstOpening=openConversation();
  `, context);
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext(`
    draftOperation=() => new Promise(resolve => { releaseDraft=resolve; });
    secondOpening=openConversation();
    releaseHistory({});
  `, context);
  await vm.runInContext("firstOpening", context);
  assert.equal(vm.runInContext("openingHistory", context), true);
  assert.equal(vm.runInContext("saves", context), 0);
  vm.runInContext(`api=async()=>({}); releaseDraft(null);`, context);
  await vm.runInContext("secondOpening", context);
  assert.equal(vm.runInContext("openingHistory", context), false);
  assert.equal(vm.runInContext("saves", context), 1);
});
