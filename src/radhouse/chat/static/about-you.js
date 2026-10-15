"use strict";
(() => {
  const sourceLabels = {user:"User notes",memory:"Agent notes"};
  const stateLabels = {empty:"No saved notes yet.",missing:"No saved notes file yet.",
    unreadable:"These saved notes could not be read. Refresh to check again.",
    too_large:"These notes are too large to display here. The original file is kept."};
  const node = (tag, text, className) => {
    const element=document.createElement(tag);
    if(text)element.textContent=text;
    if(className)element.className=className;
    return element;
  };
  const dateLabel = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : null;

  class AboutYou {
    constructor({container,request,onAuthRequired=null}) {
      this.container=container;this.request=request;this.onAuthRequired=onAuthRequired;
      this.epoch=0;this.controller=null;
      this.refresh=node("button","Refresh");this.refresh.type="button";
      window.RadhouseIcons?.decorate(this.refresh,"refresh","Refresh");
      this.refresh.addEventListener("click",()=>{void this.load();});
      this.status=node("p",null,"about-you-status");this.status.setAttribute("role","status");this.status.setAttribute("aria-live","polite");
      this.sources=node("div",null,"about-you-sources");
      this.container.replaceChildren(this.refresh,this.status,this.sources);
    }

    cancel() {
      this.epoch++;this.controller?.abort();this.controller=null;this.refresh.disabled=false;
      window.RadhouseIcons?.busy(this.refresh,false);
    }

    clear() {
      this.cancel();this.status.textContent="";this.sources.replaceChildren();
    }

    _render(value) {
      this.sources.replaceChildren();
      for(const source of value.sources) {
        const section=node("section",null,"about-you-source");
        section.append(node("h2",sourceLabels[source.target]));
        const description=source.target==="user" ? "Saved information about you." : "Your assistant’s saved notes.";
        section.append(node("p",description,"about-you-description"));
        const modified=dateLabel(source.file_modified_at);
        section.append(node("p",source.source_filename+(modified?" · Last changed "+modified:""),"about-you-source-meta"));
        if(source.state==="available") {
          const list=node("ul",null,"about-you-notes");
          for(const text of source.entries)list.append(node("li",text));
          section.append(list);
        } else section.append(node("p",stateLabels[source.state] || "These saved notes are unavailable.","about-you-empty"));
        this.sources.append(section);
      }
      const checked=dateLabel(value.checked_at);
      this.status.textContent=checked?"Checked "+checked:"Saved notes loaded.";
    }

    async load() {
      this.cancel();const epoch=this.epoch;
      const controller=new AbortController();this.controller=controller;
      this.refresh.disabled=true;this.status.textContent="Checking saved notes…";this.sources.replaceChildren();
      window.RadhouseIcons?.busy(this.refresh,true);
      try {
        const value=await this.request("/chat/about-you",undefined,false,controller.signal);
        if(epoch!==this.epoch)return;
        this._render(value);
      } catch(error) {
        if(epoch!==this.epoch)return;
        this.sources.replaceChildren();
        if(error.status===401) {this.clear();this.onAuthRequired?.();return;}
        this.status.textContent="Saved notes are unavailable right now. Refresh to try again.";
      } finally {
        if(epoch===this.epoch){this.controller=null;this.refresh.disabled=false;window.RadhouseIcons?.busy(this.refresh,false);}
      }
    }
  }
  window.RadhouseAboutYou=AboutYou;
})();
