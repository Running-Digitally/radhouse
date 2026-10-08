"use strict";

// Presentation only. Each page owns its session check and private content.
(() => {
  const shell = document.querySelector(".shell, .admin-shell");
  const nav = document.getElementById("management-nav");
  const header = shell?.querySelector("header");
  const main = shell?.querySelector("main");
  if (!shell || !nav || !header || !main) { return; }

  const preferenceKey = "radhouse.navigation.collapsed";
  const mobile = window.matchMedia("(max-width: 760px)");
  let authenticated = false, drawerOpen = false, collapsed = false, focusedInPanel = null;
  try { collapsed = localStorage.getItem(preferenceKey) === "true"; } catch (_) { /* Optional presentation preference. */ }

  const panel = document.createElement("aside");
  panel.id = "navigation-panel"; panel.className = "navigation-panel"; panel.hidden = true;
  nav.before(panel); panel.append(nav);
  const heading = document.createElement("div"); heading.className = "navigation-heading";
  const label = document.createElement("span"); label.textContent = "Navigation";
  const closeButton = document.createElement("button");
  closeButton.type = "button"; closeButton.id = "navigation-close";
  closeButton.textContent = "×"; closeButton.setAttribute("aria-label", "Close menu");
  heading.append(label, closeButton); panel.prepend(heading);

  const toggle = document.createElement("button");
  toggle.type = "button"; toggle.id = "navigation-toggle"; toggle.hidden = true;
  toggle.setAttribute("aria-controls", panel.id);
  const icon = document.createElement("span"); icon.textContent = "☰"; icon.setAttribute("aria-hidden", "true");
  toggle.append(icon, document.createTextNode(" Menu")); header.prepend(toggle);
  const backdrop = document.createElement("button");
  backdrop.type = "button"; backdrop.className = "navigation-backdrop";
  backdrop.setAttribute("aria-label", "Close menu"); backdrop.tabIndex = -1; backdrop.hidden = true;
  shell.append(backdrop); shell.classList.add("navigation-shell");

  const inertBeforeOpen = new Map();
  function modalContent(disabled) {
    for (const node of [header, main]) {
      if (disabled) {
        if (!inertBeforeOpen.has(node)) { inertBeforeOpen.set(node, node.inert); }
        node.inert = true;
      } else if (inertBeforeOpen.has(node)) {
        node.inert = inertBeforeOpen.get(node); inertBeforeOpen.delete(node);
      }
    }
  }
  function visibleLinks() { return [...nav.querySelectorAll("a[href]")].filter(node => !node.hidden); }
  function render() {
    const open = authenticated && (mobile.matches ? drawerOpen : !collapsed);
    toggle.hidden = !authenticated; nav.hidden = !authenticated; panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    shell.classList.toggle("nav-active", authenticated);
    shell.classList.toggle("nav-collapsed", !open);
    shell.classList.toggle("nav-drawer-open", mobile.matches && open);
    closeButton.hidden = !mobile.matches;
    backdrop.hidden = !(mobile.matches && open);
    if (mobile.matches && open) {
      panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true");
      panel.setAttribute("aria-label", "Navigation");
    } else {
      panel.removeAttribute("role"); panel.removeAttribute("aria-modal"); panel.removeAttribute("aria-label");
    }
    modalContent(mobile.matches && open);
  }
  function close(returnFocus = true) {
    if (mobile.matches) { drawerOpen = false; }
    else {
      collapsed = true;
      try { localStorage.setItem(preferenceKey, "true"); } catch (_) { /* Optional presentation preference. */ }
    }
    render();
    if (returnFocus && authenticated) { toggle.focus(); }
  }
  toggle.addEventListener("click", () => {
    if (mobile.matches) {
      drawerOpen = !drawerOpen; render();
      if (drawerOpen) { (visibleLinks()[0] || closeButton).focus(); }
    } else {
      collapsed = !collapsed;
      try { localStorage.setItem(preferenceKey, String(collapsed)); } catch (_) { /* Optional presentation preference. */ }
      render();
    }
  });
  closeButton.addEventListener("click", () => close());
  backdrop.addEventListener("click", () => close());
  document.addEventListener("keydown", event => {
    if (!mobile.matches || !drawerOpen || !authenticated) { return; }
    if (event.key === "Escape") { event.preventDefault(); close(); return; }
    if (event.key !== "Tab") { return; }
    const items = [closeButton, ...visibleLinks()];
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
  nav.addEventListener("click", event => {
    if (mobile.matches && event.target.closest("a[href]")) { close(false); }
  });
  document.addEventListener("focusin", event => {
    focusedInPanel = panel.contains(event.target) ? event.target : null;
  });
  mobile.addEventListener("change", () => {
    const previousFocus = focusedInPanel;
    drawerOpen = false; render();
    if (previousFocus && authenticated) {
      if (panel.hidden) { toggle.focus(); }
      else if (!previousFocus.getClientRects().length) { (visibleLinks()[0] || toggle).focus(); }
    }
  });

  window.RadhouseNavigation = Object.freeze({
    update(session) {
      authenticated = Boolean(session);
      for (const link of nav.querySelectorAll("[data-management]")) { link.hidden = session?.management?.read !== true; }
      for (const link of nav.querySelectorAll("a[href]")) {
        if (new URL(link.href).pathname === location.pathname) { link.setAttribute("aria-current", "page"); }
        else { link.removeAttribute("aria-current"); }
      }
      if (!authenticated) { drawerOpen = false; }
      render();
    },
    close,
    isOpen: () => !panel.hidden,
  });
  render();
})();
