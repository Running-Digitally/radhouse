import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

const markdown = new MarkdownIt({ html: false, linkify: true, typographer: false });

function button(label: string, selected: boolean): HTMLButtonElement {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "result-viewer__tab";
  node.textContent = label;
  node.setAttribute("aria-selected", String(selected));
  node.setAttribute("role", "tab");
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
  const previewButton = button("Preview", true);
  const sourceButton = button("Source", false);
  const preview = document.createElement("div");
  preview.className = "result-viewer__preview";
  preview.setAttribute("role", "tabpanel");
  const raw = document.createElement("pre");
  raw.className = "result result-viewer__source";
  raw.setAttribute("role", "tabpanel");
  raw.hidden = true;
  raw.textContent = source;

  const sanitized = DOMPurify.sanitize(markdown.render(source), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "form", "input", "button", "iframe", "object", "embed"],
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
  };
  previewButton.onclick = () => show("preview");
  sourceButton.onclick = () => show("source");
  tabs.append(previewButton, sourceButton);
  viewer.append(tabs, preview, raw);
  return viewer;
}
