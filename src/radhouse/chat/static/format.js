"use strict";
// A deliberately small DOM formatter: source HTML is always text, never markup.
window.RadhouseFormat = (() => {
  function nextPositions(text, matches) {
    const positions = new Uint32Array(text.length + 1);
    let next = text.length;
    positions[text.length] = next;
    for (let i = text.length - 1; i >= 0; i--) {
      if (matches(text[i])) next = i;
      positions[i] = next;
    }
    return positions;
  }
  function delimiters(text) {
    return {
      tick: nextPositions(text, c => c === "`"),
      star: nextPositions(text, c => c === "*"),
      bracket: nextPositions(text, c => c === "]"),
      newline: nextPositions(text, c => c === "\n"),
      linkEnd: nextPositions(text, c => c === ")" || /\s/.test(c)),
      urlEnd: nextPositions(text, c => c === "<" || c === ">" || /\s/.test(c)),
    };
  }
  function markedToken(text, start, positions, marker, tag) {
    const body = start + marker.length;
    const end = positions[body];
    if (end <= body || end >= text.length || !text.startsWith(marker, end)) return null;
    return { start, end: end + marker.length, tag, label: text.slice(body, end) };
  }
  function markdownToken(text, start, positions) {
    const close = positions.bracket[start + 1];
    if (close <= start + 1 || close >= positions.newline[start + 1] || text[close + 1] !== "(") return null;
    const end = positions.linkEnd[close + 2];
    if (end <= close + 2 || text[end] !== ")") return null;
    return { start, end: end + 1, tag: "a", label: text.slice(start + 1, close), url: text.slice(close + 2, end) };
  }
  function urlToken(text, start, positions) {
    let length = 0;
    if (text.startsWith("https://", start)) length = 8;
    else if (text.startsWith("http://", start)) length = 7;
    if (!length) return null;
    const end = positions.urlEnd[start + length];
    if (end <= start + length) return null;
    const url = text.slice(start, end);
    return { start, end, tag: "a", label: url, url };
  }
  function inlineToken(text, start, positions) {
    if (text[start] === "`") return markedToken(text, start, positions.tick, "`", "code");
    if (text[start] === "*") {
      if (text[start + 1] === "*") return markedToken(text, start, positions.star, "**", "strong");
      return markedToken(text, start, positions.star, "*", "em");
    }
    if (text[start] === "[") return markdownToken(text, start, positions);
    if (text[start] === "h") return urlToken(text, start, positions);
    return null;
  }
  function tokenElement(token, text) {
    const original = text.slice(token.start, token.end);
    let url;
    if (token.tag === "a") {
      try { url = new URL(token.url); }
      catch { return document.createTextNode(original); }
      if (!["https:", "http:"].includes(url.protocol)) return document.createTextNode(original);
    }
    const element = document.createElement(token.tag);
    element.textContent = token.label;
    if (url) {
      element.href = url.href;
      element.target = "_blank";
      element.rel = "noopener noreferrer";
    }
    return element;
  }
  function inline(parent, text) {
    const positions = delimiters(text);
    let offset = 0;
    for (let index = 0; index < text.length;) {
      const token = inlineToken(text, index, positions);
      if (!token || positions.newline[index] < token.end) { index++; continue; }
      parent.append(document.createTextNode(text.slice(offset, index)), tokenElement(token, text));
      index = token.end;
      offset = index;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  function headingText(line) {
    const text = line, marker = text.match(/^#{1,6}\s/);
    if (!marker) return null;
    return text.slice(marker[0].length).trimStart() || null;
  }
  function listItem(line) {
    const text = line.trimStart(), marker = text.match(/^([-*+]|\d+[.)])\s/);
    if (!marker) return null;
    const label = text.slice(marker[0].length).trimStart();
    if (!label) return null;
    return { label, ordered: /^\d/.test(marker[1]), start: Number.parseInt(marker[1], 10) };
  }
  function fenceLabel(line) {
    const text = line.trimStart();
    if (!text.startsWith("```") || text.slice(3).includes("`")) return null;
    return text.slice(3).trim();
  }
  function codeBlock(lines, start, language) {
    const code = [];
    let next = start + 1;
    while (next < lines.length && lines[next].trim() !== "```") code.push(lines[next++]);
    if (next < lines.length) next++;
    const block = document.createElement("div"); block.className = "code-block";
    const header = document.createElement("div"); header.className = "code-header";
    const label = document.createElement("span"); label.textContent = language || "Code";
    const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy";
    copy.dataset.label = "Copy"; copy.dataset.copyKind = "code"; copy.dataset.accessibleLabel = "Copy code"; copy.setAttribute("aria-label","Copy code");
    window.RadhouseIcons?.decorate(copy, "clipboard", "Copy", {accessibleLabel:"Copy code"});
    const content = code.join("\n");
    copy.addEventListener("click", () => copyText(content, copy)); header.append(label, copy);
    const pre = document.createElement("pre"), body = document.createElement("code"); body.textContent = content;
    pre.append(body); block.append(header, pre);
    return { node: block, next };
  }
  function listBlock(lines, start, first) {
    const node = document.createElement(first.ordered ? "ol" : "ul");
    if (first.ordered) node.start = first.start;
    let next = start;
    while (next < lines.length) {
      const item = listItem(lines[next]);
      if (!item || item.ordered !== first.ordered) break;
      const li = document.createElement("li"); inline(li, item.label); node.append(li); next++;
    }
    return { node, next };
  }
  function startsBlock(line) {
    return /^(?:```|#{1,6}\s|[-*+]\s|\d+[.)]\s)/.test(line.trimStart());
  }
  function paragraphBlock(lines, start) {
    const node = document.createElement("p");
    inline(node, lines[start]);
    let next = start + 1;
    while (next < lines.length && lines[next].trim() && !startsBlock(lines[next])) {
      node.append(document.createElement("br")); inline(node, lines[next++]);
    }
    return { node, next };
  }
  function render(text) {
    const result = document.createDocumentFragment(), lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length;) {
      if (!lines[i].trim()) { i++; continue; }
      const language = fenceLabel(lines[i]);
      if (language !== null) {
        const block = codeBlock(lines, i, language); result.append(block.node); i = block.next; continue;
      }
      const heading = headingText(lines[i]);
      if (heading) { const node = document.createElement("h3"); inline(node, heading); result.append(node); i++; continue; }
      const item = listItem(lines[i]);
      if (item) { const block = listBlock(lines, i, item); result.append(block.node); i = block.next; continue; }
      const block = paragraphBlock(lines, i); result.append(block.node); i = block.next;
    }
    return result;
  }
  const copyTimers = new WeakMap();
  async function copyText(text, button) {
    if (button.disabled) return;
    clearTimeout(copyTimers.get(button));
    const hadFocus = document.activeElement === button;
    const label = button.dataset.label || "Copy";
    const accessibleLabel = button.dataset.accessibleLabel || label;
    const show = (icon, text, name=text) => {
      if (window.RadhouseIcons) window.RadhouseIcons.decorate(button, icon, text, {compact:button.dataset.copyKind === "answer",accessibleLabel:name});
      else { button.textContent = text; button.setAttribute("aria-label",name); }
    };
    let status = document.getElementById("radhouse-copy-status");
    if (!status) {
      status = document.createElement("span"); status.id = "radhouse-copy-status";
      status.className = "rh-copy-status"; status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite"); document.body.append(status);
    }
    button.disabled = true; window.RadhouseIcons?.busy(button, true);
    status.textContent = "Copying…";
    try {
      await navigator.clipboard.writeText(text);
      show("check", "Copied"); button.dataset.state = "success";
      status.textContent = button.dataset.copyKind === "answer" ? "Answer copied." : "Code copied.";
      button.removeAttribute("title");
    } catch {
      show("warning", "Copy unavailable"); button.dataset.state = "error";
      status.textContent = "Copy unavailable. Select the text to copy it.";
      button.title = "Select the text to copy it.";
    } finally {
      button.disabled = false; button.setAttribute("aria-busy", "false");
      if (hadFocus && button.isConnected && document.activeElement === document.body) button.focus({preventScroll:true});
    }
    copyTimers.set(button, setTimeout(() => {
      show("clipboard", label, accessibleLabel); delete button.dataset.state; button.removeAttribute("title");
    }, 2000));
  }
  return { render, copyText };
})();
