"use strict";

// Original Radhouse glyphs: 24-unit grid, 1.7-unit round stroke, currentColor.
// Kept with the shared shell so every surface uses one family and no asset API.
window.RadhouseIcons = (() => {
  const paths = Object.freeze({
    chat: ["M7 4h10a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4h-6l-5 3v-3a3 3 0 0 1-3-3V8a4 4 0 0 1 4-4Z", "M8 9h8M8 13h5"],
    library: ["M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z", "M8 12h8M8 16h5"],
    browser: ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z", "M3 8h18M7 5.5h.01M10 5.5h.01"],
    settings: ["M4 7h16M4 17h16", "M9 4v6", "M15 14v6"],
    infrastructure: ["M5 3h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM5 13h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2Z", "M7 7h.01M7 17h.01M12 7h5M12 17h5"],
    clipboard: ["M8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2", "M9 3h6a1 1 0 0 1 1 1v3H8V4a1 1 0 0 1 1-1ZM8 12h8M8 16h5"],
    check: ["m5 12 4 4L19 6"],
    refresh: ["M20 7v5h-5", "M20 12a8 8 0 1 0-2.3 5.7"],
    signout: ["M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5", "M9 12h12m-5-5 5 5-5 5"],
    back: ["m13 5-7 7 7 7M6 12h14"],
    forward: ["m11 5 7 7-7 7M4 12h14"],
    close: ["m6 6 12 12M6 18 18 6"],
    menu: ["M4 6h16M4 12h16M4 18h16"],
    pointer: ["m5 3 14 9-7 2-3 7Z"],
    agent: ["m3.5 10 7.2-6.2q1.3-1.1 2.6 0l7.2 6.2v9q0 2-2 2h-13q-2 0-2-2Z", "M16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z", "M12 14h.01"],
    key: ["M14 10a5 5 0 1 0-4 4l4 4h3v3h4v-4l-7-7Z"],
    keyboard: ["M4 5h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z", "M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M10 13h.01M14 13h.01M18 13h.01M8 16h8"],
    eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z", "M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"],
    attach: ["m8 12 7-7a3 3 0 0 1 4 4L9 19a5 5 0 0 1-7-7l10-10", "m8 12 5-5"],
    send: ["m3 3 18 9-18 9 4-9ZM7 12h14"],
    warning: ["m12 3 10 18H2Z", "M12 9v5M12 17h.01"],
  });
  const bound = new WeakSet(), animations = new WeakMap();
  function play(target, frames, duration=360) {
    animations.get(target)?.cancel();
    const animation=target.animate(frames,{duration,easing:"cubic-bezier(.22,.8,.25,1)"});
    animations.set(target,animation);
  }
  function press(node) {
    if(node.disabled || matchMedia("(prefers-reduced-motion: reduce)").matches)return;
    const svg=node.querySelector(".rh-icon");if(!svg)return;
    const parts=svg.querySelectorAll("path"), name=svg.dataset.icon;
    if(name==="settings"){
      play(parts[1],[{transform:"translateX(0)"},{transform:"translateX(3px)",offset:.4},{transform:"translateX(0)"}]);
      play(parts[2],[{transform:"translateX(0)"},{transform:"translateX(-3px)",offset:.4},{transform:"translateX(0)"}]);
    }else if(name==="agent"){
      play(parts[1],[{transform:"scale(1)"},{transform:"scale(.8)",offset:.2},{transform:"scale(1.15)",offset:.6},{transform:"scale(1)"}],420);
      play(parts[2],[{opacity:1},{opacity:.4,offset:.2},{opacity:1}],420);
    }else if(name==="signout"){
      play(parts[1],[{transform:"translateX(0)"},{transform:"translateX(4px)",offset:.45},{transform:"translateX(0)"}]);
    }else if(name==="refresh"){
      play(svg,[{transform:"rotate(0)"},{transform:"rotate(390deg)",offset:.85},{transform:"rotate(360deg)"}],480);
    }else if(name==="back" || name==="forward"){
      const direction=name==="back"?-1:1;
      play(svg,[{transform:"translateX(0)"},{transform:`translateX(${direction*4}px)`,offset:.3},{transform:`translateX(${-direction}px)`,offset:.7},{transform:"translateX(0)"}]);
    }else if(name==="library" || name==="clipboard"){
      play(svg,[{transform:"translateY(0)"},{transform:"translateY(-3px) rotate(-4deg)",offset:.35},{transform:"translateY(1px)",offset:.7},{transform:"translateY(0)"}]);
    }else if(name==="close"){
      play(svg,[{transform:"scale(1) rotate(0)"},{transform:"scale(.75) rotate(12deg)",offset:.25},{transform:"scale(1) rotate(0)"}],280);
    }else{
      play(svg,[{transform:"scale(1)"},{transform:"scale(.85)",offset:.2},{transform:"scale(1.08)",offset:.65},{transform:"scale(1)"}]);
    }
  }
  function create(name) {
    if (!Object.hasOwn(paths, name)) throw new Error("unknown_radhouse_icon");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [key, value] of Object.entries({viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": "1.7", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false"})) svg.setAttribute(key, value);
    svg.classList.add("rh-icon"); svg.dataset.icon = name;
    for (const d of paths[name]) {
      const path = document.createElementNS(svg.namespaceURI, "path"); path.setAttribute("d", d); svg.append(path);
    }
    return svg;
  }
  function decorate(node, name, label = node.textContent.trim(), {compact = false} = {}) {
    const text = document.createElement("span"); text.className = "rh-action-label"; text.textContent = label;
    node.replaceChildren(create(name), text); node.classList.add("rh-action");
    node.dataset.icon = name; node.classList.toggle("rh-action--compact", compact);
    node.setAttribute("aria-label", label);
    if (compact) node.dataset.tooltip = label;
    else delete node.dataset.tooltip;
    if(!bound.has(node)){
      node.addEventListener("click",()=>press(node),{capture:true});bound.add(node);
    }
    if(name==="check" && !matchMedia("(prefers-reduced-motion: reduce)").matches){
      const path=node.querySelector(".rh-icon path");
      play(path,[{strokeDasharray:"30",strokeDashoffset:"30"},{strokeDasharray:"30",strokeDashoffset:"0"}],300);
    }
    return node;
  }
  function busy(node, pending) {
    node.setAttribute("aria-busy", String(pending));
    if (pending) node.dataset.state = "pending";
    else delete node.dataset.state;
  }
  return Object.freeze({create, decorate, busy, press, names: Object.freeze(Object.keys(paths))});
})();

