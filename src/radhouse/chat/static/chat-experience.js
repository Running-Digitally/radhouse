"use strict";
// Navigation uses only loaded, owner-authorized turns; no transcript is persisted here.
window.RadhouseChatExperience = class {
  constructor({root, pane, messages, quote, onBrowse}) {
    this.pane=pane; this.messages=messages; this.quote=quote; this.onBrowse=onBrowse; this.rows=[];
    this.toolbar=document.createElement("div"); this.toolbar.className="conversation-toolbar";
    const heading=document.createElement("div"), title=document.createElement("strong"); title.textContent="Your conversation";
    this.status=document.createElement("span"); this.status.className="conversation-status"; this.status.setAttribute("role","status");
    heading.append(title,this.status);
    this.toggle=document.createElement("button"); this.toggle.type="button"; this.toggle.textContent="Find in conversation";
    this.toggle.setAttribute("aria-expanded","false"); this.toggle.setAttribute("aria-controls","conversation-finder");
    this.toolbar.append(heading,this.toggle);
    this.panel=document.createElement("section"); this.panel.id="conversation-finder"; this.panel.className="conversation-finder"; this.panel.hidden=true;
    const label=document.createElement("label"); label.textContent="Search loaded messages";
    this.search=document.createElement("input"); this.search.type="search"; this.search.placeholder="Find a question, reply, or idea…"; this.search.maxLength=200; label.append(this.search);
    this.count=document.createElement("p"); this.count.setAttribute("role","status");
    this.results=document.createElement("div"); this.results.className="conversation-results";
    this.panel.append(label,this.count,this.results); root.prepend(this.toolbar,this.panel);
    this.toggle.addEventListener("click",()=>this.setOpen(this.panel.hidden));
    this.search.addEventListener("input",()=>this.renderResults());
    this.panel.addEventListener("keydown",event=>{if(event.key==="Escape"){this.setOpen(false);this.toggle.focus();}});
  }
  setOpen(open) {
    this.panel.hidden=!open; this.toggle.setAttribute("aria-expanded",String(open));
    if(open){this.onBrowse();this.renderResults();this.search.focus();}
  }
  update(rows) {
    this.rows=rows;
    const active=rows.filter(row=>!['completed','failed','interrupted','cancelled'].includes(row.status));
    const status=active.length ? "Work in progress · you can leave and return" : "One conversation, wherever you return";
    if(this.status.textContent!==status)this.status.textContent=status;
    if(!this.panel.hidden)this.renderResults();
  }
  renderResults() {
    const query=this.search.value.trim().toLocaleLowerCase();
    const matches=this.rows.filter(row=>(row.text+"\n"+(row.output||"")).toLocaleLowerCase().includes(query));
    const shown=matches.slice(-50).reverse();
    const key=JSON.stringify([query,matches.length,shown.map(row=>[row.request_id,row.text,row.output])]);
    if(key===this.resultsKey)return;
    this.resultsKey=key;
    const focused=this.results.contains(document.activeElement) ? document.activeElement.dataset.searchRequestId : null;
    this.count.textContent=`${matches.length} matching exchanges in loaded history${matches.length>50 ? " · showing latest 50" : ""}. Load earlier messages to search more.`;
    this.results.replaceChildren(...shown.map(row=>{
      const button=document.createElement("button"); button.type="button";
      button.dataset.searchRequestId=row.request_id;
      const title=document.createElement("strong"), excerpt=document.createElement("span");
      title.textContent=(row.text || "Attached files").slice(0,140);
      excerpt.textContent=(row.output || "Reply pending").slice(0,160); button.append(title,excerpt);
      button.addEventListener("click",()=>{
        this.setOpen(false);this.onBrowse();
        const node=[...this.messages.children].find(item=>item.dataset.requestId===row.request_id);
        if(node){node.tabIndex=-1;node.focus({preventScroll:true});this.pane.scrollTop+=node.getBoundingClientRect().top-this.pane.getBoundingClientRect().top;}
      }); return button;
    }));
    if(focused){
      const next=[...this.results.children].find(node=>node.dataset.searchRequestId===focused);
      (next || this.search).focus({preventScroll:true});
    }
  }
  replyAction(turn) {
    const button=document.createElement("button"); button.type="button"; button.className="quote-answer"; button.textContent="Quote in reply";
    button.addEventListener("click",()=>this.quote(turn.output || turn.text)); return button;
  }
  clear() {this.rows=[];this.resultsKey=null;this.search.value="";this.results.replaceChildren();this.setOpen(false);this.status.textContent="";}
};
