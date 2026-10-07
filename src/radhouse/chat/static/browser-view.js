"use strict";
(() => {
  const labels = {starting: "Opening the assistant’s browser…", live: "Live browser",
    idle: "Browser is idle", unavailable: "Browser view is unavailable"};
  const identifier = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
  const maxFrame = 512 * 1024;

  class BrowserView {
    constructor(container) {
      this.container = container;
      this.container.classList.add("browser-view");
      this.container.hidden = true;
      this.epoch = 0; this.open = true; this.active = false;
      this.run = null; this.generation = null; this.timer = null;
      this.controller = null; this.frameUrl = null; this.pendingUrls = new Set();
      const header = document.createElement("div"); header.className = "browser-view-header";
      const heading = document.createElement("h2"); heading.textContent = "Assistant browser";
      this.toggle = document.createElement("button"); this.toggle.type = "button";
      this.toggle.textContent = "Hide browser"; this.toggle.setAttribute("aria-expanded", "true");
      header.append(heading, this.toggle);
      this.body = document.createElement("div"); this.body.className = "browser-view-body";
      this.status = document.createElement("p"); this.status.className = "browser-view-status";
      this.status.setAttribute("role", "status"); this.status.setAttribute("aria-live", "polite");
      this.site = document.createElement("p"); this.site.className = "browser-view-site";
      this.viewport = document.createElement("div"); this.viewport.className = "browser-view-viewport";
      this.image = document.createElement("img"); this.image.alt = "Live page in the assistant’s browser";
      this.image.hidden = true; this.image.draggable = false;
      this.viewport.hidden = true;
      this.viewport.append(this.image); this.body.append(this.status, this.site, this.viewport);
      this.container.replaceChildren(header, this.body);
      this.toggle.addEventListener("click", () => {
        this.open = !this.open; this.body.hidden = !this.open;
        this.toggle.textContent = this.open ? "Hide browser" : "Show browser";
        this.toggle.setAttribute("aria-expanded", String(this.open));
        this._cancel();
        if (this.open) this._schedule(0);
      });
      this.visibility = () => {
        this._cancel();
        if (!document.hidden) this._schedule(0);
      };
      document.addEventListener("visibilitychange", this.visibility);
    }

    _label(text) {
      if (this.status.textContent !== text) this.status.textContent = text;
    }

    update(value) {
      const state = value && Object.hasOwn(labels, value.state) ? value.state : "unavailable";
      const run = typeof value?.run_id === "string" && identifier.test(value.run_id) ? value.run_id : null;
      const generation = typeof value?.generation === "string" && identifier.test(value.generation) ? value.generation : null;
      const changed = run !== this.run || generation !== this.generation;
      if (changed) {
        this._cancel(); this._clearImage();
        if (run !== this.run) {
          this.open = true; this.body.hidden = false;
          this.toggle.textContent = "Hide browser"; this.toggle.setAttribute("aria-expanded", "true");
        }
      }
      this.run = run; this.generation = generation;
      this.active = state === "live" && run !== null && generation !== null;
      this.container.hidden = state === "idle" && run === null;
      this._label(labels[state]);
      this.site.textContent = typeof value?.url === "string" ? value.url : "";
      this.site.hidden = !this.site.textContent;
      if (!this.active) { this._cancel(); this._clearImage(); }
      else if (!this.controller && this.timer === null) this._schedule(0);
    }

    _cancel() {
      this.epoch++;
      clearTimeout(this.timer); this.timer = null;
      this.controller?.abort(); this.controller = null;
    }

    _clearImage() {
      this.image.hidden = true; this.viewport.hidden = true; this.image.removeAttribute("src");
      if (this.frameUrl) URL.revokeObjectURL(this.frameUrl);
      this.frameUrl = null;
      for (const url of this.pendingUrls) URL.revokeObjectURL(url);
      this.pendingUrls.clear();
    }

    _schedule(delay) {
      if (!this.active || !this.open || document.hidden || this.container.hidden || this.timer !== null) return;
      this.timer = setTimeout(() => { this.timer = null; void this._poll(); }, delay);
    }

    async _poll() {
      if (!this.active || !this.open || document.hidden || this.container.hidden) return;
      const epoch = this.epoch, run = this.run, generation = this.generation;
      const controller = new AbortController(); this.controller = controller;
      const timeout = setTimeout(() => controller.abort(), 5000);
      let objectUrl = null;
      try {
        const response = await fetch(`/chat/browser/frame?run_id=${encodeURIComponent(run)}`,
          {credentials: "same-origin", cache: "no-store", signal: controller.signal});
        if (epoch !== this.epoch) return;
        if (response.status === 401 || response.status === 403) {
          this.stop(); this.container.dispatchEvent(new CustomEvent("browser-auth-required", {bubbles: true})); return;
        }
        if (!response.ok) throw new Error("browser_unavailable");
        if (response.headers.get("content-type")?.split(";")[0] !== "image/jpeg"
            || response.headers.get("x-radhouse-browser-generation") !== generation) throw new Error("browser_unavailable");
        const blob = await response.blob();
        if (epoch !== this.epoch) return;
        if (blob.size > maxFrame || blob.size < 4) throw new Error("browser_unavailable");
        objectUrl = URL.createObjectURL(blob); this.pendingUrls.add(objectUrl);
        const image = new Image(); image.src = objectUrl;
        await image.decode();
        if (epoch !== this.epoch || !this.active || !this.open || document.hidden
            || run !== this.run || generation !== this.generation) return;
        if (this.frameUrl) URL.revokeObjectURL(this.frameUrl);
        this.frameUrl = objectUrl; this.pendingUrls.delete(objectUrl); objectUrl = null;
        this.image.src = this.frameUrl; this.image.hidden = false; this.viewport.hidden = false;
        this._label(labels.live);
      } catch (_) {
        if (epoch === this.epoch) { this._clearImage(); this._label(labels.unavailable); }
      } finally {
        clearTimeout(timeout);
        if (objectUrl) { URL.revokeObjectURL(objectUrl); this.pendingUrls.delete(objectUrl); }
        if (this.controller === controller) this.controller = null;
        if (epoch === this.epoch) this._schedule(500);
      }
    }

    stop() {
      this._cancel(); this._clearImage();
      this.active = false; this.run = null; this.generation = null;
      this.site.textContent = ""; this._label(""); this.container.hidden = true;
    }

    destroy() { this.stop(); document.removeEventListener("visibilitychange", this.visibility); }
  }

  window.BrowserView = BrowserView;
})();
