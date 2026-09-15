import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const markdown = new MarkdownIt({ html: false, linkify: true, typographer: false });
let viewerSequence = 0;

function button(label: string, selected: boolean, id: string, controls: string): HTMLButtonElement {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "result-viewer__tab";
  node.textContent = label;
  node.setAttribute("aria-selected", String(selected));
  node.setAttribute("role", "tab");
  node.id = id;
  node.setAttribute("aria-controls", controls);
  node.tabIndex = selected ? 0 : -1;
  return node;
}

/** Render locally. The exact source remains the review, digest and download authority. */
export function resultViewer(source: string): HTMLElement {
  const viewer = document.createElement("section");
  viewer.className = "result-viewer";
  const tabs = document.createElement("div");
  tabs.className = "result-viewer__tabs";
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Result view");
  const id = ++viewerSequence;
  const previewId = `result-preview-${id}`;
  const sourceId = `result-source-${id}`;
  const previewButton = button("Preview", true, `result-preview-tab-${id}`, previewId);
  const sourceButton = button("Source", false, `result-source-tab-${id}`, sourceId);
  const preview = document.createElement("div");
  preview.className = "result-viewer__preview";
  preview.setAttribute("role", "tabpanel");
  preview.id = previewId;
  preview.setAttribute("aria-labelledby", previewButton.id);
  preview.tabIndex = 0;
  const raw = document.createElement("pre");
  raw.className = "result result-viewer__source";
  raw.setAttribute("role", "tabpanel");
  raw.id = sourceId;
  raw.setAttribute("aria-labelledby", sourceButton.id);
  raw.tabIndex = 0;
  raw.hidden = true;
  raw.textContent = source;

  const sanitized = DOMPurify.sanitize(markdown.render(source), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "form", "input", "button", "iframe", "object", "embed", "img", "picture", "audio", "video", "source"],
    FORBID_ATTR: ["style", "srcset"],
  });
  preview.innerHTML = sanitized;
  for (const link of preview.querySelectorAll<HTMLAnchorElement>("a")) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }

  const show = (mode: "preview" | "source"): void => {
    const previewSelected = mode === "preview";
    preview.hidden = !previewSelected;
    raw.hidden = previewSelected;
    previewButton.setAttribute("aria-selected", String(previewSelected));
    sourceButton.setAttribute("aria-selected", String(!previewSelected));
    previewButton.tabIndex = previewSelected ? 0 : -1;
    sourceButton.tabIndex = previewSelected ? -1 : 0;
  };
  previewButton.onclick = () => show("preview");
  sourceButton.onclick = () => show("source");
  for (const [index, tab] of [previewButton, sourceButton].entries()) {
    tab.onkeydown = (event) => {
      const target = event.key === "Home" ? 0 : event.key === "End" ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp" ? (index + 1) % 2
        : event.key === "ArrowRight" || event.key === "ArrowDown" ? (index + 1) % 2 : null;
      if (target === null) return;
      event.preventDefault();
      show(target === 0 ? "preview" : "source");
      [previewButton, sourceButton][target]?.focus();
    };
  }
  tabs.append(previewButton, sourceButton);
  viewer.append(tabs, preview, raw);
  return viewer;
}
