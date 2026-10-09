"use strict";
(() => {
  const labels = {starting: "Opening the assistant’s browser…", live: "Live browser",
    idle: "Browser is idle", unavailable: "Browser view is unavailable"};
  const identifier = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
  const maxFrame = 512 * 1024;
  function resolveAddress(value, engine="google") {
    const text=value.trim();
    if(!text)throw new Error("Enter an address or search.");
    if(!["google","duckduckgo"].includes(engine))throw new Error("Choose a supported search engine.");
    const web=/^https?:\/\//i.test(text);
    const host=/^(?:localhost|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9-]+|\[[0-9a-f:]+\])(?::\d+)?(?:[/?#].*)?$/i.test(text);
    if(web || host) {
      const url=new URL(web ? text : "https://"+text);
      if(!["http:","https:"].includes(url.protocol) || !url.hostname || url.username || url.password)
        throw new Error("Use a web address without embedded login details.");
      return {url:url.href,kind:"navigation"};
    }
    if(/^[a-z][a-z0-9+.-]*:/i.test(text) || text.startsWith("//"))
      throw new Error("Use an HTTP or HTTPS address.");
    const url=new URL(engine==="duckduckgo" ? "https://duckduckgo.com/" : "https://www.google.com/search");
    url.searchParams.set("q",text);
    return {url:url.href,kind:"search"};
  }
  window.RadhouseAddress={resolve:resolveAddress};

  class BrowserView {
    constructor(container, {persistent = false, request = null, onReturn = null, tab = null} = {}) {
      this.container = container;
      this.persistent = persistent;
      this.container.classList.add("browser-view");
      this.container.hidden = true;
      this.epoch = 0; this.open = true; this.active = false;
      this.run = null; this.generation = null; this.timer = null;
      this.controller = null; this.frameUrl = null; this.pendingUrls = new Set();
      this.request = request; this.onReturn = onReturn; this.tab = tab;
      this.controlEnabled = false; this.control = null; this.sequence = 0;
      this.displayedFrame = null; this.actionPending = false; this.lease = null;
      this.inputUnconfirmed = false;
      this.preferences=null;
      const header = document.createElement("div"); header.className = "browser-view-header"; this.header = header;
      const heading = document.createElement("h2"); heading.textContent = "Assistant browser";
      this.toggle = document.createElement("button"); this.toggle.type = "button";
      this.toggle.textContent = "Hide browser"; this.toggle.setAttribute("aria-expanded", "true");
      this._decorate(this.toggle,"eye","Hide browser",true);
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
      if (this.request) this._createControls();
      this.toggle.addEventListener("click", () => {
        this.open = !this.open; this.body.hidden = !this.open;
        this.container.classList.toggle("browser-view--collapsed",!this.open);
        this._decorate(this.toggle,"eye",this.open ? "Hide browser" : "Show browser",true);
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
      const changed = (!this.controlEnabled && run !== this.run) || generation !== this.generation;
      if (changed) {
        this._cancel(); this._clearImage();
        if (state !== "unavailable" && this.generation !== null && generation !== this.generation) this.addressEdited = false;
        if (run !== this.run) {
          this.open = true; this.body.hidden = false;
          this.container.classList.remove("browser-view--collapsed");
          this._decorate(this.toggle,"eye","Hide browser",true); this.toggle.setAttribute("aria-expanded", "true");
        }
      }
      this.run = run; this.generation = generation;
      this.active = state === "live" && (run !== null || this.controlEnabled) && generation !== null;
      this.container.hidden = !this.persistent && state === "idle" && run === null;
      this._label(labels[state]);
      this.site.textContent = typeof value?.url === "string" ? value.url : "";
      this.site.hidden = !this.site.textContent;
      if (this.request) this._updateControls(value, state);
      if (!this.active) { this._cancel(); this._clearImage(); }
      else if (!this.controller && this.timer === null) this._schedule(0);
    }

    _cancel() {
      this.epoch++;
      clearTimeout(this.timer); this.timer = null;
      this.controller?.abort(); this.controller = null;
    }

    _clearImage() {
      this.displayedFrame = null;
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
        const path = this.controlEnabled ? `/chat/browser/frame?generation=${encodeURIComponent(generation)}`
          : `/chat/browser/frame?run_id=${encodeURIComponent(run)}`;
        const response = await fetch(path,
          {credentials: "same-origin", cache: "no-store", signal: controller.signal,
            headers: this.controlEnabled ? {"X-Radhouse-Browser-Tab":this.tab()} : {}});
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
        let displayed = null;
        if (this.controlEnabled) {
          const frame = response.headers.get("x-radhouse-browser-frame-id"),
            width = Number(response.headers.get("x-radhouse-browser-width")),
            height = Number(response.headers.get("x-radhouse-browser-height"));
          if (!identifier.test(frame || "") || !Number.isInteger(width) || !Number.isInteger(height)
              || width < 1 || height < 1 || width > 8192 || height > 8192) throw new Error("browser_unavailable");
          displayed = {frame_id:frame,viewport:{width,height}};
        }
        objectUrl = URL.createObjectURL(blob); this.pendingUrls.add(objectUrl);
        const image = new Image(); image.src = objectUrl;
        await image.decode();
        if (epoch !== this.epoch || !this.active || !this.open || document.hidden
            || run !== this.run || generation !== this.generation) return;
        if (this.frameUrl) URL.revokeObjectURL(this.frameUrl);
        this.frameUrl = objectUrl; this.pendingUrls.delete(objectUrl); objectUrl = null;
        this.image.src = this.frameUrl; this.image.hidden = false; this.viewport.hidden = false;
        this.displayedFrame = displayed;
        this._label(labels.live);
        this._renderControlState();
      } catch {
        // A failed or undecodable frame clears the image and displays unavailable.
        if (epoch === this.epoch) { this._clearImage(); this._label(labels.unavailable); this._renderControlState(); }
      } finally {
        clearTimeout(timeout);
        if (objectUrl) { URL.revokeObjectURL(objectUrl); this.pendingUrls.delete(objectUrl); }
        if (this.controller === controller) this.controller = null;
        if (epoch === this.epoch) this._schedule(500);
      }
    }

    stop() {
      this._cancel(); this._clearImage();
      this._clearSecrets(); this.control = null; this.lease = null; this.actionNotice=null;
      this.inputUnconfirmed=false;
      this.addressEdited=false;
      this.preferences=null;
      this.suggestions?.replaceChildren();
      this.active = false; this.run = null; this.generation = null;
      this.site.textContent = ""; this._label(""); this.container.hidden = true;
    }

    destroy() { this.stop(); document.removeEventListener("visibilitychange", this.visibility); }

    _decorate(button,icon,label,compact=false) {
      if(window.RadhouseIcons && icon)window.RadhouseIcons.decorate(button,icon,label,{compact});
      else button.textContent=label;
      return button;
    }

    _button(label, action, icon=null, compact=false) {
      const button = document.createElement("button"); button.type = "button"; button.textContent = label;
      this._decorate(button,icon,label,compact);
      button.addEventListener("click",async()=>{
        if(button.disabled || button.getAttribute("aria-busy")==="true")return;
        window.RadhouseIcons?.busy(button,true);
        try {await action();} finally {window.RadhouseIcons?.busy(button,false);}
      }); return button;
    }

    _createControls() {
      this.launcher = document.createElement("div"); this.launcher.className = "browser-launcher";
      this.illustration = this._button("Open browser window",()=>this._act("/chat/browser/open",{}),"browser",true);
      this.illustration.classList.add("browser-illustration");
      this.illustration.setAttribute("aria-label","Open browser window");
      this.launchCaption = document.createElement("p");
      this.openButton = this._button("Open browser",()=>this._act("/chat/browser/open",{}),"browser");
      this.openButton.classList.add("primary");
      this.reconnectBrowser = this._button("Reconnect browser",()=>this._act("/chat/browser",undefined,{method:"GET"}),"refresh");
      this.launcher.append(this.illustration,this.launchCaption,this.openButton,this.reconnectBrowser);
      this.toolbar = document.createElement("form"); this.toolbar.className = "browser-address";
      this.address = document.createElement("input"); this.address.type="text";
      this.address.placeholder="Search or enter address"; this.address.setAttribute("aria-label","Search or enter address");
      this.address.inputMode="search";this.address.enterKeyHint="go";this.address.autocapitalize="none";
      this.suggestions=document.createElement("datalist");this.suggestions.id="browser-address-"+crypto.randomUUID();
      this.address.setAttribute("list",this.suggestions.id);
      this.address.addEventListener("focus",()=>{void this._loadPreferences();});
      this.address.autocomplete="off"; this.address.spellcheck=false;
      this.addressEdited=false;
      this.address.addEventListener("input",()=>{this.addressEdited=true;});
      this.back = this._button("Back",()=>this._input("back",{}),"back",true);
      this.reload = this._button("Refresh",()=>this._input("reload",{}),"refresh",true);
      this.go = document.createElement("button"); this.go.type="submit"; this.go.textContent="Go";
      this._decorate(this.go,"forward","Go",true);
      this.toolbar.append(this.back,this.reload,this.address,this.go,this.suggestions);
      this.toolbar.addEventListener("submit",event=>{event.preventDefault();void this._navigateAddress();});
      this.actions = document.createElement("div"); this.actions.className="browser-actions";
      this.owner = document.createElement("span"); this.owner.className="browser-owner";
      this.connection = document.createElement("span"); this.connection.className="browser-connection";
      this.connection.textContent="Live";this.connection.setAttribute("aria-hidden","true");
      this.sessionActions=document.createElement("div");this.sessionActions.className="browser-session-actions";
      this.take = this._button("Take control",()=>this._act("/chat/browser/control/take",{...this._binding(),request_id:crypto.randomUUID()}),"pointer");
      this.returnButton = this._button("Return to agent",()=>this._return(),"agent");
      this.closeButton = this._button("Close browser",()=>this._act("/chat/browser/control/close",this._binding()),"close");
      this.closeButton.classList.add("browser-close");
      this.reconnectButton = this._button("Reconnect controls",()=>this._reconnectControls(),"refresh");
      this.sessionActions.append(this.take,this.returnButton,this.reconnectButton,this.closeButton);
      this.actions.append(this.owner,this.connection,this.sessionActions);
      this.controlStatus = document.createElement("p"); this.controlStatus.className="browser-control-status";
      this.controlStatus.setAttribute("role","status"); this.controlStatus.setAttribute("aria-live","polite");
      this.keyboard = document.createElement("form"); this.keyboard.className="browser-keyboard";
      this.typeField = document.createElement("input"); this.typeField.type="password"; this.typeField.autocomplete="off";
      this.typeField.setAttribute("aria-label","Type into selected page field");
      this.typeField.placeholder="Type into the selected page field…";
      this.typeButton = document.createElement("button"); this.typeButton.type="submit"; this.typeButton.textContent="Type";
      this._decorate(this.typeButton,"keyboard","Type");
      this.keyboard.append(this.typeField,this.typeButton);
      for (const key of ["Tab","Enter","Backspace"]) this.keyboard.append(this._button(key,()=>this._input("press",{key})));
      this.keyboard.addEventListener("submit",event=>{event.preventDefault();const text=this.typeField.value;this.typeField.value="";if(text)void this._input("text",{text});});
      this.loginToggle = this._button("Saved logins",()=>this._showLogins(),"key");
      this.utilities=document.createElement("div");this.utilities.className="browser-utilities";
      this.utilities.append(this.keyboard,this.loginToggle);
      this.loginPanel=document.createElement("section"); this.loginPanel.className="browser-logins"; this.loginPanel.hidden=true;
      const loginHeading=document.createElement("h3"); loginHeading.textContent="Saved logins";
      this.loginList=document.createElement("div");
      this.loginForm=document.createElement("form");
      this.loginFields={};
      for (const [name,label,type] of [["label","Login name","text"],["identifier","Account","text"],["password","Password","password"]]) {
        const wrapper=document.createElement("label");wrapper.textContent=label;
        const input=document.createElement("input");input.type=type;input.autocomplete="off";input.required=true;
        input.maxLength=name==="password" ? 16384 : name==="label" ? 256 : 512;
        wrapper.append(input);this.loginForm.append(wrapper);this.loginFields[name]=input;
      }
      const typeLabel=document.createElement("label");typeLabel.textContent="Account type";
      this.loginType=document.createElement("select");
      for (const [value,label] of [["username","Username"],["email","Email"],["phone","Phone"]]) {
        const option=document.createElement("option");option.value=value;option.textContent=label;this.loginType.append(option);
      }
      typeLabel.append(this.loginType);this.loginForm.prepend(typeLabel);
      this.saveLogin=document.createElement("button");this.saveLogin.type="submit";this.saveLogin.textContent="Save login for this site";
      this.loginForm.append(this.saveLogin);
      this.loginForm.addEventListener("submit",event=>{event.preventDefault();void this._saveLogin();});
      const note=document.createElement("p");note.textContent="Optional. This stores a login for this website in your agent’s encrypted vault. Complete verification codes directly on the page.";
      this.loginPanel.append(loginHeading,note,this.loginList,this.loginForm);
      this.body.prepend(this.launcher,this.toolbar,this.actions,this.controlStatus);
      this.body.append(this.utilities,this.loginPanel);
      this.viewport.addEventListener("click",event=>{
        const point=this._point(event);if(point)void this._input("click",point);
      });
      this.viewport.addEventListener("wheel",event=>{
        const point=this._point(event);if(!point)return;event.preventDefault();
        void this._input("scroll",{...point,delta_x:event.deltaX,delta_y:event.deltaY});
      },{passive:false});
      this.container.addEventListener("focusout",event=>{
        if (!this.container.contains(event.relatedTarget)) this._clearSecrets();
      });
    }

    _clearSecrets() {
      if(this.typeField)this.typeField.value="";
      if(this.loginFields)for(const field of Object.values(this.loginFields))field.value="";
      if(this.loginPanel)this.loginPanel.hidden=true;
      if(this.loginToggle)this.loginToggle.setAttribute("aria-expanded","false");
      if(this.loginList)this.loginList.replaceChildren();
    }

    _binding() {
      return {generation:this.generation,revision:this.control?.revision,lease_id:this.control?.lease_id || null};
    }

    _updateControls(value,state) {
      const previous=this.lease;
      this.control=value?.control || null;this.lease=this.control?.lease_id || null;
      if(previous!==this.lease){this.sequence=0;this.inputUnconfirmed=false;this.actionNotice=null;this._clearSecrets();}
      if(this.control?.next_sequence)this.sequence=Math.max(this.sequence,this.control.next_sequence-1);
      this.canReturn=value?.can_return===true;this.vaultEnabled=value?.vault_enabled===true;
      const unavailable=state==="unavailable";
      if(state==="idle" || this.state==="unavailable" && !unavailable)this.actionNotice=null;
      this.state=state;
      this.container.classList.toggle("browser-view--controlled",this.controlEnabled);
      this.container.classList.toggle("browser-view--active",this.active);
      this.launcher.hidden=this.active || this.controlEnabled && state!=="idle" && !unavailable;
      this.openButton.hidden=unavailable;
      this.reconnectBrowser.hidden=!unavailable;
      this.openButton.disabled=!this.controlEnabled || this.actionPending || unavailable;
      this.illustration.disabled=this.openButton.disabled;
      this.launchCaption.textContent=unavailable ? "The browser connection is unavailable. Reconnect to check it again." : this.controlEnabled
        ? "Open a browser to explore, sign in, or share a page with your assistant."
        : "Browser control needs the upgraded Hermes runtime. You can still watch an active agent browser.";
      this.toolbar.hidden=!this.controlEnabled || !this.active;
      this.actions.hidden=!this.controlEnabled || !this.active;
      this.keyboard.hidden=!this._human();
      if(state==="idle")this.addressEdited=false;
      if(!this.addressEdited && document.activeElement!==this.address)this.address.value=value?.url || "";
      if(state!=="live")this._clearSecrets();
      this._renderControlState();
      if(!this.controlEnabled && state==="idle")this.controlStatus.textContent="Browser control is not connected to this instance yet.";
    }

    _human() {
      return this.active && this.control?.mode==="human" && !!this.lease
        && this.control.lease_expires_at>Date.now()/1000;
    }

    _renderControlState() {
      if(!this.request)return;
      const human=this._human(), input=human && !!this.displayedFrame && !this.actionPending && !this.inputUnconfirmed;
      const ownerText=human ? "You have control" : {agent:"Agent has control",takeover_pending:"Handing over…",paused:"Browser paused",recovering:"Check the page",human:"Open in another tab"}[this.control?.mode] || "Connecting…";
      const ownerIcon=human ? "pointer" : ["agent","takeover_pending","paused","recovering"].includes(this.control?.mode) ? "agent" : "browser";
      if(this.owner.textContent!==ownerText){
        this.owner.textContent="";
        if(window.RadhouseIcons)this.owner.append(window.RadhouseIcons.create(ownerIcon));
        this.owner.append(document.createTextNode(ownerText));
      }
      window.RadhouseIcons?.setAgentState(this.owner,{agent:"working",takeover_pending:"waiting",paused:"paused",recovering:"error"}[this.control?.mode] || "ready");
      window.RadhouseIcons?.setAgentState(this.returnButton,this.canReturn ? "ready" : "thinking");
      this.connection.textContent=this.image.hidden ? this.status.textContent===labels.unavailable ? "Unavailable" : "Connecting" : "Live";
      this.connection.dataset.state=this.image.hidden ? "pending" : "live";
      this.container.setAttribute("aria-busy",String(this.actionPending));
      this.controlStatus.classList.toggle("browser-control-status--quiet",!this.actionNotice && !["takeover_pending","paused","recovering"].includes(this.control?.mode) && (!human || this.canReturn));
      this.loginToggle.setAttribute("aria-expanded",String(!this.loginPanel.hidden));
      this.openButton.disabled=!this.controlEnabled || this.actionPending || this.state==="unavailable";
      this.illustration.disabled=this.openButton.disabled;
      this.reconnectBrowser.disabled=this.actionPending;
      this.viewport.classList.toggle("browser-interactive",input);
      this.take.hidden=!this.control?.can_take || human;
      this.take.disabled=this.actionPending;
      this.returnButton.hidden=!human;
      this.returnButton.disabled=this.actionPending || !this.canReturn || this.inputUnconfirmed;
      this.reconnectButton.hidden=!this.inputUnconfirmed || !human;
      this.reconnectButton.disabled=this.actionPending;
      this.returnButton.title=this.canReturn ? "" : "Your assistant’s current reply is still finishing.";
      this.closeButton.disabled=this.actionPending;
      this.loginToggle.hidden=!human || !this.vaultEnabled;
      this.loginToggle.disabled=this.actionPending || this.inputUnconfirmed;
      for(const element of this.toolbar.elements)element.disabled=!input;
      window.RadhouseIcons?.busy(this.go,this.actionPending && document.activeElement===this.go);
      for(const element of this.keyboard.elements)element.disabled=!input;
      for(const element of this.loginForm.elements)element.disabled=!human || this.actionPending || this.inputUnconfirmed;
      for(const button of this.loginList.querySelectorAll("button"))button.disabled=!human || this.actionPending || this.inputUnconfirmed;
      this.keyboard.hidden=!human;
      this.utilities.hidden=!human;
      const text=this.active ? {agent:"Your assistant is using this browser.",human:"You have control. Browser actions from your assistant are paused.",
        takeover_pending:"Waiting for the current browser action to finish…",paused:"Browser actions are paused. Take control to continue.",
        recovering:"A browser action could not be confirmed. Input is paused."}[this.control?.mode] : null;
      if(this.actionNotice)this.controlStatus.textContent=this.actionNotice;
      else if(text)this.controlStatus.textContent=human && !this.canReturn ? text+" Its current reply is still finishing." : text;
      else this.controlStatus.textContent="";
    }

    _point(event) {
      if(!this._human() || !this.displayedFrame || this.actionPending)return null;
      const rect=this.image.getBoundingClientRect(),{width,height}=this.displayedFrame.viewport;
      const scale=Math.min(rect.width/width,rect.height/height),
        left=rect.left+(rect.width-width*scale)/2,top=rect.top+(rect.height-height*scale)/2;
      const x=(event.clientX-left)/scale,y=(event.clientY-top)/scale;
      return Number.isFinite(x) && Number.isFinite(y) && x>=0 && y>=0 && x<width && y<height ? {x,y} : null;
    }

    async _act(path,body,{method="POST",update=true}={}) {
      if(this.actionPending || !this.request)return null;
      const epoch=this.epoch;this.actionPending=true;this.actionNotice=null;this._renderControlState();
      this.container.dispatchEvent(new CustomEvent("browser-activity",{bubbles:true}));
      try {
        const value=await this.request(path,body,method);
        if(epoch!==this.epoch)return null;
        if(update) {
          this.update(value);
          this.container.dispatchEvent(new CustomEvent("browser-state",{bubbles:true,detail:value}));
        }
        return value;
      } catch {
        if(epoch===this.epoch)this.actionNotice=method==="GET"
          ? "The browser connection is unavailable. Reconnect to check it again."
          : "We could not confirm that action. It has not been retried. Check the browser before continuing.";
        return null;
      } finally {
        this.actionPending=false;this._clearSecrets();this._renderControlState();
      }
    }

    async _input(operation,args) {
      if(!this._human() || !this.displayedFrame || this.actionPending || this.inputUnconfirmed)return;
      const value=await this._act("/chat/browser/control/input",{...this._binding(),...this.displayedFrame,
        sequence:++this.sequence,operation,arguments:args},{update:false});
      if(!value || ["uncertain","reserved"].includes(value.outcome)) {
        this.inputUnconfirmed=true;
        this.actionNotice="Previous input wasn’t confirmed. Check the page before continuing.";
      } else if(value.outcome!=="applied")this.actionNotice="That action was not applied. Check the page before trying another action.";
      else if(operation==="navigate" && this.address.value===args.url)this.addressEdited=false;
      this._renderControlState();
      this._cancel();this._schedule(0);
      return value;
    }

    async _loadPreferences() {
      const epoch=this.epoch;
      try {
        const value=await this.request("/chat/browser/preferences",undefined,"GET");
        if(epoch!==this.epoch || !["google","duckduckgo"].includes(value?.search_engine))return false;
        this.preferences=value;
        this.suggestions.replaceChildren();
        for(const entry of value.history || []) {
          const option=document.createElement("option");option.value=entry.url;this.suggestions.append(option);
        }
        return true;
      } catch {return false;}
    }

    async _navigateAddress() {
      const original=this.address.value;
      try {
        let target=resolveAddress(original);
        if(target.kind==="search") {
          if(!await this._loadPreferences())throw new Error("Your browser settings could not be loaded. Try again.");
          target=resolveAddress(original,this.preferences.search_engine);
        }
        const result=await this._input("navigate",{url:target.url});
        if(result?.outcome==="applied" && this.address.value===original) {
          this.address.value=target.url;this.addressEdited=false;
          void this._loadPreferences();
        }
      } catch(error) {this.actionNotice=error.message;this._renderControlState();}
    }

    async _reconnectControls() {
      if(!this._human() || !this.inputUnconfirmed || this.actionPending)return;
      this._clearSecrets();
      const paused=await this._act("/chat/browser/control/pause",this._binding());
      if(!paused) {
        this.actionNotice="Previous input wasn’t confirmed. Check the page before continuing.";
        this._renderControlState();return;
      }
      if(paused.control?.mode!=="paused" || paused.control?.can_take!==true)return;
      await this._act("/chat/browser/control/take",{...this._binding(),request_id:crypto.randomUUID()});
    }

    async _return() {
      if(!this._human() || !this.canReturn || this.actionPending || this.inputUnconfirmed || !this.onReturn)return;
      this.actionPending=true;this._renderControlState();this._clearSecrets();
      try {await this.onReturn(this._binding());}
      finally {this.actionPending=false;this._renderControlState();}
    }

    async _showLogins() {
      if(!this._human() || !this.vaultEnabled || this.actionPending || this.inputUnconfirmed)return;
      const value=await this._act("/chat/browser/logins/list",{...this._binding(),sequence:++this.sequence},{update:false});
      if(!value)return;
      this.loginPanel.hidden=false;
      this.loginToggle.setAttribute("aria-expanded","true");
      for(const item of value.items || []) {
        const row=document.createElement("div");row.className="browser-login-item";
        const label=document.createElement("span");label.textContent=item.label+" · "+item.identifier+" · "+item.origin;
        row.append(label,this._button("Remove",async()=>{
          if(!this._human() || this.actionPending || this.inputUnconfirmed)return;
          const removed=await this._act("/chat/browser/logins/"+encodeURIComponent(item.id),{...this._binding(),sequence:++this.sequence},{method:"DELETE",update:false});
          if(removed?.removed)row.remove();
        }));this.loginList.append(row);
      }
    }

    async _saveLogin() {
      if(!this._human() || !this.vaultEnabled || this.actionPending || this.inputUnconfirmed)return;
      const body={...this._binding(),sequence:++this.sequence,identifier_type:this.loginType.value};
      for(const [name,field]of Object.entries(this.loginFields))body[name]=field.value;
      this._clearSecrets();
      const value=await this._act("/chat/browser/logins",body,{update:false});
      if(value){this.actionNotice="Login saved for this website.";this._renderControlState();}
    }
  }

  window.BrowserView = BrowserView;
})();
