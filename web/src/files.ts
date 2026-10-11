import { ApiError } from "./api.js";

export interface AttachedFile {
  name: string;
  content: string;
  media_type: string;
  encoding: "utf-8" | "base64";
  sha256: string | null;
}

const TEXT_TYPES = new Map([
  [".txt", "text/plain"], [".log", "text/plain"],
  [".md", "text/markdown"], [".markdown", "text/markdown"],
  [".csv", "text/csv"], [".json", "application/json"],
]);
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

function extension(name: string): string {
  const index = name.lastIndexOf(".");
  return index < 0 ? "" : name.slice(index).toLowerCase();
}

function base64(data: Uint8Array): string {
  let value = "";
  for (let offset = 0; offset < data.length; offset += 0x8000) {
    value += String.fromCharCode(...data.subarray(offset, offset + 0x8000));
  }
  return btoa(value);
}

function hex(data: ArrayBuffer): string {
  return Array.from(new Uint8Array(data), value => value.toString(16).padStart(2, "0")).join("");
}

export async function loadAttachments(files: File[]): Promise<AttachedFile[]> {
  if (files.length > 4) throw new ApiError("invalid_input_files", 422);
  let textBytes = 0;
  let imageBytes = 0;
  const result: AttachedFile[] = [];
  for (const file of files) {
    if (!file.name || file.name.length > 200 || /[\\/\0\r\n]/.test(file.name)) {
      throw new ApiError("invalid_input_files", 422);
    }
    if (file.size > (IMAGE_TYPES.has(file.type) ? 4 * 1024 * 1024 : 65536)) {
      throw new ApiError("invalid_input_files", 422);
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (IMAGE_TYPES.has(file.type)) {
      imageBytes += bytes.byteLength;
      if (bytes.byteLength > 4 * 1024 * 1024 || imageBytes > 8 * 1024 * 1024) {
        throw new ApiError("invalid_input_files", 422);
      }
      const digest = hex(await crypto.subtle.digest("SHA-256", bytes));
      result.push({
        name: file.name, content: base64(bytes), media_type: file.type,
        encoding: "base64", sha256: digest,
      });
      continue;
    }
    const mediaType = TEXT_TYPES.get(extension(file.name));
    if (!mediaType) throw new ApiError("invalid_input_files", 422);
    textBytes += bytes.byteLength;
    if (textBytes > 65536) throw new ApiError("invalid_input_files", 422);
    let content: string;
    try { content = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
    catch { throw new ApiError("invalid_input_files", 422); }
    if (content.includes("\0")) throw new ApiError("invalid_input_files", 422);
    result.push({
      name: file.name, content, media_type: mediaType,
      encoding: "utf-8", sha256: null,
    });
  }
  return result;
}

export async function appendAttachments(existing: AttachedFile[], files: File[]): Promise<AttachedFile[]> {
  const combined = [...existing];
  for (const file of await loadAttachments(files)) {
    if (!combined.some(item => item.name === file.name && item.media_type === file.media_type
        && item.encoding === file.encoding && item.content === file.content)) combined.push(file);
  }
  const textBytes = combined.filter(file => file.encoding === "utf-8")
    .reduce((total, file) => total + new TextEncoder().encode(file.content).length, 0);
  const imageBytes = combined.filter(file => file.encoding === "base64")
    .reduce((total, file) => total + file.content.length * 3 / 4 - (file.content.match(/=*$/)?.[0].length ?? 0), 0);
  if (combined.length > 4 || textBytes > 65536 || imageBytes > 8 * 1024 * 1024) {
    throw new ApiError("invalid_input_files", 422);
  }
  return combined;
}

/** One attachment interaction for both assignment and conversation composers. */
export function attachmentPicker(target: HTMLElement, draft: { files: AttachedFile[] },
  run: (work: () => Promise<void>) => Promise<void>, filePicker: (open: boolean) => void): HTMLElement {
  const wrapper = document.createElement("div"); wrapper.className = "attachment-picker";
  const label = document.createElement("label"); label.className = "field";
  const caption = document.createElement("span"); caption.className = "field__label";
  caption.textContent = "Reference files · paste, drop or add text/CSV/images";
  const input = document.createElement("input"); input.type = "file"; input.multiple = true;
  input.className = "field__control";
  input.accept = ".txt,.md,.markdown,.csv,.json,.log,.png,.jpg,.jpeg,.webp";
  label.append(caption, input);
  const limits = document.createElement("p"); limits.className = "muted attachment-limits";
  limits.textContent = "Up to 4 files. Text: 64 KiB total. Images: 4 MiB each, 8 MiB total. New selections add to this list.";
  const list = document.createElement("ul"); list.className = "attachment-list";
  list.setAttribute("aria-label", "Selected attachments");
  const render = () => {
    list.replaceChildren();
    draft.files.forEach((file, index) => {
      const item = document.createElement("li");
      const name = document.createElement("span"); name.textContent = file.name;
      const remove = document.createElement("button"); remove.type = "button";
      remove.className = "button button--secondary"; remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.onclick = () => void run(async () => { draft.files = draft.files.filter((_, i) => i !== index); render(); });
      item.append(name, remove); list.append(item);
    });
  };
  const add = (selected: File[]) => run(async () => {
    draft.files = await appendAttachments(draft.files, selected); render();
  });
  input.onclick = () => filePicker(true);
  input.addEventListener("cancel", () => filePicker(false));
  input.onchange = () => {
    filePicker(false);
    const selected = Array.from(input.files ?? []);
    input.value = "";
    void add(selected);
  };
  acceptPastedOrDroppedFiles(target, add);
  render(); wrapper.append(label, limits, list);
  return wrapper;
}

export function acceptPastedOrDroppedFiles(
  target: HTMLElement,
  load: (files: File[]) => Promise<void>,
): void {
  target.addEventListener("paste", event => {
    const files = Array.from((event as ClipboardEvent).clipboardData?.files ?? []);
    if (!files.length) return;
    event.preventDefault();
    void load(files);
  });
  target.addEventListener("dragover", event => {
    if (Array.from((event as DragEvent).dataTransfer?.types ?? []).includes("Files")) {
      event.preventDefault();
    }
  });
  target.addEventListener("drop", event => {
    const files = Array.from((event as DragEvent).dataTransfer?.files ?? []);
    if (!files.length) return;
    event.preventDefault();
    void load(files);
  });
}
