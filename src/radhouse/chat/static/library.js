"use strict";
(() => {
  class Library {
    constructor({request, card, openMessage}) {
      this.request = request; this.card = card; this.openMessage = openMessage;
      this.epoch = 0; this.controller = null; this.cursor = null; this.timer = null;
      this.files = document.getElementById("library-files");
      this.status = document.getElementById("library-status");
      this.search = document.getElementById("library-search");
      this.source = document.getElementById("library-source");
      this.more = document.getElementById("library-more");
      this.refresh = document.getElementById("library-refresh");
      this.search.addEventListener("input", () => {
        this.cancel(); this.more.hidden = true;
        this.timer = setTimeout(() => { this.timer = null; void this.load(); }, 250);
      });
      this.source.addEventListener("change", () => { void this.load(); });
      this.refresh.addEventListener("click", () => { void this.load(); });
      this.more.addEventListener("click", () => { void this.load(true); });
    }

    cancel() {
      this.epoch++; this.controller?.abort(); this.controller = null;
      clearTimeout(this.timer); this.timer = null;
    }

    clear() {
      this.cancel(); this.cursor = null; this.files.replaceChildren();
      this.status.textContent = ""; this.search.value = ""; this.source.value = "all";
      this.more.hidden = true; this.more.disabled = false; this.refresh.disabled = false;
    }

    async load(append = false) {
      if (append && !this.cursor) return;
      this.cancel(); const epoch = this.epoch;
      const controller = new AbortController(); this.controller = controller;
      const timeout = setTimeout(() => controller.abort(), 10000);
      const params = new URLSearchParams({query: this.search.value, source: this.source.value});
      if (append) params.set("before", this.cursor);
      if (!append) { this.files.replaceChildren(); this.cursor = null; this.more.hidden = true; }
      this.refresh.disabled = true; this.more.disabled = true;
      window.RadhouseIcons?.busy(this.refresh,true);
      this.status.textContent = "Loading files…";
      try {
        const page = await this.request("/chat/library?" + params, undefined, false, controller.signal);
        if (epoch !== this.epoch) return;
        for (const file of page.files) this.files.append(this.render(file));
        this.cursor = page.next_cursor; this.more.hidden = !this.cursor;
        this.status.textContent = this.files.children.length ? "" :
          (this.search.value ? "No files match this search." : this.source.value === "assistant" ?
            "Files shared by Radhouse will appear here." : "Files you upload will appear here.");
      } catch {
        if (epoch !== this.epoch) return;
        this.status.textContent = "Files couldn’t be loaded. Try Refresh.";
      } finally {
        clearTimeout(timeout);
        if (epoch === this.epoch) {
          this.controller = null; this.refresh.disabled = false; this.more.disabled = false;
          window.RadhouseIcons?.busy(this.refresh,false);
        }
      }
    }

    render(file) {
      const card = this.card(file, file.download_url, false);
      card.classList.add("library-file");
      const detail = document.createElement("div"); detail.className = "library-file-meta";
      const source = document.createElement("span"); source.textContent = file.source === "assistant" ? "Shared by Radhouse" : "Uploaded by you";
      detail.append(source);
      if (file.request_id) {
        const link = document.createElement("a"); link.href = "/?message=" + encodeURIComponent(file.request_id);
        link.textContent = "Open in Chat";
        link.addEventListener("click", event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault(); void this.openMessage(file.request_id);
        });
        detail.append(link);
      }
      card.append(detail); return card;
    }
  }
  window.RadhouseLibrary = Library;
})();
