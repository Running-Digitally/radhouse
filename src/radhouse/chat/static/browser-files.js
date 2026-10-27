"use strict";
(() => {
  class BrowserFiles {
    constructor(view, upload) {
      this.view=view; this.upload=upload; this.pending=false; this.lastPoll=0; this.epoch=0;
      this.dialog=document.createElement("dialog"); this.dialog.className="browser-file-picker";
      this.transferStatus=document.createElement("p");this.transferStatus.setAttribute("role","status");
      this.transferStatus.hidden=true;view.body?.append(this.transferStatus);
      const title=document.createElement("h2"); title.textContent="Choose a file";
      this.destination=document.createElement("p");
      this.note=document.createElement("p"); this.note.setAttribute("role","status");
      const device=document.createElement("button"); device.type="button"; device.textContent="Your device";
      this.device=document.createElement("input"); this.device.type="file"; this.device.hidden=true;
      device.addEventListener("click",()=>this.device.click());
      this.device.addEventListener("change",()=>{const file=this.device.files[0]; if(file)void this.sendDevice(file);});
      this.search=document.createElement("input"); this.search.type="search"; this.search.placeholder="Search Library";
      this.search.setAttribute("aria-label","Search Library");
      this.search.addEventListener("input",()=>{clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>void this.load(),250);});
      const label=document.createElement("h3"); label.textContent="Library";
      this.list=document.createElement("div"); this.list.className="browser-file-list";
      this.more=document.createElement("button"); this.more.type="button"; this.more.textContent="Show more";
      this.more.addEventListener("click",()=>void this.load(true));
      const cancel=document.createElement("button"); cancel.type="button"; cancel.textContent="Cancel";
      cancel.addEventListener("click",()=>this.dialog.close());
      this.dialog.addEventListener("close",()=>{this.dismissed=this.chooser?.id;this.epoch++;});
      this.dialog.append(title,this.destination,device,this.device,label,this.search,this.list,this.more,this.note,cancel);
      document.body.append(this.dialog);
    }

    update(value) {
      this.enabled=value?.files_enabled===true;
      this.transferStatus.hidden=!this.enabled;
      this.transferStatus.textContent=value?.downloads?.unavailable ? "Downloads couldn’t be saved yet. Reconnect to check again." :
        value?.downloads?.saving ? "Saving downloads to Library…" : "Downloads are saved to Library automatically.";
      if(!this.enabled || !this.view._human()) {
        this.chooser=null; if(this.dialog.open)this.dialog.close(); return;
      }
      if(this.pending || Date.now()-this.lastPoll<1500)return;
      this.lastPoll=Date.now(); void this.poll();
    }

    async poll() {
      this.pending=true; const binding=this.view._binding();
      try {
        const result=await this.view.request("/chat/browser/files",binding);
        if(this.view.generation!==binding.generation || !this.view._human())return;
        if(!result.chooser) {this.chooser=null;if(this.dialog.open)this.dialog.close();return;}
        if(result.chooser.id===this.chooser?.id || result.chooser.id===this.dismissed)return;
        this.chooser=result.chooser; this.binding=binding;
        this.destination.textContent="Upload to "+new URL(this.chooser.destination).origin;
        this.note.textContent="Downloads are saved to Library automatically.";
        this.device.value="";this.search.value="";this.dialog.showModal();await this.load();
      } catch { /* Existing browser status owns connection recovery. */ }
      finally {this.pending=false;}
    }

    async load(append=false) {
      const epoch=++this.epoch;
      const params=new URLSearchParams({query:this.search.value});
      if(append && this.cursor)params.set("before",this.cursor);
      try {
        const result=await this.view.request("/chat/library?"+params,undefined,"GET");
        if(epoch!==this.epoch || !this.dialog.open)return;
        if(!append)this.list.replaceChildren();
        for(const file of result.files) {
          if(!file.file_id)continue;
          const button=document.createElement("button");button.type="button";
          button.textContent=file.name+(file.private ? " · Private" : "");
          button.addEventListener("click",()=>void this.send(file.file_id));this.list.append(button);
        }
        this.cursor=result.next_cursor;this.more.hidden=!this.cursor;
        if(!this.list.children.length)this.list.textContent="No files here yet. Choose one from your device.";
      } catch {this.note.textContent="Library couldn’t be loaded. Search again to retry.";}
    }

    busy(value) {
      this.pending=value;
      for(const button of this.dialog.querySelectorAll("button,input"))button.disabled=value;
    }

    async sendDevice(blob) {
      const chooser=this.chooser;
      this.busy(true);this.note.textContent="Saving to Library…";
      try {
        // A device file selected in the shared browser stays private until explicitly shared.
        const file_id=await this.upload(blob,true);
        if(this.chooser!==chooser || !this.dialog.open)return;
        await this.send(file_id);
      } catch {this.note.textContent="The file couldn’t be saved. Your device original is unchanged.";}
      finally {this.busy(false);}
    }

    async send(file_id) {
      const chooser=this.chooser;
      if(!chooser || !this.view._human())return;
      this.busy(true);this.note.textContent="Uploading…";
      try {
        const result=await this.view.request("/chat/browser/files/upload",{...this.view._binding(),
          file_id,chooser:chooser.id,destination:chooser.destination});
        if(result.applied!==true)throw new Error("unconfirmed");
        this.view.actionNotice="File uploaded. The original is in Library.";
        this.view._renderControlState();this.dialog.close();
      } catch {this.note.textContent="Upload wasn’t confirmed. Check the website, then choose its file button again. Your Library file is safe.";}
      finally {this.busy(false);}
    }
  }
  window.RadhouseBrowserFiles=BrowserFiles;
})();
