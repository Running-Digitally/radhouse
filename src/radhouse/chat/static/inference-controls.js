"use strict";
(() => {
  class RadhouseInference {
    constructor({container, request, onAuthRequired = () => {}, onChange = () => {}}) {
      this.container = container; this.request = request;
      this.onAuthRequired = onAuthRequired; this.onChange = onChange;
      this.catalog = null; this.epoch = 0; this.controller = null; this.disabled = false; this.loading = false;
      container.classList.add("inference-controls");
      this.model = document.createElement("select"); this.model.setAttribute("aria-label", "Model");
      this.thinking = document.createElement("select"); this.thinking.setAttribute("aria-label", "Thinking");
      this.modelLabel = this.label("Model", this.model);
      this.thinkingLabel = this.label("Thinking", this.thinking);
      this.status = document.createElement("span"); this.status.className = "inference-status";
      this.status.setAttribute("role", "status");
      this.hint = document.createElement("span"); this.hint.className = "inference-status";
      this.refresh = document.createElement("button"); this.refresh.type = "button";
      this.refresh.textContent = "Refresh models";
      window.RadhouseIcons?.decorate(this.refresh, "refresh", "Refresh models");
      container.replaceChildren(this.modelLabel, this.thinkingLabel, this.refresh, this.hint, this.status);
      this.model.addEventListener("change", () => { this.renderThinking(); this.onChange(this.selection()); });
      this.thinking.addEventListener("change", () => { this.onChange(this.selection()); });
      this.refresh.addEventListener("click", () => { void this.load(true); });
      this.clear();
    }

    label(text, select) {
      const label = document.createElement("label");
      const span = document.createElement("span"); span.textContent = text;
      label.append(span, select); return label;
    }

    option(select, value, label, disabled = false) {
      const option = document.createElement("option");
      option.value = value; option.textContent = label; option.disabled = disabled;
      select.append(option);
    }

    clear() {
      this.epoch++; this.controller?.abort(); this.controller = null; this.catalog = null; this.loading = false;
      this.model.replaceChildren(); this.option(this.model, "", "Default"); this.model.value = "";
      this.thinking.replaceChildren(); this.option(this.thinking, "default", "Default");
      this.thinking.value = "default"; this.thinkingLabel.hidden = true; this.status.textContent = "";
      this.hint.textContent = "";
      this.setDisabled(this.disabled);
    }

    selection() {
      const model = this.model.value || null, thinking = this.thinking.value || "default";
      return model === null && thinking === "default" ? null : {model, thinking};
    }

    setDisabled(disabled) {
      this.disabled = Boolean(disabled);
      this.model.disabled = this.disabled || this.loading;
      this.thinking.disabled = this.disabled || this.loading;
      this.refresh.disabled = this.disabled || this.loading;
      window.RadhouseIcons?.busy(this.refresh, this.loading);
    }

    renderThinking(preserve = "default") {
      const selected = this.model.value || this.catalog?.current_model;
      const row = this.catalog?.models?.find(row => row.id === selected && row.available);
      const caps = row?.thinking;
      this.hint.textContent = row && caps?.state === "unknown" ? "Thinking settings aren’t available for this model." : "";
      this.thinking.replaceChildren(); this.option(this.thinking, "default", "Default");
      const supported = caps?.state === "supported";
      if (supported && caps.can_enable) this.option(this.thinking, "on", "On");
      if (supported && caps.can_disable) this.option(this.thinking, "off", "Off");
      if (supported) for (const effort of caps.choices) {
        this.option(this.thinking, effort, effort.charAt(0).toUpperCase() + effort.slice(1));
      }
      const exists = Array.from(this.thinking.options).some(option => option.value === preserve);
      if (!exists && preserve !== "default") this.option(this.thinking, preserve, preserve + " (unavailable)", true);
      this.thinking.value = preserve;
      this.thinkingLabel.hidden = this.thinking.options.length === 1;
    }

    async load(refresh = false) {
      this.controller?.abort(); const epoch = ++this.epoch;
      const controller = this.controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      const selected = this.selection();
      this.loading = true; this.setDisabled(this.disabled);
      this.status.textContent = "Checking models…";
      try {
        const value = await this.request("/chat/inference" + (refresh ? "?refresh=true" : ""), undefined, false, controller.signal);
        if (epoch !== this.epoch) return;
        if (value?.schema !== "radhouse.inference.v1" || !Array.isArray(value.models)) throw new Error("invalid_catalog");
        this.catalog = value; this.model.replaceChildren();
        this.option(this.model, "", value.current_model ? "Default · " + value.current_model : "Default");
        for (const row of value.models) {
          this.option(this.model, row.id, row.label + (row.available ? "" : " (unavailable)"), !row.available);
        }
        if (selected?.model && !value.models.some(row => row.id === selected.model)) {
          this.option(this.model, selected.model, selected.model + " (unavailable)", true);
        }
        this.model.value = selected?.model || "";
        this.renderThinking(selected?.thinking || "default");
        this.status.textContent = value.state === "available" ? "" : value.models.some(row => row.reason === "transport_unsupported") ?
          "This engine’s connection doesn’t support workspace tools." : "Model choices are unavailable. You can use Default.";
        this.setDisabled(this.disabled);
      } catch (error) {
        if (epoch !== this.epoch) return;
        if (error?.status === 401 || error?.code === "authentication_required" || error?.message === "authentication_required") {
          this.onAuthRequired(); return;
        }
        this.catalog = null;
        for (const option of this.model.options) if (option.value) {
          option.disabled = true;
          if (!option.textContent.endsWith(" (unavailable)")) option.textContent += " (unavailable)";
        }
        this.renderThinking(selected?.thinking || "default"); this.setDisabled(this.disabled);
        this.status.textContent = "Model choices couldn’t be checked. You can use Default.";
      } finally {
        clearTimeout(timeout); if (epoch === this.epoch) {
          this.controller = null; this.loading = false; this.setDisabled(this.disabled);
          this.onChange(this.selection());
        }
      }
    }
  }
  window.RadhouseInference = RadhouseInference;
})();
