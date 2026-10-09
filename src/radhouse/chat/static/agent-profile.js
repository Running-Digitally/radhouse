"use strict";
(() => {
  const schema="radhouse.agent-profile.v1";
  const defaults=Object.freeze({schema,revision:0,name:"",intro:"",theme:"hearthside",portrait:"ember",accent:"fern",surface:"paper",stateMotion:true,iconMotion:true});
  const accents=Object.freeze({fern:"Fern",clay:"Clay",tide:"Tide",plum:"Plum"});
  const surfaces=Object.freeze({paper:"Warm paper",night:"Evening",system:"Follow device"});
  const signalKey="radhouse.agent-profile.saved";
  const clone=value=>({...value});
  const node=(tag,text,className)=>{const result=document.createElement(tag);if(text!==undefined)result.textContent=text;if(className)result.className=className;return result;};
  const profileFields=["name","intro","theme","portrait","accent","surface","stateMotion","iconMotion"];
  const same=(a,b)=>a && b && profileFields.every(key=>a[key]===b[key]);
  const unsafeText=/[\p{Cc}\p{Cs}\p{Zl}\p{Zp}\u202a-\u202e\u2066-\u2069]/u;
  const textError=(value,limit,multiline=false)=> typeof value!=="string" || unsafeText.test(multiline?value.replaceAll("\n",""):value)
    ? "Use plain text without control characters." : [...value.trim()].length>limit ? "Use up to "+limit+" characters." : "";
  const colorScheme=matchMedia("(prefers-color-scheme: dark)");
  let activePresentation=null;
  function applyAppearance(profile) {
    activePresentation=profile;
    const value=profile || defaults;
    document.documentElement.dataset.rhAccent=value.accent;
    document.documentElement.dataset.rhSurface=value.surface==="system" ? (colorScheme.matches?"night":"paper") : value.surface;
    window.RadhouseIcons?.setMotionPreferences({iconMotion:value.iconMotion,stateMotion:value.stateMotion});
  }
  colorScheme.addEventListener("change",()=>{if(activePresentation?.surface==="system")applyAppearance(activePresentation);});

  class AgentProfile {
    constructor({container,request,onAuthRequired=null,onChange=null}) {
      this.container=container;this.request=request;this.onAuthRequired=onAuthRequired;this.onChange=onChange;
      this.catalog=null;this.saved=null;this.current=null;this.epoch=0;this.abort=null;this.busy=false;this.visible=false;this.remoteChanged=false;this.activeTab=0;
      this.status=node("p","Opening your agent…","agent-profile-status");this.status.setAttribute("role","status");this.status.setAttribute("aria-live","polite");
      this.retry=node("button","Try again");this.retry.type="button";this.retry.hidden=true;this.retry.addEventListener("click",()=>void this.load());
      this.editor=node("div",undefined,"agent-profile-editor");this.container.replaceChildren(this.status,this.retry,this.editor);
      this.storageHandler=event=>{if(event.key===signalKey && this.saved)void this.refreshFromOtherTab();};
      window.addEventListener("storage",this.storageHandler);
      document.addEventListener("radhouse-agent-state",event=>this.renderState(event.detail));
    }

    get profile(){return this.current ? clone(this.current) : null;}
    get savedProfile(){return this.saved ? clone(this.saved) : null;}
    get dirty(){return Boolean(this.saved && !same(this.current,this.saved));}
    get displayName(){return this.current?.name || "Your Agent";}
    setVisible(value){this.visible=Boolean(value);this.container.hidden=!this.visible;}

    clear() {
      this.epoch++;this.abort?.abort();this.abort=null;this.busy=false;this.saved=null;this.current=null;this.remoteChanged=false;this.activeTab=0;
      if(this.previewImage)window.RadhousePortrait?.clear(this.previewImage);this.editor.replaceChildren();this.status.textContent="";this.retry.hidden=true;
      applyAppearance(null);window.RadhouseNavigation?.setProfile(null);this.onChange?.(null);
    }

    valid(value) {
      return value?.schema===schema && Number.isInteger(value.revision) && value.revision>=0 &&
        !textError(value.name,32) && !textError(value.intro,160,true) &&
        this.catalog?.profiles.some(entry=>entry.id===value.portrait && entry.theme===value.theme) &&
        this.catalog?.themes.some(entry=>entry.id===value.theme) && Object.hasOwn(accents,value.accent) && Object.hasOwn(surfaces,value.surface) &&
        typeof value.stateMotion==="boolean" && typeof value.iconMotion==="boolean";
    }

    async load() {
      if(this.dirty || this.busy)return;
      const epoch=++this.epoch;this.abort?.abort();this.abort=new AbortController();this.busy=true;
      this.status.textContent="Opening your agent…";this.retry.hidden=true;
      try {
        if(!this.catalog)this.catalog=await this.request("/workspace-assets/agent-profile/catalog.json",undefined,false,this.abort.signal);
        const value=await this.request("/chat/agent-profile",undefined,false,this.abort.signal);
        if(epoch!==this.epoch)return;
        if(!this.valid(value))throw new Error("invalid_agent_profile");
        this.saved=clone(value);this.current=clone(value);this.remoteChanged=false;
        this.render();this.present();this.status.textContent="";
      } catch(error) {
        if(epoch!==this.epoch)return;
        if(error.status===401){this.clear();this.onAuthRequired?.();return;}
        this.status.textContent="Your agent settings are unavailable. Try again.";this.retry.hidden=false;
      } finally {
        if(epoch===this.epoch){this.abort=null;this.busy=false;this.updateActions();}
      }
    }

    async refreshFromOtherTab() {
      if(this.busy)return;
      if(this.dirty){this.remoteChanged=true;this.status.textContent="Saved settings changed in another tab. Your draft is kept. Discard to load the saved version.";return;}
      await this.load();
    }

    chooseTheme(id) {
      const theme=this.catalog.themes.find(entry=>entry.id===id);if(!theme || this.busy)return;
      this.current.theme=id;this.current.portrait=theme.cover;this.renderCharacters();this.changed();
    }

    changed() {
      this.present();this.updateActions();
      const error=textError(this.current.name,32) || textError(this.current.intro,160,true);
      this.status.textContent=error || (this.dirty ? (this.remoteChanged?"Your draft is kept. Saved settings changed in another tab.":"Unsaved changes") : "");
    }

    present() {
      const profile=this.current, entry=this.catalog.profiles.find(item=>item.id===profile.portrait);
      applyAppearance(profile);window.RadhouseNavigation?.setProfile(profile,entry);this.onChange?.(clone(profile));
      if(!this.previewImage)return;
      this.previewImage.src=entry.asset;window.RadhousePortrait?.update(this.previewImage,profile,entry);this.previewName.textContent=profile.name || "Your Agent";
      this.previewIntro.textContent=profile.intro || entry.intro;this.previewRole.textContent=entry.role;
      this.storySummary.textContent="About "+entry.name;this.storyText.textContent=entry.story;
      this.suggest.textContent="Use "+entry.name;this.suggest.setAttribute("aria-label","Use "+entry.name+" as agent name");
    }

    render() {
      if(this.previewImage)window.RadhousePortrait?.clear(this.previewImage);this.editor.replaceChildren();this.editor.className="agent-profile-editor";
      const tabs=node("div",undefined,"agent-profile-tabs");tabs.setAttribute("role","tablist");tabs.setAttribute("aria-label","Customize your agent");
      const identity=node("button","Identity"), appearance=node("button","Appearance");
      identity.type=appearance.type="button";identity.id="agent-identity-tab";appearance.id="agent-appearance-tab";
      this.identityPanel=node("section");this.identityPanel.id="agent-identity-panel";this.appearancePanel=node("section");this.appearancePanel.id="agent-appearance-panel";
      for(const [button,panel] of [[identity,this.identityPanel],[appearance,this.appearancePanel]]){
        button.setAttribute("role","tab");button.setAttribute("aria-controls",panel.id);panel.setAttribute("role","tabpanel");panel.setAttribute("aria-labelledby",button.id);panel.tabIndex=0;
      }
      const show=index=>{this.activeTab=index;for(const [i,button] of [identity,appearance].entries()){button.setAttribute("aria-selected",String(i===index));button.tabIndex=i===index?0:-1;}this.identityPanel.hidden=index!==0;this.appearancePanel.hidden=index!==1;};
      identity.addEventListener("click",()=>show(0));appearance.addEventListener("click",()=>show(1));
      tabs.addEventListener("keydown",event=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;event.preventDefault();const index=event.key==="Home"?0:event.key==="End"?1:identity.getAttribute("aria-selected")==="true"?1:0;show(index);[identity,appearance][index].focus();});
      tabs.append(identity,appearance);show(this.activeTab);
      this.form=node("form",undefined,"agent-profile-form");this.form.addEventListener("submit",event=>{event.preventDefault();void this.save();});
      this.form.append(tabs,this.identityPanel,this.appearancePanel);
      this.renderThemes();
      this.characterField=node("fieldset",undefined,"agent-character-options");this.identityPanel.append(this.characterField);this.renderCharacters();
      const nameLabel=node("label","3. Make the name yours","agent-profile-field");
      this.nameInput=node("input");this.nameInput.id="agent-profile-name";this.nameInput.autocomplete="off";this.nameInput.placeholder="Your Agent";this.nameInput.value=this.current.name;
      nameLabel.htmlFor=this.nameInput.id;
      const nameRow=node("div",undefined,"agent-profile-name-row");this.suggest=node("button");this.suggest.type="button";this.suggest.addEventListener("click",()=>{this.nameInput.value=this.catalog.profiles.find(entry=>entry.id===this.current.portrait).name;this.current.name=this.nameInput.value;this.changed();});
      nameRow.append(this.nameInput,this.suggest);nameLabel.append(nameRow,node("small","Optional · up to 32 characters. Leave blank for “Your Agent”."));
      this.nameInput.addEventListener("input",()=>{this.current.name=this.nameInput.value;this.changed();});
      const introduction=node("details",undefined,"agent-intro-disclosure");introduction.append(node("summary","Personalize the introduction"));
      const introLabel=node("label","Introduction · optional, up to 160 characters","agent-profile-field");this.introInput=node("textarea");this.introInput.rows=2;this.introInput.id="agent-profile-intro";this.introInput.value=this.current.intro;
      introLabel.htmlFor=this.introInput.id;introLabel.append(this.introInput);introduction.append(introLabel);
      this.introInput.addEventListener("input",()=>{this.current.intro=this.introInput.value;this.changed();});this.identityPanel.append(nameLabel,introduction);
      this.renderAppearance();this.renderPreview();
      this.saveButton=node("button","Save changes","primary");this.saveButton.type="submit";window.RadhouseIcons?.decorate(this.saveButton,"check","Save changes");
      this.discardButton=node("button","Discard");this.discardButton.type="button";this.discardButton.addEventListener("click",()=>void this.discard());
      const actions=node("div",undefined,"agent-profile-actions");actions.append(this.discardButton,this.saveButton);this.form.append(actions);
      this.editor.append(this.form,this.preview);this.renderState(window.RadhouseNavigation?.agentStatus?.());
    }

    renderThemes() {
      const field=node("fieldset",undefined,"agent-theme-options");field.append(node("legend","1. Choose a theme"));
      for(const theme of this.catalog.themes){
        const label=node("label",undefined,"agent-theme-option"), radio=node("input");radio.type="radio";radio.name="agent-theme";radio.value=theme.id;radio.checked=theme.id===this.current.theme;
        radio.addEventListener("change",()=>this.chooseTheme(theme.id));
        const text=node("span");text.append(node("strong",theme.name),node("small",theme.style));label.append(radio,text);field.append(label);
      }
      this.identityPanel.append(field);
    }

    renderCharacters() {
      const theme=this.catalog.themes.find(entry=>entry.id===this.current.theme), entries=this.catalog.profiles.filter(entry=>entry.theme===theme.id);
      this.characterField.replaceChildren(node("legend","2. Pick a "+theme.name+" character"));this.characterField.dataset.count=String(entries.length);
      for(const entry of entries){
        const label=node("label",undefined,"agent-character-option"), radio=node("input");radio.type="radio";radio.name="agent-portrait";radio.value=entry.id;radio.checked=entry.id===this.current.portrait;
        radio.addEventListener("change",()=>{this.current.portrait=entry.id;this.changed();});
        const image=node("img");image.src=entry.asset;image.alt="";image.width=image.height=96;image.loading="lazy";image.decoding="async";
        label.append(radio,image,node("strong",entry.name),node("small",entry.role));this.characterField.append(label);
      }
    }

    renderAppearance() {
      const accent=node("fieldset",undefined,"agent-accent-options");accent.append(node("legend","A color to call your own"));
      for(const [id,name] of Object.entries(accents)){
        const label=node("label"),radio=node("input"),swatch=node("span",undefined,"agent-accent-swatch");radio.type="radio";radio.name="agent-accent";radio.value=id;radio.checked=id===this.current.accent;swatch.dataset.accent=id;swatch.setAttribute("aria-hidden","true");
        radio.addEventListener("change",()=>{this.current.accent=id;this.changed();});label.append(radio,swatch,node("span",name));accent.append(label);
      }
      const surface=node("fieldset",undefined,"agent-surface-options");surface.append(node("legend","Interface appearance"));
      for(const [id,name] of Object.entries(surfaces)){
        const label=node("label"),radio=node("input");radio.type="radio";radio.name="agent-surface";radio.value=id;radio.checked=id===this.current.surface;
        radio.addEventListener("change",()=>{this.current.surface=id;this.changed();});label.append(radio,node("span",name));surface.append(label);
      }
      this.appearancePanel.append(accent,surface);
      for(const [key,title,detail] of [["stateMotion","Agent state animation","Animate the portrait and show your agent’s actual status in the house mark."],["iconMotion","Playful interface icons","Small responses to hover and click."]]){
        const label=node("label",undefined,"agent-motion-toggle"),text=node("span"),input=node("input");text.append(node("strong",title),node("small",detail));input.type="checkbox";input.setAttribute("role","switch");input.checked=this.current[key];input.addEventListener("change",()=>{this.current[key]=input.checked;this.changed();});label.append(text,input);this.appearancePanel.append(label);
      }
      this.appearancePanel.append(node("p","Your device’s reduced motion setting always takes priority.","agent-profile-note"));
    }

    renderPreview() {
      this.preview=node("aside",undefined,"agent-profile-preview");this.preview.setAttribute("aria-label","Agent appearance preview");this.preview.append(node("p","Your agent, in context","agent-profile-eyebrow"));
      this.previewImage=node("img");this.previewImage.width=this.previewImage.height=160;this.previewImage.alt="Your agent’s portrait";this.previewImage.decoding="async";
      this.previewName=node("h2");this.previewIntro=node("p",undefined,"agent-preview-intro");this.previewRole=node("p",undefined,"agent-preview-role");
      this.state=node("p",undefined,"agent-preview-state");this.stateIcon=window.RadhouseIcons?.create("agent");this.stateText=node("span","Status unavailable");if(this.stateIcon)this.state.append(this.stateIcon);this.state.append(this.stateText);
      const story=node("details",undefined,"agent-character-story");this.storySummary=node("summary");this.storyText=node("p");story.append(this.storySummary,this.storyText);
      this.preview.append(this.previewImage,this.previewName,this.previewRole,this.previewIntro,story,this.state);
    }

    renderState(detail) {
      if(!this.stateIcon)return;
      const valid=detail && window.RadhouseIcons.agentStates.includes(detail.state);
      window.RadhouseIcons.setAgentState(this.stateIcon,valid?detail.state:"ready");
      this.stateText.textContent=valid ? detail.text : "Status unavailable";
    }

    updateActions() {
      if(!this.saveButton)return;
      this.saveButton.disabled=this.busy || !this.dirty || !this.valid(this.current);this.discardButton.disabled=this.busy || (!this.dirty && !this.remoteChanged);
      this.nameInput.setCustomValidity(textError(this.current.name,32));this.introInput.setCustomValidity(textError(this.current.intro,160,true));
      for(const control of this.form.querySelectorAll("input,textarea,button[role=tab]"))control.disabled=this.busy;
      this.suggest.disabled=this.busy;window.RadhouseIcons?.busy(this.saveButton,this.busy);
    }

    async discard() {
      if(this.busy || !this.saved)return;
      const restoreFocus=document.activeElement===this.discardButton;
      const reload=this.remoteChanged;this.current=clone(this.saved);this.render();this.present();this.updateActions();this.status.textContent="Changes discarded.";
      if(reload)await this.load();
      if(restoreFocus)this.form?.querySelector('[role="tab"][aria-selected="true"]')?.focus({preventScroll:true});
    }

    async save() {
      if(this.busy || !this.dirty || !this.valid(this.current))return;
      const epoch=this.epoch;this.busy=true;this.abort=new AbortController();this.status.textContent="Saving…";this.updateActions();
      try {
        const value=await this.request("/chat/agent-profile",clone(this.current),false,this.abort.signal);
        if(epoch!==this.epoch)return;
        if(!this.valid(value))throw new Error("invalid_agent_profile");
        this.saved=clone(value);this.current=clone(value);this.remoteChanged=false;this.present();this.status.textContent="Saved.";
        this.nameInput.value=value.name;this.introInput.value=value.intro;
        try{localStorage.setItem(signalKey,String(Date.now())+"-"+Math.random());}catch(_){/* Persistence belongs to the server. */}
      } catch(error) {
        if(epoch!==this.epoch)return;
        if(error.status===401){this.clear();this.onAuthRequired?.();return;}
        if(error.status===409 || error.message==="agent_profile_conflict"){
          this.remoteChanged=true;this.status.textContent="Saved settings changed in another tab. Your draft is kept. Discard to load the saved version.";
        }else this.status.textContent="Changes could not be saved. Your draft is kept. Try Save again.";
      } finally {
        if(epoch===this.epoch){this.busy=false;this.abort=null;this.updateActions();}
      }
    }
  }
  window.RadhouseAgentProfile=AgentProfile;
})();