// Presentation only. Each page owns its session check and private content.
(() => {
  const icons = window.RadhouseIcons;
  for (const [id, name] of [["logout", "signout"], ["library-refresh", "refresh"], ["refresh", "refresh"]]) {
    const node = document.getElementById(id); if (node) icons.decorate(node, name);
  }
  const attach = document.getElementById("attach"); if (attach) icons.decorate(attach, "attach", "Attach files");
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
  icons.decorate(closeButton, "close", "Close menu", {compact: true});
  heading.append(label, closeButton); panel.prepend(heading);

  const toggle = document.createElement("button");
  toggle.type = "button"; toggle.id = "navigation-toggle"; toggle.hidden = true;
  toggle.setAttribute("aria-controls", panel.id);
  icons.decorate(toggle, "menu", "Open menu", {compact: true}); header.prepend(toggle);
  const destinations = {"/": "chat", "/library": "library", "/browser": "browser", "/settings": "settings", "/infrastructure": "infrastructure"};
  for (const link of nav.querySelectorAll("a[href]")) {
    const name = destinations[new URL(link.href).pathname]; if (name) icons.decorate(link, name);
  }
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
    const toggleLabel = open ? "Close menu" : "Open menu";
    toggle.setAttribute("aria-label", toggleLabel); toggle.dataset.tooltip = toggleLabel;
    toggle.querySelector(".rh-action-label").textContent = toggleLabel;
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
