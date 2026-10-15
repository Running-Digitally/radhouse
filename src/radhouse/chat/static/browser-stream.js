"use strict";
(() => {
  // Presentation only. Selkies and the server's generation/lease gate own input.
  class BrowserStream {
    constructor(view) {
      this.view=view;this.info=null;this.preview=false;this.visible=true;this.presented=false;
      this.input={ready:false,touch:matchMedia('(pointer:coarse)').matches,hardware:false,focused:false};
      this.frame=document.createElement('iframe');this.frame.className='browser-stream-frame';
      this.frame.title='Live assistant browser';this.frame.allow='clipboard-read; clipboard-write';this.frame.tabIndex=-1;
      this.tools=document.createElement('div');this.tools.className='browser-stream-tools';this.tools.hidden=true;
      const button=(label,action)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',action);return b;};
      this.keyboard=button('Keyboard',()=>this.invoke('show',false));
      this.keys=button('Keys',()=>this.toggleKeys(this.panel.hidden));this.keys.setAttribute('aria-expanded','false');
      this.panel=document.createElement('div');this.panel.className='browser-stream-keys';this.panel.hidden=true;
      this.panel.id='browser-keys-'+crypto.randomUUID();this.panel.setAttribute('role','group');this.panel.setAttribute('aria-label','Browser keys');this.keys.setAttribute('aria-controls',this.panel.id);
      this.panel.append(button('Keyboard',()=>this.invoke('show',true)));
      for(const [name,label]of [['address','Address bar'],['tab','Tab'],['enter','Enter'],['backspace','Backspace'],['escape','Escape']])this.panel.append(button(label,()=>this.invoke('press',name)));
      this.panel.append(button('Dismiss keyboard',()=>this.hideKeyboard()));
      this.fit=button('Fit',()=>view.viewport.classList.remove('browser-stream-zoom'));
      this.zoom=button('Zoom',()=>view.viewport.classList.add('browser-stream-zoom'));
      this.tools.append(this.keyboard,this.keys,this.fit,this.zoom,this.panel);view.viewport.before(this.tools);
      this.privacy=document.createElement('div');this.privacy.className='browser-privacy';this.privacy.hidden=true;this.privacy.setAttribute('role','group');this.privacy.setAttribute('aria-label','Agent visibility during your takeover');
      this.privateButton=button('Private',()=>this.changeMode('private'));
      this.observeButton=button('Let agent observe',()=>this.changeMode('observe'));
      this.privacyText=document.createElement('span');this.privacyText.setAttribute('role','status');
      this.privacy.append(this.privateButton,this.observeButton,this.privacyText);this.tools.before(this.privacy);
      this.notice=document.createElement('p');this.notice.className='browser-stream-notice';this.notice.setAttribute('role','status');this.notice.hidden=true;this.tools.after(this.notice);
      this.message=event=>{
        if(event.origin!==location.origin||event.source!==this.frame.contentWindow)return;
        if(event.data?.type==='mobileInputStatus'&&['ready','touch','hardware','focused'].every(k=>typeof event.data[k]==='boolean')){
          this.input=event.data;this.render();
          view.container.dispatchEvent(new CustomEvent('browser-input-focus',{bubbles:true,detail:{focused:this.input.focused}}));
        }
        if(event.data?.type==='framePresented'){this.presented=true;this.render();}
      };
      window.addEventListener('message',this.message);
      this.focus=event=>{if(event.target.closest?.('#compose'))this.hideKeyboard();};document.addEventListener('focusin',this.focus);
    }
    get enabled(){return this.info!==null;}
    update(value){
      const stream=value?.stream;
      if(!stream){this.clear();return;}
      if(stream.path!=='/chat/browser/stream/index.html'||typeof stream.token!=='string'||!/^[-_A-Za-z0-9]{32,128}$/.test(stream.token)){
        this.clear();return;
      }
      if(this.info?.token!==stream.token || this.streamGeneration!==this.view.generation){this.connectionNonce=crypto.randomUUID();this.streamGeneration=this.view.generation;}
      this.info={path:stream.path,token:stream.token};this.mount();this.render();
    }
    mount(){
      if(!this.info||!this.visible)return;
      const url=this.info.path+'?connection='+encodeURIComponent(this.connectionNonce)+'#token='+encodeURIComponent(this.info.token);
      if(this.frame.getAttribute('src')!==url){this.hideKeyboard();this.input.ready=false;this.presented=false;this.frame.src=url;}
      if(!this.frame.isConnected)this.view.viewport.append(this.frame);
      this.view.image.hidden=true;this.view.viewport.hidden=false;
    }
    render(){
      if(!this.info)return;
      const view=this.view,human=view._human(),touch=this.input.touch||matchMedia('(pointer:coarse)').matches;
      view.container.classList.add('browser-view--streaming');view.viewport.hidden=!view.active;
      view.toolbar.hidden=true;view.keyboard.hidden=true;
      view._decorate(view.take,'pointer','Take control privately');
      const mode=view.control?.observation_mode==='observe'?'observe':'private';
      this.privacy.hidden=!human||this.preview;
      this.privateButton.setAttribute('aria-pressed',String(mode==='private'));
      this.observeButton.setAttribute('aria-pressed',String(mode==='observe'));
      this.privateButton.disabled=this.observeButton.disabled=view.actionPending;
      this.privacyText.textContent=mode==='observe'?'Agent can read this page when you ask in chat. You keep control.':'Private. Only you can see the page.';
      view.connection.textContent=this.presented?'Live':'Connecting';view.connection.dataset.state=this.presented?'live':'pending';
      this.tools.hidden=!view.active||this.preview;
      this.keyboard.hidden=!human||!touch||this.input.hardware;this.keys.hidden=!human||!touch;
      for(const b of [this.keyboard,this.keys,...this.panel.querySelectorAll('button')])b.disabled=!human||!this.input.ready||view.actionPending;
      if(!human||this.preview){this.hideKeyboard();this.toggleKeys(false);}
    }
    async changeMode(mode){
      if(!this.view._human()||this.view.actionPending)return;
      const value=await this.view._act('/chat/browser/control/visibility',{...this.view._binding(),mode});
      if(!value&&mode==='private'){
        this.notice.textContent='Privacy change is not confirmed. Wait for Private before entering sensitive information.';this.notice.hidden=false;
      }
    }
    invoke(method,arg){
      if(this.preview||!this.view._human()||this.view.actionPending||!this.input.ready)return;
      if(!this.frame.contentWindow?.radhouseInput?.[method](arg)){
        this.notice.textContent='Browser input is connecting. Try again in a moment.';this.notice.hidden=false;
      }else{this.notice.hidden=true;this.view.container.dispatchEvent(new CustomEvent('browser-activity',{bubbles:true}));}
    }
    toggleKeys(open){this.panel.hidden=!open;this.keys.setAttribute('aria-expanded',String(open));}
    hideKeyboard(){this.frame.contentWindow?.radhouseInput?.hide();}
    presentation({preview,visible}){
      if(preview&&!this.preview)this.hideKeyboard();this.preview=preview;this.visible=visible;
      this.view.body.inert=preview;this.frame.inert=preview;
      if(visible)this.mount();else if(this.frame.isConnected){this.hideKeyboard();this.frame.remove();this.frame.removeAttribute('src');this.presented=false;}
      this.render();
    }
    clear(){
      this.hideKeyboard();this.frame.remove();this.frame.removeAttribute('src');this.info=null;this.input.ready=false;
      this.presented=false;this.tools.hidden=true;this.privacy.hidden=true;this.notice.hidden=true;this.toggleKeys(false);
      this.view.container.classList.remove('browser-view--streaming');this.view.body.inert=false;
    }
    destroy(){this.clear();window.removeEventListener('message',this.message);document.removeEventListener('focusin',this.focus);}
  }
  window.RadhouseBrowserStream=BrowserStream;
})();
