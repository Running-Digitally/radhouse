import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

class DOMNode {
  constructor(tag, text = "") { this.tag = tag; this.text = text; this.children = []; this.dataset = {}; this.events = {}; this.attributes = new Map(); }
  append(...nodes) { this.children.push(...nodes); }
  set textContent(text) { this.children = []; this.text = text; }
  get textContent() { return this.text + this.children.map(node => node.textContent).join(""); }
  addEventListener(name, action) { this.events[name] = action; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
}

function formatter() {
  const copied = [];
  const body = new DOMNode("body");
  const byId = (node, id) => node.id === id ? node : node.children.map(child => byId(child, id)).find(Boolean);
  const context = vm.createContext({
    window: {}, URL,
    document: {
      body,
      getElementById: id => byId(body, id) || null,
      createElement: tag => new DOMNode(tag),
      createTextNode: text => new DOMNode("#text", text),
      createDocumentFragment: () => new DOMNode("#fragment"),
    },
    navigator: { clipboard: { async writeText(text) { copied.push(text); } } },
    setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(readFileSync(new URL("../src/radhouse/chat/static/format.js", import.meta.url), "utf8"), context, { filename: fileURLToPath(new URL("../src/radhouse/chat/static/format.js", import.meta.url)) });
  return { ...context.window.RadhouseFormat, copied };
}

function descendants(node, tag) {
  return node.children.flatMap(child => [ ...(child.tag === tag ? [child] : []), ...descendants(child, tag) ]);
}

test("inline formatting preserves text, links and literal source HTML", () => {
  const { render } = formatter();
  const tree = render('Hello **bold** and *soft* with `code`, [guide](https://example.com/a) and http://example.com. <script>unsafe()</script>');
  assert.equal(descendants(tree, "strong")[0].textContent, "bold");
  assert.equal(descendants(tree, "em")[0].textContent, "soft");
  assert.equal(descendants(tree, "code")[0].textContent, "code");
  assert.equal(descendants(tree, "a")[0].href, "https://example.com/a");
  assert.equal(descendants(tree, "a")[0].rel, "noopener noreferrer");
  assert.equal(descendants(tree, "a")[0].target, "_blank");
  assert.equal(descendants(tree, "a").length, 2);
  assert.equal(descendants(tree, "script").length, 0);
  assert.ok(tree.textContent.includes("<script>unsafe()</script>"));
});

test("invalid and active-content links remain literal text", () => {
  const { render } = formatter();
  for (const text of ["[run](javascript:alert)", "[data](data:text/html,payload)", "[relative](/private)", "[broken](https://)"]) {
    const tree = render(text);
    assert.equal(descendants(tree, "a").length, 0);
    assert.equal(tree.textContent, text);
  }
});

test("headings, ordered lists and fenced code keep their display and copy contracts", async () => {
  const { render, copied } = formatter();
  const tree = render("## Small step\n\n3. first\n4. second\n\n```python\nprint('hello')\n```");
  assert.equal(descendants(tree, "h3")[0].textContent, "Small step");
  assert.equal(descendants(tree, "ol")[0].start, 3);
  assert.deepEqual(descendants(tree, "li").map(node => node.textContent), ["first", "second"]);
  assert.equal(descendants(tree, "pre")[0].textContent, "print('hello')");
  const button = descendants(tree, "button")[0];
  assert.equal(button.textContent, "Copy");
  assert.equal(button.getAttribute("aria-label"), "Copy code");
  await button.events.click();
  assert.deepEqual(copied, ["print('hello')"]);
  assert.equal(button.textContent, "Copied");
  assert.equal(button.getAttribute("aria-label"), "Copied");
  assert.equal(button.getAttribute("aria-busy"), "false");
});

test("unclosed markers, mixed list kinds and paragraph line breaks remain readable", () => {
  const { render } = formatter();
  const tree = render("before\nafter\n\n- one\n1. two\n\n**unclosed [link `code");
  assert.equal(descendants(tree, "br").length, 1);
  assert.equal(descendants(tree, "ul").length, 1);
  assert.equal(descendants(tree, "ol").length, 1);
  assert.ok(tree.textContent.endsWith("**unclosed [link `code"));
});

test("long unmatched delimiters and whitespace do not cause quadratic rendering", () => {
  const { render } = formatter();
  const start = performance.now();
  for (const text of ["[".repeat(100_000), "*".repeat(100_000), "#" + " ".repeat(100_000), "-" + " ".repeat(100_000)]) {
    const tree = render(text);
    assert.ok(tree.textContent.length > 0);
  }
  assert.ok(performance.now() - start < 2000, "Delimiter-heavy replies must remain responsive");
});
