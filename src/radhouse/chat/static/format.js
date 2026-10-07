"use strict";
// A deliberately small DOM formatter: source HTML is always text, never markup.
window.RadhouseFormat = (() => {
  function inline(parent, text) {
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\s)]+\)|https?:\/\/[^\s<>]+)/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(offset, match.index)));
      const token = match[0]; let element;
      if (token.startsWith("`")) { element = document.createElement("code"); element.textContent = token.slice(1,-1); }
      else if (token.startsWith("**")) { element = document.createElement("strong"); element.textContent = token.slice(2,-2); }
      else if (token.startsWith("*")) { element = document.createElement("em"); element.textContent = token.slice(1,-1); }
      else {
        const link = token.match(/^\[([^\]]+)\]\((.+)\)$/), label = link ? link[1] : token;
        let url;
        try { url = new URL(link ? link[2] : token); } catch (_) {}
        if (url && ["https:","http:"].includes(url.protocol)) {
          element = document.createElement("a"); element.href = url.href; element.target = "_blank"; element.rel = "noopener noreferrer"; element.textContent = label;
        } else { element = document.createTextNode(token); }
      }
      parent.append(element); offset = match.index + token.length;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  function render(text) {
    const result = document.createDocumentFragment(), lines = text.split(/\r?\n/);
    for (let i=0; i<lines.length;) {
      if (!lines[i].trim()) { i++; continue; }
      const fence = lines[i].match(/^\s*```([^`]*)$/);
      if (fence) {
        const code = []; i++;
        while (i<lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
        if (i<lines.length) i++;
        const block = document.createElement("div"); block.className = "code-block";
        const header = document.createElement("div"); header.className = "code-header";
        const label = document.createElement("span"); label.textContent = fence[1].trim() || "Code";
        const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy code";
        copy.addEventListener("click",() => copyText(code.join("\n"),copy)); header.append(label,copy);
        const pre = document.createElement("pre"), content = document.createElement("code"); content.textContent = code.join("\n"); pre.append(content); block.append(header,pre); result.append(block); continue;
      }
      const heading = lines[i].match(/^#{1,6}\s+(.+)$/);
      if (heading) { const element = document.createElement("h3"); inline(element,heading[1]); result.append(element); i++; continue; }
      const list = lines[i].match(/^\s*(?:([-*+])|\d+[.)])\s+(.+)$/);
      if (list) {
        const ordered = !list[1], element = document.createElement(ordered ? "ol" : "ul");
        if (ordered) element.start = parseInt(lines[i].trim(),10);
        while (i<lines.length) {
          const item = lines[i].match(/^\s*(?:([-*+])|\d+[.)])\s+(.+)$/);
          if (!item || !!item[1] === ordered) break;
          const li = document.createElement("li"); inline(li,item[2]); element.append(li); i++;
        }
        result.append(element); continue;
      }
      const paragraph = [lines[i++]];
      while (i<lines.length && lines[i].trim() && !/^\s*(?:```|#{1,6}\s|[-*+]\s|\d+[.)]\s)/.test(lines[i])) paragraph.push(lines[i++]);
      const element = document.createElement("p");
      paragraph.forEach((line,index) => { if (index) element.append(document.createElement("br")); inline(element,line); }); result.append(element);
    }
    return result;
  }
  async function copyText(text, button) {
    try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; }
    catch (_) { button.textContent = "Copy unavailable"; button.title = "Select the text to copy it."; }
    setTimeout(() => { button.textContent = button.dataset.label || "Copy code"; },2000);
  }
  return {render,copyText};
})();
