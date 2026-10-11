/** Restore local reading state without retaining private data across sessions. */
export function preserveView(page: HTMLElement): () => void {
  const identity = page.dataset.identity;
  const focused = (page.getRootNode() as Document | ShadowRoot).activeElement;
  const controls = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLElement>(
    "button, input, textarea, select, a, summary, [tabindex]",
  ));
  const key = (node: HTMLElement): string => {
    const scope = node.closest<HTMLElement>("[data-task-id], [data-conversation-id], [data-publication-id], [data-project-id]");
    return JSON.stringify([
      scope?.dataset.taskId ?? scope?.dataset.conversationId ?? scope?.dataset.publicationId ?? scope?.dataset.projectId ?? "page",
      node.tagName, node.getAttribute("name"), node.getAttribute("role"),
      node.getAttribute("aria-label"), node.getAttribute("href"),
      node.matches("input, select, textarea") ? "" : node.textContent,
    ]);
  };
  const focusKey = focused instanceof HTMLElement && page.contains(focused) ? key(focused) : null;
  const focusIndex = focusKey === null ? -1 : controls(page).filter(node => key(node) === focusKey).indexOf(focused as HTMLElement);
  const selection = focused instanceof HTMLTextAreaElement || focused instanceof HTMLInputElement
    ? [focused.selectionStart, focused.selectionEnd] : null;
  const details = Array.from(page.querySelectorAll<HTMLDetailsElement>("details[data-view-key]"))
    .map(node => ({ key: node.dataset.viewKey, open: node.open }));
  const viewers = Array.from(page.querySelectorAll<HTMLElement>(".result-viewer[data-view-key]"))
    .map(node => ({ key: node.dataset.viewKey, mode: node.dataset.mode,
      scroll: Array.from(node.querySelectorAll<HTMLElement>('[role="tabpanel"]')).map(panel => [panel.scrollTop, panel.scrollLeft]) }));
  const scroll = [window.scrollX, window.scrollY] as const;
  return () => {
    if (!identity || page.dataset.identity !== identity) return;
    const keyed = Array.from(page.querySelectorAll<HTMLElement>("[data-view-key]"));
    for (const saved of details) {
      const next = keyed.find(node => node.dataset.viewKey === saved.key);
      if (next instanceof HTMLDetailsElement) next.open = saved.open;
    }
    for (const saved of viewers) {
      const next = keyed.find(node => node.dataset.viewKey === saved.key);
      if (!next) continue;
      if (saved.mode === "source") next.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1]?.click();
      next.querySelectorAll<HTMLElement>('[role="tabpanel"]').forEach((panel, index) => {
        const position = saved.scroll[index];
        if (position) { panel.scrollTop = position[0] ?? 0; panel.scrollLeft = position[1] ?? 0; }
      });
    }
    const next = focusKey === null ? null : controls(page).filter(node => key(node) === focusKey)[focusIndex];
    next?.focus({ preventScroll: true });
    if ((next instanceof HTMLTextAreaElement || next instanceof HTMLInputElement)
        && selection?.[0] != null && selection[1] != null) next.setSelectionRange(selection[0], selection[1]);
    window.scrollTo({ left: scroll[0], top: scroll[1], behavior: "instant" });
  };
}
