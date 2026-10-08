"use strict";
// A local, single-agent design fixture. No runtime or settings API is called.
(() => {
  const icons = window.RadhouseIcons;
  const key = "radhouse.design.agent-identity.v1";
  const profiles = [
    {id:"ember",name:"Ember",theme:"Hearth",story:"Once the keeper of a tiny hillside inn. Now keeps the light on while you find your next good idea.",intro:"Keeps the light on while you find your next good idea.",reply:"Of course. Let’s put the kettle on and start with what matters."},
    {id:"moss",name:"Moss",theme:"Grove",story:"A collector of overlooked details and well-thumbed notebooks. Believes good ideas grow with a little patience.",intro:"Good ideas grow with a little patience.",reply:"Let’s look a little closer. There’s usually something useful hiding in the details."},
    {id:"aster",name:"Aster",theme:"Orbit",story:"A quiet navigator with a sky full of questions. Turns faraway possibilities into a next step you can take.",intro:"Faraway possibilities. A next step you can take.",reply:"Absolutely. Let’s map what we know, then find a promising direction."},
    {id:"lumi",name:"Lumi",theme:"Fable",story:"A moonlit storyteller who sees connections others miss. Makes a little room for the unexpected.",intro:"Makes a little room for the unexpected.",reply:"Yes. Let’s follow the interesting thread and see what it brings into view."}
  ];
  const accents = {fern:{name:"Fern",color:"#456d55",soft:"#eaf0e6"},clay:{name:"Clay",color:"#9a553b",soft:"#f5e9df"},tide:{name:"Tide",color:"#3d6574",soft:"#e5eef1"},plum:{name:"Plum",color:"#76576e",soft:"#efe7ec"}};
  const states = {thinking:["Thinking","Connecting the dots."],idle:["Idle","Here when you need me."],working:["Working","Making things happen."],waiting:["Waiting for you","A little input would help."],paused:["Paused","Taking a breather."],completed:["Completed","All wrapped up."]};
  const defaults = {name:"",intro:profiles[0].intro,portrait:"ember",customPortrait:null,accent:"fern",stateMotion:true,iconMotion:true,surface:"paper"};
  let saved = {...defaults}, draft, customName=false, customIntro=false, previewState="thinking", toastTimer, uploadGeneration=0;
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
  draft={...saved}; customName=Boolean(draft.name);customIntro=draft.intro!==profiles.find(p=>p.id===draft.portrait).intro;
  for(const node of document.querySelectorAll("[data-glyph]")) {
    const label=node.textContent.trim(), name=node.dataset.glyph;
    if(node.matches("button")) icons.decorate(node,name,label,{accessibleLabel:node.getAttribute("aria-label")||label});
    else node.append(icons.create(name));
  }
  function radio(name,value,label,checked) {
    const input=document.createElement("input"); input.type="radio";input.name=name;input.value=value;input.checked=checked;input.setAttribute("aria-label",label); return input;
  }
  for(const profile of profiles) {
    const label=document.createElement("label");label.className="character-option";
    const input=radio("portrait",profile.id,`${profile.name} · ${profile.theme}`,draft.portrait===profile.id&&!draft.customPortrait);
    const top=document.createElement("div");top.className="character-top";
    const image=document.createElement("img");image.src=`characters/${profile.id}.png`;image.alt="";
    const caption=document.createElement("div"),name=document.createElement("span"),theme=document.createElement("span");
    name.className="character-name";name.textContent=profile.name;theme.className="character-theme";theme.textContent=profile.theme;caption.append(name,theme);top.append(image,caption);
    const story=document.createElement("p");story.className="character-story";story.textContent=profile.story;
    const check=document.createElement("span");check.className="character-check";check.append(icons.create("check"));
    label.append(input,top,story,check);byId("character-grid").append(label);
    input.addEventListener("change",()=>{
      uploadGeneration++;draft.portrait=profile.id;draft.customPortrait=null;
      if(!customName){draft.name=profile.name;byId("agent-name").value=draft.name;}
      if(!customIntro){draft.intro=profile.intro;byId("agent-intro").value=draft.intro;}
      byId("upload-status").textContent="";update();
    });
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
    for(const node of document.querySelectorAll("[data-status-icon]"))node.replaceChildren(createStatus(previewState));
    for(const node of document.querySelectorAll("[data-state-label]"))node.textContent=states[previewState][0];
    byId("state-description").textContent=states[previewState][1];
    byId("header-status").setAttribute("aria-label",`Preview agent status: ${states[previewState][0]}`);
    byId("save").disabled=!dirty();byId("discard").disabled=!dirty();
    byId("save-status").textContent=dirty()?"Unsaved changes":"Make yourself at home.";
    byId("motion-note").textContent=reducedMotion.matches?"Your device prefers reduced motion. Animations are paused; status labels stay visible.":"Your device’s reduced-motion preference is always respected.";
  }
  function syncInputs() {
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
  byId("open-profile").addEventListener("click",()=>{showTab("identity");byId("main").scrollIntoView({block:"start"});byId("agent-name").focus({preventScroll:true});});
  byId("nav-settings").addEventListener("click",()=>{if(mobile.matches)menu(false,false);showTab("appearance",true);byId("appearance-tab").scrollIntoView({block:"center"});});
  for(const button of document.querySelectorAll("[data-nav]"))button.addEventListener("click",()=>toast("This preview focuses on your agent’s identity and appearance."));
  byId("agent-name").addEventListener("input",event=>{draft.name=event.target.value;customName=Boolean(draft.name.trim());update();});
  byId("agent-intro").addEventListener("input",event=>{draft.intro=event.target.value;customIntro=true;update();});
  byId("suggest-name").addEventListener("click",()=>{draft.name=profiles.find(p=>p.id===draft.portrait).name;customName=false;byId("agent-name").value=draft.name;update();});
  byId("state-motion").addEventListener("change",event=>{draft.stateMotion=event.target.checked;update();});
  byId("icon-motion").addEventListener("change",event=>{draft.iconMotion=event.target.checked;update();});
  for(const input of document.querySelectorAll('[name="surface"]'))input.addEventListener("change",()=>{draft.surface=input.value;update();});
  byId("preview-state").addEventListener("change",event=>{previewState=event.target.value;update();});
  byId("header-status").addEventListener("click",()=>{const ids=Object.keys(states);previewState=ids[(ids.indexOf(previewState)+1)%ids.length];byId("preview-state").value=previewState;update();toast(`Previewing: ${states[previewState][0]}`);});
  byId("identity-form").addEventListener("submit",event=>{
    event.preventDefault();let persisted=true;
    try {localStorage.setItem(key,JSON.stringify(draft));}catch(_){persisted=false;}
    if(persisted){saved={...draft};update();byId("save-status").textContent="Saved in this browser preview.";toast("Your agent feels a little more like yours.");}
    else{byId("save-status").textContent="Couldn’t save in this browser. Your changes are still here.";toast("Local storage is unavailable. Your changes remain unsaved.");}
  });
  byId("discard").addEventListener("click",()=>{uploadGeneration++;draft={...saved};customName=Boolean(draft.name);customIntro=draft.intro!==profiles.find(p=>p.id===draft.portrait).intro;syncInputs();});
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
