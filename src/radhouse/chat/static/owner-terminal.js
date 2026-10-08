"use strict";
(() => {
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const bytesTo64 = data => {
    let text = "";
    for (const byte of data) text += String.fromCharCode(byte);
    return btoa(text);
  };
  const from64 = text => Uint8Array.from(atob(text), byte => byte.charCodeAt(0));
  const action = (button, icon, label) => {
    if (window.RadhouseIcons) window.RadhouseIcons.decorate(button, icon, label);
    else button.textContent = label;
  };

  class OwnerTerminalView {
    constructor(root, {request, tab, onAuthRequired = null, onContextChange = null}) {
      this.root = root; this.request = request; this.tab = tab;
      this.onAuthRequired = onAuthRequired; this.onContextChange = onContextChange;
      this.binding = null; this.visible = false; this.epoch = 0; this.cursor = 0;
      this.term = null; this.fit = null; this.controller = null; this.timer = null;
      this.sequence = 0; this.writing = Promise.resolve(); this.inputUnconfirmed = false;
      this.actionPending = false; this.contextWanted = false; this.state = "closed";
      this.root.classList.add("owner-terminal");
      const header = make("div", null, "owner-terminal-header");
      header.append(make("h2", "Agent VM terminal"));
      this.openButton = make("button", "Open terminal"); this.openButton.type = "button";
      this.closeButton = make("button", "Close terminal"); this.closeButton.type = "button";
      action(this.openButton, "terminal", "Open terminal");
      action(this.closeButton, "close", "Close terminal");
      this.closeButton.hidden = true; header.append(this.openButton, this.closeButton);
      this.status = make("p", "Open a terminal when you need it.", "owner-terminal-status");
      this.status.setAttribute("role", "status"); this.status.setAttribute("aria-live", "polite");
      this.viewport = make("div", null, "owner-terminal-viewport"); this.viewport.hidden = true;
      this.placeholder = make("div", null, "owner-terminal-placeholder");
      this.placeholder.append(make("span", ">_", "owner-terminal-symbol"),
        make("p", "Your terminal on the assistant’s VM."),
        make("p", "Opening this page keeps the terminal asleep. Open terminal to start."));
      const contextLabel = make("label", null, "owner-terminal-context");
      this.checkbox = make("input"); this.checkbox.type = "checkbox";
      const contextText = make("span", "Include terminal context in my next message");
      if (window.RadhouseIcons) window.RadhouseIcons.decorate(contextText, "terminal-context", contextText.textContent);
      contextLabel.append(this.checkbox, contextText);
      const explanation = make("p", "Only selected text, or the last 20 visible lines, is shared when you send a message.", "owner-terminal-context-help");
      this.root.replaceChildren(header, this.status, this.placeholder, this.viewport, contextLabel, explanation);
      this.openButton.addEventListener("click", () => { void this.open(); });
      this.closeButton.addEventListener("click", () => { void this.close(); });
      this.checkbox.addEventListener("change", () => { this.contextEnabled = this.checkbox.checked; });
      this.observer = new ResizeObserver(() => {
        if (this.visible && this.term && this.binding && !this.actionPending) {
          this.fit.fit(); clearTimeout(this.resizeTimer);
          this.resizeTimer = setTimeout(() => { void this._resize(); }, 150);
        }
      });
      this.observer.observe(this.viewport);
      this.visibility = () => {
        clearTimeout(this.keepTimer);
        if (document.hidden) this._cancel();
        else if (this.visible) this._schedule();
        else this._keepAlive();
      };
      this.pagehide = () => { clearTimeout(this.keepTimer); this._cancel(); };
      document.addEventListener("visibilitychange", this.visibility);
      window.addEventListener("pagehide", this.pagehide);
      window.addEventListener("pageshow", this.visibility);
    }

    get available() { return !!this.binding && this.state !== "closed"; }
    get contextEnabled() { return this.contextWanted; }
    set contextEnabled(value) {
      this.contextWanted = value === true; this.checkbox.checked = this.contextWanted;
      this.onContextChange?.(this.contextWanted);
    }
    _tab() { return typeof this.tab === "function" ? this.tab() : this.tab; }
    _bound(values = {}) { return {...this.binding, ...values}; }
    async _request(operation, values = {}, signal) {
      return this.request("/chat/terminal/" + operation, {tab_id: this._tab(), ...values}, "POST", signal);
    }
    _binding(value) {
      return value.terminal_id ? {terminal_id: value.terminal_id, generation: value.generation,
        attach_epoch: value.attach_epoch} : null;
    }
    _apply(value) {
      const binding = this._binding(value);
      const changed = this.binding?.generation !== binding?.generation;
      this.binding = binding; this.state = value.state; this.sequence = value.last_sequence;
      if (changed) { this.cursor = 0; this.term?.reset(); }
      this.closeButton.hidden = !this.available;
      action(this.openButton, "terminal", this.available ? "Reconnect terminal" : "Open terminal");
      this.viewport.hidden = !this.available; this.placeholder.hidden = this.available;
      if (this.available) this._mount();
      this.status.textContent = this.state === "open" ? "Terminal ready. Commands run as the assistant VM’s unprivileged user."
        : this.state === "exited" ? "The shell has exited. Close terminal to finish." : "Open a terminal when you need it.";
    }
    _mount() {
      if (!this.term) {
        if (!window.Terminal || !window.FitAddon?.FitAddon) throw new Error("terminal_renderer_unavailable");
        this.term = new window.Terminal({cursorBlink: true, scrollback: 2000, allowProposedApi: false,
          fontSize: 14, convertEol: false, theme: {background: "#17231e", foreground: "#f4f3ec"}});
        this.fit = new window.FitAddon.FitAddon(); this.term.loadAddon(this.fit); this.term.open(this.viewport);
        this.term.onData(data => { this._input(data); });
      }
      if (this.visible) this.fit.fit();
    }
    _cancel() {
      this.epoch++; this.controller?.abort(); this.controller = null;
      clearTimeout(this.timer); this.timer = null; clearTimeout(this.resizeTimer);
    }
    _error(error, action = false) {
      if (error.status === 401) { this.dispose(); this.onAuthRequired?.(); return; }
      if (action) this.inputUnconfirmed = true;
      this.status.textContent = action
        ? "Input was not confirmed. Check the terminal, then reconnect before typing again."
        : "Terminal connection is unavailable. Reconnect to try again.";
    }
    async show() {
      if (this.visible) return;
      this._cancel(); clearTimeout(this.keepTimer); this.visible = true; const epoch = this.epoch;
      this.status.textContent = "Checking terminal…";
      try {
        const value = await this._request("status");
        if (epoch !== this.epoch) return;
        this._apply(value); this._schedule();
      } catch (error) { if (epoch === this.epoch) this._error(error); }
    }
    hide() {
      if (!this.visible) return;
      this.visible = false; this._cancel(); this._keepAlive();
    }
    _keepAlive() {
      clearTimeout(this.keepTimer);
      if (this.visible || document.hidden || !this.available) return;
      const epoch = this.epoch;
      this.keepTimer = setTimeout(async () => {
        try {
          const value = await this._request("status");
          if (epoch !== this.epoch || this.visible) return;
          this.state = value.state;
          if (value.state === "closed") this.binding = null;
        } catch (error) {
          if (epoch === this.epoch && error.status === 401) this._error(error);
          return;
        }
        if (epoch === this.epoch) this._keepAlive();
      }, 30000);
    }
    async open() {
      if (this.actionPending) return;
      this._cancel(); this.actionPending = true; this.openButton.disabled = true;
      const action = Symbol("terminal-open"); this.actionToken = action;
      const epoch = this.epoch; this.status.textContent = "Opening terminal…";
      try {
        const value = await this._request("open", {request_id: crypto.randomUUID(),
          cols: this.term?.cols || 100, rows: this.term?.rows || 28});
        if (epoch !== this.epoch) return;
        this.inputUnconfirmed = false; this._apply(value); this.term?.focus(); this._schedule();
      } catch (error) { if (epoch === this.epoch) this._error(error); }
      finally {
        if (this.actionToken === action) { this.actionPending = false; this.actionToken = null; this.openButton.disabled = false; }
      }
    }
    async close() {
      if (!this.binding || this.actionPending) return;
      this._cancel(); this.actionPending = true; this.closeButton.disabled = true;
      const action = Symbol("terminal-close"); this.actionToken = action;
      const epoch = this.epoch;
      try {
        const value = await this._request("close", this._bound());
        if (epoch !== this.epoch) return;
        this._apply(value); this.binding = null; this.term?.dispose(); this.term = null; this.fit = null;
        this.viewport.replaceChildren(); this.contextEnabled = false; this.cursor = 0;
      } catch (error) { if (epoch === this.epoch) this._error(error, true); }
      finally {
        if (this.actionToken === action) { this.actionPending = false; this.actionToken = null; this.closeButton.disabled = false; }
      }
    }
    _schedule(delay = 0) {
      if (!this.visible || document.hidden || !this.available || this.timer !== null || this.controller) return;
      this.timer = setTimeout(() => { this.timer = null; void this._poll(); }, delay);
    }
    async _poll() {
      if (!this.visible || document.hidden || !this.available) return;
      const epoch = this.epoch, controller = new AbortController(); this.controller = controller;
      try {
        const value = await this._request("output", this._bound({cursor: this.cursor, wait_ms: 15000}), controller.signal);
        if (epoch !== this.epoch) return;
        if (value.truncated) this.term.write("\r\n[Earlier output is no longer available.]\r\n");
        await new Promise(resolve => this.term.write(from64(value.data_b64), resolve));
        if (epoch !== this.epoch) return;
        this.cursor = value.next_cursor; this.state = value.state;
        if (value.state === "exited") this.status.textContent = "The shell has exited. Close terminal to finish.";
      } catch (error) {
        if (epoch === this.epoch) { this._error(error); return; }
      } finally { if (epoch === this.epoch) this.controller = null; }
      if (epoch === this.epoch) this._schedule(this.state === "exited" ? 2000 : 0);
    }
    _input(text) {
      if (!this.visible || this.state !== "open" || this.inputUnconfirmed || this.actionPending) return;
      const bytes = new TextEncoder().encode(text), epoch = this.epoch;
      if (!bytes.length) return;
      if (bytes.length > 65536) { this.status.textContent = "Paste up to 64 KiB at a time."; return; }
      this.writing = this.writing.then(async () => {
        if (epoch !== this.epoch || this.inputUnconfirmed || !this.visible) return;
        const sequence = ++this.sequence;
        try {
          const value = await this._request("input", this._bound({sequence, data_b64: bytesTo64(bytes)}));
          if (epoch !== this.epoch) return;
          if (value.last_sequence !== sequence || value.last_outcome !== "written") this._error({}, true);
        } catch (error) { if (epoch === this.epoch) this._error(error, true); }
      });
    }
    async _resize() {
      if (!this.visible || !this.term || !this.binding) return;
      const epoch = this.epoch, binding = this.binding;
      try { await this._request("resize", this._bound({cols: this.term.cols, rows: this.term.rows})); }
      catch (error) {
        if (epoch === this.epoch && binding === this.binding && error.status === 401) this._error(error);
      }
    }
    async prepareContext() {
      if (!this.contextEnabled) return null;
      if (!this.available || !this.term) throw new Error("terminal_context_unavailable");
      const selected = this.term.getSelection();
      let text = selected, source = "selection", truncated = false;
      if (!text) {
        source = "recent"; const buffer = this.term.buffer.active;
        const end = Math.min(buffer.length, buffer.baseY + buffer.cursorY + 1);
        let start = Math.max(0, end - 20); truncated = start > 0;
        // Never manufacture a newline inside an automatically wrapped token.
        // If the first retained row is a continuation, omit that incomplete
        // logical line rather than send a fragment that defeats secret masks.
        while (start < end && buffer.getLine(start)?.isWrapped) { start++; truncated = true; }
        text = "";
        for (let index = start; index < end; index++) {
          const continuation = index + 1 < end && buffer.getLine(index + 1)?.isWrapped;
          text += buffer.getLine(index)?.translateToString(!continuation) || "";
          if (index + 1 < end && !continuation) text += "\n";
        }
      }
      const lines = text.split("\n");
      if (lines.length > 20) { text = lines.slice(-20).join("\n"); truncated = true; }
      let bytes = new TextEncoder().encode(text);
      if (bytes.length > 8192) {
        let start = bytes.length - 8192;
        while (start < bytes.length && (bytes[start] & 0xc0) === 0x80) start++;
        text = new TextDecoder().decode(bytes.slice(start)); truncated = true;
      }
      const epoch = this.epoch, identity = this.binding;
      const value = await this._request("context-scrub", {terminal_id: identity.terminal_id,
        generation: identity.generation, captured_at: new Date().toISOString(), source, text, truncated});
      if (epoch !== this.epoch || this.binding !== identity) throw new Error("terminal_context_changed");
      return value;
    }
    dispose() {
      this.visible = false; this._cancel(); clearTimeout(this.keepTimer); this.term?.dispose(); this.term = null; this.fit = null;
      this.binding = null; this.state = "closed"; this.cursor = 0; this.sequence = 0;
      this.writing = Promise.resolve(); this.inputUnconfirmed = false; this.contextEnabled = false;
      this.actionPending = false; this.actionToken = null; this.openButton.disabled = false; this.closeButton.disabled = false;
      this.viewport.replaceChildren(); this.viewport.hidden = true; this.placeholder.hidden = false;
      this.closeButton.hidden = true; action(this.openButton, "terminal", "Open terminal");
      this.status.textContent = "Open a terminal when you need it.";
    }
  }
  window.OwnerTerminalView = OwnerTerminalView;
  window.RadhouseOwnerTerminal = OwnerTerminalView;
})();
