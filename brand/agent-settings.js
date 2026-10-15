"use strict";
// A local, single-agent design fixture. No runtime or settings API is called.
(() => {
  const icons = window.RadhouseIcons;
  const key = "radhouse.design.agent-identity.v1";
  const {themes, profiles} = window.RadhouseCharacters;
  const accents = {fern:{name:"Fern",color:"#456d55",soft:"#eaf0e6"},clay:{name:"Clay",color:"#9a553b",soft:"#f5e9df"},tide:{name:"Tide",color:"#3d6574",soft:"#e5eef1"},plum:{name:"Plum",color:"#76576e",soft:"#efe7ec"}};
  const states = {thinking:["Thinking","Connecting the dots."],idle:["Idle","Here when you need me."],working:["Working","Making things happen."],waiting:["Waiting for you","A little input would help."],paused:["Paused","Taking a breather."],completed:["Completed","All wrapped up."]};
  const defaults = {name:"",intro:profiles[0].intro,portrait:"ember",customPortrait:null,accent:"fern",stateMotion:true,iconMotion:true,surface:"paper"};
  let saved = {...defaults}, draft, customName=false, customIntro=false, toastTimer, uploadGeneration=0;
  const byId = id => document.getElementById(id);
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const deviceNight = matchMedia("(prefers-color-scheme: dark)");
  const mobile = matchMedia("(max-width: 650px)");
  function validate(value) {
    if(!value || typeof value!=="object") return {...defaults};
    const portrait=profiles.some(p=>p.id===value.portrait)?value.portrait:"ember";
    return {name:typeof value.name==="string"?value.name.slice(0,32):"",intro:typeof value.intro==="string"?value.intro.slice(0,160):profiles.find(p=>p.id===portrait).intro,portrait,
      customPortrait:typeof value.customPortrait==="string" && /^data:image\/(png|jpeg|webp);base64,/.test(value.customPortrait) && value.customPortrait.length<=1500000?value.customPortrait:null,
      accent:Object.hasOwn(accents,value.accent)?value.accent:"fern",stateMotion:value.stateMotion!==false,iconMotion:value.iconMotion!==false,surface:["paper","night","system"].includes(value.surface)?value.surface:"paper"};
  }
  try {saved=validate(JSON.parse(localStorage.getItem(key)));} catch (_) { /* Optional local storage. */ }
  draft={...saved}; customName=Boolean(draft.name.trim() && draft.name!==profiles.find(p=>p.id===draft.portrait).name);customIntro=draft.intro!==profiles.find(p=>p.id===draft.portrait).intro;
  for(const node of document.querySelectorAll("[data-glyph]")) {
    const label=node.textContent.trim(), name=node.dataset.glyph;
    if(node.matches("button")) icons.decorate(node,name,label,{accessibleLabel:node.getAttribute("aria-label")||label});
    else node.append(icons.create(name));
  }
  function radio(name,value,label,checked) {
    const input=document.createElement("input"); input.type="radio";input.name=name;input.value=value;input.checked=checked;input.setAttribute("aria-label",label); return input;
  }
  // Theme, portrait and preview always describe the same identity.
  let selectedTheme=profiles.find(p=>p.id===draft.portrait).theme;
  let portraitByTheme={};
  function selectCharacter(profile) {
    uploadGeneration++;draft.portrait=profile.id;draft.customPortrait=null;
    portraitByTheme[profile.theme]=profile.id;
    if(!customName){draft.name=profile.name;byId("agent-name").value=draft.name;}
    if(!customIntro){draft.intro=profile.intro;byId("agent-intro").value=draft.intro;}
    for(const input of document.querySelectorAll('[name="portrait"]'))input.checked=input.value===profile.id;
    byId("upload-status").textContent="";update();
  }
  function renderPortraits() {
    const collection=themes.find(theme=>theme.id===selectedTheme);
    const members=profiles.filter(profile=>profile.theme===selectedTheme);
    const legend=document.createElement("legend");legend.className="sr-only";legend.textContent=`Choose a ${collection.name} character`;
    byId("character-grid").replaceChildren(legend);
    byId("character-grid").style.setProperty("--portrait-count",members.length);
    byId("character-grid").dataset.count=members.length;
    byId("collection-title").textContent=collection.name;
    for(const profile of members) {
      const label=document.createElement("label");label.className="character-option";
      const input=radio("portrait",profile.id,`${profile.name} · ${collection.name}`,draft.portrait===profile.id&&!draft.customPortrait);
      const top=document.createElement("div");top.className="character-top";
      const image=document.createElement("img");image.src=`characters/${profile.id}.png`;image.alt="";image.width=88;image.height=88;
      const caption=document.createElement("div"),name=document.createElement("span"),role=document.createElement("span");
      name.className="character-name";name.textContent=profile.name;role.className="character-theme";role.textContent=profile.role;caption.append(name,role);top.append(image,caption);
      const check=document.createElement("span");check.className="character-check";check.append(icons.create("check"));
      label.append(input,top,check);byId("character-grid").append(label);
      input.addEventListener("change",()=>selectCharacter(profile));
    }
    for(const input of document.querySelectorAll('[name="collection"]'))input.checked=input.value===selectedTheme;
  }
  function chooseTheme(id) {
    selectedTheme=id;renderPortraits();
    const members=profiles.filter(profile=>profile.theme===id);
    selectCharacter(members.find(profile=>profile.id===portraitByTheme[id])||members[0]);
  }
  for(const theme of themes) {
    const label=document.createElement("label");label.className="theme-option";
    const input=radio("collection",theme.id,theme.name,selectedTheme===theme.id);input.setAttribute("aria-controls","character-grid");
    const portraits=document.createElement("span");portraits.className="theme-portraits";portraits.setAttribute("aria-hidden","true");
    for(const profile of profiles.filter(profile=>profile.theme===theme.id).slice(0,3)) {
      const image=document.createElement("img");image.src=`characters/${profile.id}.png`;image.alt="";image.width=44;image.height=44;portraits.append(image);
    }
    const text=document.createElement("span"),name=document.createElement("strong"),style=document.createElement("small");
    name.textContent=theme.name;style.textContent=theme.style;text.append(name,style);
    label.append(input,portraits,text);byId("theme-options").append(label);
    input.addEventListener("change",()=>chooseTheme(theme.id));
  }
  for(const [id,accent] of Object.entries(accents)) {
    const label=document.createElement("label");label.className="accent-option";label.style.setProperty("--swatch",accent.color);
    const input=radio("accent",id,accent.name,draft.accent===id),swatch=document.createElement("span"),name=document.createElement("span");
    swatch.className="swatch";name.textContent=accent.name;label.append(input,swatch,name);byId("accent-options").append(label);
    input.addEventListener("change",()=>{draft.accent=id;update();});
  }
  function createStatus(state) {
    const svg=icons.create("agent");
    icons.setAgentState(svg,state==="completed"?"complete":state);
    svg.classList.add("agent-status-svg");
    return svg;
  }
  const stateSequence=["idle","thinking","working","waiting","paused","completed"];
  let pinnedState="thinking",hoveredState=null,focusedState=null;
  function renderPreviewState() {
    const state=hoveredState||focusedState||pinnedState;
    for(const node of document.querySelectorAll("[data-status-icon]"))node.replaceChildren(createStatus(state));
    for(const node of document.querySelectorAll("[data-state-label]"))node.textContent=states[state][0];
    byId("state-description").textContent=states[state][1];
    byId("header-status").setAttribute("aria-label",`Show agent state preview: ${states[state][0]}`);
    for(const button of byId("state-options").querySelectorAll("button")) {
      button.setAttribute("aria-pressed",String(button.dataset.state===pinnedState));
      button.dataset.previewing=String(button.dataset.state===state);
    }
  }
  for(const [index,state] of stateSequence.entries()) {
    const button=document.createElement("button");button.type="button";button.className="state-chip";
    button.dataset.state=state;button.style.setProperty("--state-index",index);
    button.tabIndex=state===pinnedState?0:-1;button.setAttribute("aria-label",`Preview ${states[state][0]}`);
    const text=document.createElement("span");text.textContent=states[state][0];button.append(createStatus(state),text);
    byId("state-options").append(button);
    button.addEventListener("pointerenter",event=>{if(event.pointerType!=="touch"){hoveredState=state;focusedState=null;renderPreviewState();}});
    button.addEventListener("pointerleave",()=>{const changed=hoveredState===state||focusedState===state;if(hoveredState===state)hoveredState=null;if(focusedState===state)focusedState=null;if(changed)renderPreviewState();});
    button.addEventListener("focus",()=>{focusedState=state;hoveredState=null;renderPreviewState();});
    button.addEventListener("blur",()=>{if(focusedState===state){focusedState=null;renderPreviewState();}});
    button.addEventListener("click",()=>{
      pinnedState=state;
      for(const choice of byId("state-options").querySelectorAll("button"))choice.tabIndex=choice===button?0:-1;
      renderPreviewState();
    });
    button.addEventListener("keydown",event=>{
      if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Home","End"].includes(event.key))return;
      event.preventDefault();const buttons=[...byId("state-options").querySelectorAll("button")];
      const next=event.key==="Home"?0:event.key==="End"?buttons.length-1:(index+(["ArrowLeft","ArrowUp"].includes(event.key)?-1:1)+buttons.length)%buttons.length;
      for(const choice of buttons)choice.tabIndex=choice===buttons[next]?0:-1;
      buttons[next].focus();
    });
  }
  function dirty() {return JSON.stringify(draft)!==JSON.stringify(saved);}
  function cancelIconMotion() {for(const icon of document.querySelectorAll(".rh-icon:not(.agent-status-svg)")) for(const animation of icon.getAnimations({subtree:true})) animation.cancel();}
  for(const event of ["click","pointerenter","focus"])document.addEventListener(event,()=>{if(!draft.iconMotion)queueMicrotask(cancelIconMotion);},true);
  function update() {
    const name=draft.name.trim()||"Your Agent",profile=profiles.find(p=>p.id===draft.portrait),accent=accents[draft.accent];
    const surface=draft.surface==="system"?(deviceNight.matches?"night":"paper"):draft.surface;
    document.body.dataset.surface=surface;
    const nightAccents={fern:["#b7cda8","#354a3b"],clay:["#dfad90","#504036"],tide:["#a6cad6","#334a51"],plum:["#ccabc1","#4b3b47"]};
    document.body.style.setProperty("--accent",surface==="night"?nightAccents[draft.accent][0]:accent.color);
    document.body.style.setProperty("--soft",surface==="night"?nightAccents[draft.accent][1]:accent.soft);
    document.body.dataset.stateMotion=draft.stateMotion?"on":"off";document.body.dataset.iconMotion=draft.iconMotion?"on":"off";
    if(!draft.iconMotion)cancelIconMotion();
    for(const node of document.querySelectorAll("[data-name]"))node.textContent=name;
    for(const image of document.querySelectorAll("[data-portrait]"))image.src=draft.customPortrait||`characters/${profile.id}.png`;
    byId("open-profile").setAttribute("aria-label",`Customize ${name}`);
    document.title=`${name} · Radhouse`;
    byId("preview-intro").textContent=draft.intro.trim();
    byId("sample-reply").textContent=profile.reply;
    byId("profile-role").textContent=draft.customPortrait?"Your own portrait":`${profile.role} · ${themes.find(theme=>theme.id===profile.theme).name}`;
    byId("profile-story").textContent=profile.story;byId("character-story-label").textContent=`About ${profile.name}`;
    byId("character-notes").hidden=Boolean(draft.customPortrait);
    byId("suggest-name").textContent=`Use ${profile.name}`;byId("suggest-name").setAttribute("aria-label",`Use ${profile.name} as agent name`);byId("suggest-name").hidden=draft.name===profile.name;
    renderPreviewState();
    byId("save").disabled=!dirty();byId("discard").disabled=!dirty();
    byId("save-status").textContent=dirty()?"Unsaved changes":"Make yourself at home.";
    byId("motion-note").textContent=reducedMotion.matches?"Your device prefers reduced motion. Animations are paused; status labels stay visible.":"Your device’s reduced-motion preference is always respected.";
  }
  function syncInputs() {
    selectedTheme=profiles.find(profile=>profile.id===draft.portrait).theme;portraitByTheme={[selectedTheme]:draft.portrait};renderPortraits();
    byId("intro-disclosure").open=customIntro;
    byId("agent-name").value=draft.name;byId("agent-intro").value=draft.intro;byId("state-motion").checked=draft.stateMotion;byId("icon-motion").checked=draft.iconMotion;
    for(const input of document.querySelectorAll('[name="portrait"]'))input.checked=input.value===draft.portrait&&!draft.customPortrait;
    for(const input of document.querySelectorAll('[name="accent"]'))input.checked=input.value===draft.accent;
    for(const input of document.querySelectorAll('[name="surface"]'))input.checked=input.value===draft.surface;
    byId("upload-status").textContent=draft.customPortrait?"Your uploaded portrait is selected.":"";update();
  }
  function showTab(tab,focus=false) {
    for(const id of ["identity","appearance"]) {const selected=id===tab;byId(id+"-tab").setAttribute("aria-selected",String(selected));byId(id+"-tab").tabIndex=selected?0:-1;byId(id+"-panel").hidden=!selected;}
    if(focus)byId(tab+"-tab").focus();
  }
  function menu(open,returnFocus=true) {
    const sidebar=byId("main-sidebar");sidebar.dataset.open=String(open);
    byId("open-menu").setAttribute("aria-expanded",String(open));
    byId("drawer-backdrop").hidden=!open;
    for(const node of [document.querySelector(".app-header"),byId("main")])node.inert=open;
    if(open){sidebar.setAttribute("role","dialog");sidebar.setAttribute("aria-modal","true");sidebar.setAttribute("aria-label","Navigation");byId("close-menu").focus();}
    else{sidebar.removeAttribute("role");sidebar.removeAttribute("aria-modal");sidebar.removeAttribute("aria-label");if(returnFocus&&mobile.matches)byId("open-menu").focus();}
  }
  byId("open-menu").addEventListener("click",()=>menu(true));
  byId("close-menu").addEventListener("click",()=>menu(false));
  byId("drawer-backdrop").addEventListener("click",()=>menu(false));
  document.addEventListener("keydown",event=>{
    if(byId("main-sidebar").dataset.open!=="true")return;
    if(event.key==="Escape"){event.preventDefault();menu(false);}
    if(event.key==="Tab"){
      const nodes=[...byId("main-sidebar").querySelectorAll("button,a[href]")],first=nodes[0],last=nodes.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  document.querySelector(".nav-agent").addEventListener("click",()=>{if(mobile.matches)menu(false,false);showTab("identity",true);});
  for(const tab of ["identity","appearance"]) {
    byId(tab+"-tab").addEventListener("click",()=>showTab(tab));
    byId(tab+"-tab").addEventListener("keydown",event=>{if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)){event.preventDefault();showTab(event.key==="Home"?"identity":event.key==="End"?"appearance":tab==="identity"?"appearance":"identity",true);}});
  }
  byId("open-profile").addEventListener("click",()=>{showTab("identity");byId("main").scrollIntoView({block:"start"});byId("theme-options").querySelector("input:checked").focus({preventScroll:true});});
  byId("nav-settings").addEventListener("click",()=>{if(mobile.matches)menu(false,false);showTab("appearance",true);byId("appearance-tab").scrollIntoView({block:"center"});});
  for(const button of document.querySelectorAll("[data-nav]"))button.addEventListener("click",()=>toast("This preview focuses on your agent’s identity and appearance."));
  byId("agent-name").addEventListener("input",event=>{draft.name=event.target.value;customName=Boolean(draft.name.trim());update();});
  byId("agent-intro").addEventListener("input",event=>{draft.intro=event.target.value;customIntro=true;update();});
  byId("suggest-name").addEventListener("click",()=>{draft.name=profiles.find(p=>p.id===draft.portrait).name;customName=false;byId("agent-name").value=draft.name;update();});
  byId("state-motion").addEventListener("change",event=>{draft.stateMotion=event.target.checked;update();});
  byId("icon-motion").addEventListener("change",event=>{draft.iconMotion=event.target.checked;update();});
  for(const input of document.querySelectorAll('[name="surface"]'))input.addEventListener("change",()=>{draft.surface=input.value;update();});
  byId("header-status").addEventListener("click",()=>{byId("live-preview").scrollIntoView({block:"center"});byId("state-options").querySelector(`[data-state="${pinnedState}"]`).focus({preventScroll:true});});
  byId("identity-form").addEventListener("submit",event=>{
    event.preventDefault();let persisted=true;
    try {localStorage.setItem(key,JSON.stringify(draft));}catch(_){persisted=false;}
    if(persisted){saved={...draft};update();byId("save-status").textContent="Saved in this browser preview.";toast("Your agent feels a little more like yours.");}
    else{byId("save-status").textContent="Couldn’t save in this browser. Your changes are still here.";toast("Local storage is unavailable. Your changes remain unsaved.");}
  });
  byId("discard").addEventListener("click",()=>{uploadGeneration++;draft={...saved};customName=Boolean(draft.name.trim() && draft.name!==profiles.find(p=>p.id===draft.portrait).name);customIntro=draft.intro!==profiles.find(p=>p.id===draft.portrait).intro;syncInputs();});
  byId("reset").addEventListener("click",()=>{uploadGeneration++;draft={...defaults};customName=false;customIntro=false;syncInputs();toast("Default identity restored. Save to keep it.");});
  function toast(text) {clearTimeout(toastTimer);byId("toast").textContent=text;byId("toast").hidden=false;toastTimer=setTimeout(()=>{byId("toast").hidden=true;},3200);}
  byId("upload-button").addEventListener("click",()=>byId("portrait-file").click());
  byId("portrait-file").addEventListener("change",async event=>{
    const file=event.target.files[0],generation=++uploadGeneration;event.target.value="";if(!file)return;
    if(!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>1024*1024){byId("upload-status").textContent="Choose a PNG, JPEG, or WebP image up to 1 MB.";return;}
    try {
      const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
      const image=new Image();image.src=data;await image.decode();
      if(generation!==uploadGeneration)return;
      if(image.naturalWidth>8192||image.naturalHeight>8192){byId("upload-status").textContent="Choose an image up to 8192 pixels on each side.";return;}
      draft.customPortrait=data;
      for(const input of document.querySelectorAll('[name="portrait"]'))input.checked=false;
      byId("upload-status").textContent="Your portrait is ready. Save changes to keep it.";update();
    }catch(_){if(generation===uploadGeneration)byId("upload-status").textContent="That image couldn’t be opened. Try another portrait.";}
  });
  byId("copy-sample").addEventListener("click",async()=>{try{await navigator.clipboard.writeText(byId("sample-reply").textContent);toast("Copied.");}catch(_){toast("Copy is unavailable in this browser.");}});
  reducedMotion.addEventListener("change",update);deviceNight.addEventListener("change",update);
  mobile.addEventListener("change",()=>menu(false,false));
  syncInputs();
})();
