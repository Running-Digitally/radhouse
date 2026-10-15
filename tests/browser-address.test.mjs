import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const context=vm.createContext({window:{},URL});
vm.runInContext(readFileSync(new URL("../src/radhouse/chat/static/browser-view.js",import.meta.url),"utf8"),context);
const resolve=context.window.RadhouseAddress.resolve;
test("address bar accepts bare domains, local addresses and explicit web URLs",()=>{
  for(const [input,url] of [["example.org","https://example.org/"],["localhost:3000/path","https://localhost:3000/path"],
    ["192.168.1.2:8443","https://192.168.1.2:8443/"],["[::1]:8000/","https://[::1]:8000/"],
    [" http://example.org/page?q=1 ","http://example.org/page?q=1"]]) {
    assert.equal(resolve(input).url,url);assert.equal(resolve(input).kind,"navigation");
  }
});
test("search text uses the selected engine and is encoded as one query",()=>{
  for(const engine of ["google","duckduckgo"]) {
    const result=resolve("a & b # c",engine),url=new URL(result.url);
    assert.equal(result.kind,"search");assert.equal(url.searchParams.get("q"),"a & b # c");
    assert.equal(url.hostname,engine==="google" ? "www.google.com" : "duckduckgo.com");
    assert.equal(url.hash,"");
  }
});
test("address bar rejects non-web schemes, login URLs and protocol-relative ambiguity",()=>{
  for(const text of ["javascript:alert(1)","data:text/html,x","file:///private/file","ftp://example.org","//example.org","https://alice:secret@example.org/",""])
    assert.throws(()=>resolve(text));
  assert.throws(()=>resolve("words","unconfigured"));
});
