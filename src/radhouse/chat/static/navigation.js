"use strict";

// Original Radhouse glyphs. Named parts let the motion express the action.
// 24-unit grid, 1.7-unit round stroke, currentColor; no dependency or asset API.
window.RadhouseIcons = (() => {
  const paths = Object.freeze({
    chat: [["M7 4h10a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4h-6l-5 3v-3a3 3 0 0 1-3-3V8a4 4 0 0 1 4-4Z","shell"],["M8 9h8","write1"],["M8 13h5","write2"]],
    library: [["M3 8h18v10q0 2-2 2H5q-2 0-2-2Z","shell"],["M3 8V6q0-1 1-1h6l2 3","lid"],["M7 12h10","write1"],["M7 16h7","write2"]],
    browser: [["M4 3h16q1 0 1 1v16q0 1-1 1H4q-1 0-1-1V4q0-1 1-1Z","shell"],["M3 9h4V6h6v3h8","tab"],["M7 13h10","write1"],["M7 17h6","write2"]],
    settings: [["M4 7h16M4 17h16","rails"],["M9 4v6","slider1"],["M15 14v6","slider2"]],
    infrastructure: [["M5 3h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z","server1"],["M5 13h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2Z","server2"],["M7 7h.01","led1"],["M7 17h.01","led2"],["M12 7h5","write1"],["M12 17h5","write2"]],
    clipboard: [["M8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2","shell"],["M9 3h6q1 0 1 1v3H8V4q0-1 1-1Z","clip"],["M8 12h8","write1"],["M8 16h5","write2"],["M6 7h12v14H6Z","echo"]],
    check: [["m5 12 4 4L19 6","tick"],["M5 12h.01","pen"]],
    refresh: [["M18 6a8.49 8.49 0 1 0 2.49 6","arc"],["M18 2v4h-4","head"]],
    signout: [["M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5","door"],["M9 12h12m-5-5 5 5-5 5","arrow"]],
    back: [["m13 5-7 7 7 7","head"],["M6 12h14","shaft"]],
    forward: [["m11 5 7 7-7 7","head"],["M4 12h14","shaft"]],
    close: [["M12 12 6 6","arm1"],["M12 12 18 18","arm2"],["M12 12 6 18","arm3"],["M12 12 18 6","arm4"],["M12 7q1 4 5 5-4 1-5 5-1-4-5-5 4-1 5-5Z","star"]],
    menu: [["M4 6h16","write1"],["M4 12h16","write2"],["M4 18h16","write3"]],
    pointer: [["m5 3 14 9-7 2-3 7Z","shell"],["M12 14h.01","signal"]],
    agent: [["m3.5 10 7.2-6.2q1.3-1.1 2.6 0l7.2 6.2v9q0 2-2 2h-13q-2 0-2-2Z","shell"],["M16 6V3h3v5.6","chimney"],["M16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z","hearth"],["M12 14h.01","center"],["M17.5 1q-2-1 0-2t0-2","smoke1"],["M19 0q2-1 0-2t0-2","smoke2"],["M17 0h3l-3 3h3","sleep1"],["M20-2h3l-3 3h3","sleep2"],["M22-5h3l-3 3h3","sleep3"],["M10.5 12v4M13.5 12v4","pause"],["m9.5 14 1.8 2 3.8-4","done"],["M12 12v2M12 16h.01","alert"],["M10 14h.01M12 14h.01M14 14h.01","waiting"]],
    key: [["M11 10a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z","bow"],["M11 9h10v5h-3v-2h-3v-1h-4","teeth"],["M8.4 10a1.4 1.4 0 1 1-2.8 0 1.4 1.4 0 0 1 2.8 0Z","hole"]],
    keyboard: [["M4 5h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z","shell"],...[[5,8],[9,8],[13,8],[17,8],[5,12],[9,12],[13,12],[17,12]].map(([x,y],i)=>[`M${x} ${y}h2v2h-2Z`,`key${i}`]),["M8 16h8","space"]],
    eye: [["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z","lid"],["M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z","pupil"]],
    attach: [["m8 12 7-7a3 3 0 0 1 4 4L9 19a5 5 0 0 1-7-7l10-10","loop"],["m8 12 5-5","inner"]],
    send: [["m3 3 18 9-18 9 4-9Z","plane"],["M7 12h14","trail"]],
    warning: [["m12 3 10 18H2Z","shell"],["M12 9v5","mark"],["M12 17h.01","dot"]],
    terminal: [["M4 4h16q1 0 1 1v14q0 1-1 1H4q-1 0-1-1V5q0-1 1-1Z","shell"],["M3 8h18M6 6h.01","chrome"],["m7 11 3 3-3 3","prompt"],["M13 17h4","cursor"],["M13 13h4","command"]],
    "terminal-context": [["M17 8V5q0-1-1-1H4q-1 0-1 1v14q0 1 1 1h12q1 0 1-1v-3","source"],["m6 9 3 3-3 3","write1"],["M12 12h9m-3-3 3 3-3 3","arrow"],["M12 12h.01","packet"]],
    "about-you": [["M11 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z","profile"],["M3 20v-2q0-5 5-5h2","shoulders"],["M14 10h5l2 2v8h-7Z","page"],["M19 10v3h2","fold"],["M16 15h3","write1"],["M16 18h2","write2"]],
  });
  const bound=new WeakSet(), running=new Set(), byTarget=new WeakMap();
  const preferenceKey="radhouse.appearance.icon-animation";
  const reduced=matchMedia("(prefers-reduced-motion: reduce)");
  const agentStates=Object.freeze(["ready","idle","thinking","working","waiting","paused","complete","error"]);
  let enabled=true, stateEnabled=true, managedMotion=false, preferenceSaved=true;
  try {enabled=localStorage.getItem(preferenceKey)!=="off";} catch (_) { preferenceSaved=false; }
  stateEnabled=enabled;
  function effective(){return enabled && !reduced.matches;}
  function applyPreference(){
    document.documentElement.dataset.iconAnimation=effective()?"on":"off";
    document.documentElement.dataset.agentStateMotion=stateEnabled && !reduced.matches?"on":"off";
    if(!effective())for(const animation of [...running])animation.cancel();
    for(const input of document.querySelectorAll('[data-icon-animation-toggle]'))input.checked=enabled;
    for(const note of document.querySelectorAll('.rh-appearance-note'))note.textContent=
      reduced.matches ? "Your device’s reduced motion setting keeps icons still." :
      !preferenceSaved ? "Applied to this page. Browser storage is unavailable." :
      "Playful hover, click and agent-state motion. Saved in this browser.";
    document.dispatchEvent(new CustomEvent("radhouse-appearance",{detail:{enabled,effective:effective(),reduced:reduced.matches}}));
  }
  function setEnabled(value){
    enabled=Boolean(value);let saved=true;
    if(!managedMotion)stateEnabled=enabled;
    try {localStorage.setItem(preferenceKey,enabled?"on":"off");}catch(_){saved=false;}
    preferenceSaved=saved;applyPreference();return saved;
  }
  function setMotionPreferences({iconMotion=true,stateMotion=true}={}){
    managedMotion=true;enabled=Boolean(iconMotion);stateEnabled=Boolean(stateMotion);applyPreference();
  }
  reduced.addEventListener("change",applyPreference);
  window.addEventListener("storage",event=>{
    if(managedMotion)return;
    if(event.key===preferenceKey || event.key===null){
      try {enabled=localStorage.getItem(preferenceKey)!=="off";}catch(_){return;}
      stateEnabled=enabled;
      applyPreference();
    }
  });
  let appearanceId=0;
  function appearanceControl(){
    const section=document.createElement("section");section.className="rh-appearance";
    const heading=document.createElement("h2");heading.textContent="Appearance";
    const label=document.createElement("label");label.className="rh-appearance-switch";
    const input=document.createElement("input");input.type="checkbox";input.setAttribute("role","switch");
    input.dataset.iconAnimationToggle="";input.checked=enabled;
    const text=document.createElement("span");text.textContent="Icon animation";
    const note=document.createElement("p");note.className="rh-appearance-note";note.id="rh-appearance-note-"+(++appearanceId);
    input.setAttribute("aria-describedby",note.id);
    input.addEventListener("change",()=>setEnabled(input.checked));label.append(text,input);
    section.append(heading,label,note);
    note.textContent=reduced.matches ? "Your device’s reduced motion setting keeps icons still." :
      !preferenceSaved ? "Applied to this page. Browser storage is unavailable." :
      "Playful hover, click and agent-state motion. Saved in this browser.";
    return section;
  }
  function play(target,frames,duration=600,{delay=0,easing="cubic-bezier(.22,.8,.25,1)",iterations=1}={}){
    if(!target || !effective())return;
    byTarget.get(target)?.cancel();
    const animation=target.animate(frames,{duration,delay,easing,iterations,fill:"backwards"});
    byTarget.set(target,animation);running.add(animation);
    const forget=()=>running.delete(animation);
    animation.addEventListener("finish",forget,{once:true});animation.addEventListener("cancel",forget,{once:true});
  }
  const part=(svg,name)=>svg.querySelector(`[data-part="${name}"]`);
  const parts=(svg,prefix)=>[...svg.querySelectorAll(`[data-part^="${prefix}"]`)];
  function write(target,delay=0,duration=330){
    if(!target)return;
    const length=target.getTotalLength();
    play(target,[{strokeDasharray:String(length),strokeDashoffset:String(length)},{strokeDasharray:String(length),strokeDashoffset:"0"}],duration,{delay,easing:"linear"});
  }
  function writing(svg,delay=0,duration=330){parts(svg,"write").forEach((line,i)=>write(line,delay+i*110,duration));}
  function type(svg,click){
    const order=click?[0,5,2,7,1,6,4,3]:[0,5,2,7];
    order.forEach((index,i)=>play(part(svg,"key"+index),[{transform:"translateY(0)",opacity:1},{transform:"translateY(1px)",opacity:.25,offset:.35},{transform:"translateY(0)",opacity:1}],180,{delay:i*(click?60:110)}));
    if(click)play(part(svg,"space"),[{transform:"translateY(0)"},{transform:"translateY(1px)",offset:.4},{transform:"translateY(0)"}],240,{delay:480});
  }
  function blink(svg,click){
    const frames=click?[{transform:"scaleY(1)"},{transform:"scaleY(.04)",offset:.18},{transform:"scaleY(.04)",offset:.48},{transform:"scaleY(1)",offset:.7},{transform:"scaleY(.04)",offset:.82},{transform:"scaleY(1)"}]
      :[{transform:"scaleY(1)"},{transform:"scaleY(.04)",offset:.35},{transform:"scaleY(.04)",offset:.5},{transform:"scaleY(1)"}];
    play(part(svg,"lid"),frames,click?900:520);
    play(part(svg,"pupil"),click?[{opacity:1},{opacity:0,offset:.18},{opacity:0,offset:.48},{opacity:1,offset:.7},{opacity:0,offset:.82},{opacity:1}]:[{opacity:1},{opacity:0,offset:.35},{opacity:0,offset:.5},{opacity:1}],click?900:520);
  }
  function buzz(svg,click){
    for(const [i,server] of parts(svg,"server").entries()){
      play(server,[{transform:"translateX(0)"},{transform:"translateX(-.9px)",offset:.15},{transform:"translateX(.9px)",offset:.3},{transform:"translateX(-.7px)",offset:.45},{transform:"translateX(.7px)",offset:.6},{transform:"translateX(-.4px)",offset:.8},{transform:"translateX(0)"}],click?760:560,{delay:i*60,easing:"linear"});
    }
    for(const [i,led] of parts(svg,"led").entries())play(led,[{opacity:1},{opacity:.15,offset:.35},{opacity:1,offset:.7},{opacity:1}],240,{delay:i*150,iterations:click?3:2});
    if(click)writing(svg,250);
  }
  function checking(svg){
    const tick=part(svg,"tick"),length=tick.getTotalLength();
    play(tick,[{strokeDasharray:String(length),strokeDashoffset:String(length),strokeWidth:1.7},{strokeDasharray:String(length),strokeDashoffset:String(length*.72),strokeWidth:2,offset:.4},{strokeDasharray:String(length),strokeDashoffset:String(length*.72),strokeWidth:2,offset:.5},{strokeDasharray:String(length),strokeDashoffset:"0",strokeWidth:1.7}],650,{easing:"linear"});
    play(part(svg,"pen"),[{opacity:0,transform:"translate(0,0)"},{opacity:1,transform:"translate(4px,4px)",offset:.4},{opacity:1,transform:"translate(4px,4px)",offset:.5},{opacity:0,transform:"translate(14px,-6px)"}],650,{easing:"linear"});
  }
  function closing(svg,click){
    for(const arm of parts(svg,"arm")){
      if(!click)play(arm,[{transform:"scale(1)",opacity:1},{transform:"scale(.02)",opacity:0,offset:.38},{transform:"scale(.02)",opacity:0,offset:.58},{transform:"scale(1)",opacity:1}],700);
      else {
        const length=arm.getTotalLength();
        play(arm,[{transform:"scale(1)",opacity:1,strokeDasharray:String(length),strokeDashoffset:"0"},{transform:"scale(.02)",opacity:0,strokeDasharray:String(length),strokeDashoffset:"0",offset:.28},{transform:"scale(1)",opacity:0,strokeDasharray:String(length),strokeDashoffset:String(length),offset:.65},{transform:"scale(1)",opacity:1,strokeDasharray:String(length),strokeDashoffset:String(length),offset:.66},{transform:"scale(1)",opacity:1,strokeDasharray:String(length),strokeDashoffset:"0"}],900);
      }
    }
    play(part(svg,"star"),click?[{opacity:0,transform:"scale(.1)"},{opacity:0,transform:"scale(.1)",offset:.27},{opacity:1,transform:"scale(1.15)",offset:.45},{opacity:0,transform:"scale(.2)",offset:.64},{opacity:0,transform:"scale(.2)"}]:[{opacity:0,transform:"scale(.2)"},{opacity:0,transform:"scale(.2)",offset:.35},{opacity:.8,transform:"scale(.85)",offset:.48},{opacity:0,transform:"scale(.2)",offset:.65},{opacity:0}],click?900:700);
  }
  function motion(node,click=false){
    if(node.disabled || !effective())return;
    const svg=node.matches?.(".rh-icon")?node:node.querySelector(".rh-icon");if(!svg)return;
    const name=svg.dataset.icon;
    if(name==="keyboard")type(svg,click);
    else if(name==="eye")blink(svg,click);
    else if(name==="infrastructure")buzz(svg,click);
    else if(name==="check")checking(svg);
    else if(name==="close")closing(svg,click);
    else if(name==="refresh"){
      write(part(svg,"arc"),click?120:0,click?540:500);
      if(click)play(svg,[{transform:"rotate(0)"},{transform:"rotate(360deg)"}],760,{easing:"cubic-bezier(.45,0,.15,1)"});
      else play(part(svg,"head"),[{transform:"translateY(0)"},{transform:"translateY(1.5px)",offset:.4},{transform:"translateY(0)"}],500);
    }else if(name==="key"){
      if(!click){write(part(svg,"hole"),0,400);write(part(svg,"teeth"),150,400);}
      else play(svg,[{transform:"translateX(0) rotate(0)"},{transform:"translateX(2px) rotate(0)",offset:.2},{transform:"translateX(2px) rotate(-35deg)",offset:.48},{transform:"translateX(2px) rotate(0)",offset:.75},{transform:"translateX(0) rotate(0)"}],850);
    }else if(name==="agent"){
      if(!click)write(part(svg,"hearth"),0,700);
      else {
        write(part(svg,"hearth"),100,700);play(part(svg,"center"),[{opacity:1,strokeWidth:1.7},{opacity:1,strokeWidth:4,offset:.5},{opacity:1,strokeWidth:1.7}],800);
        parts(svg,"smoke").forEach((smoke,i)=>play(smoke,[{opacity:0,transform:"translateY(2px)"},{opacity:.8,transform:"translateY(0)",offset:.35},{opacity:0,transform:"translateY(-4px)"}],900,{delay:i*120}));
      }
    }else if(name==="settings"){
      for(const [i,slider] of parts(svg,"slider").entries())play(slider,[{transform:"translateX(0)"},{transform:`translateX(${(i? -1:1)*(click?5:3)}px)`,offset:.45},{transform:"translateX(0)"}],click?720:500);
    }else if(name==="back" || name==="forward"){
      write(part(svg,"shaft"),0,click?240:420);
      const direction=name==="back"?-1:1;
      play(part(svg,"head"),[{transform:"translateX(0)"},{transform:`translateX(${direction*(click?4:2)}px)`,offset:.45},{transform:"translateX(0)"}],click?580:420);
    }else if(name==="signout"){
      if(!click)write(part(svg,"arrow"),0,450);
      else {play(part(svg,"arrow"),[{transform:"translateX(0)",opacity:1},{transform:"translateX(7px)",opacity:0,offset:.5},{transform:"translateX(-3px)",opacity:0,offset:.51},{transform:"translateX(0)",opacity:1}],760);write(part(svg,"door"),150,500);}
    }else if(name==="terminal"){
      write(part(svg,"prompt"),0,300);play(part(svg,"cursor"),[{opacity:1},{opacity:.1,offset:.5},{opacity:1}],240,{iterations:click?3:2});
      const command=part(svg,"command"),length=command.getTotalLength();
      play(command,[{opacity:0,strokeDasharray:String(length),strokeDashoffset:String(length)},
        {opacity:1,strokeDasharray:String(length),strokeDashoffset:String(length),offset:.15},
        {opacity:1,strokeDasharray:String(length),strokeDashoffset:"0",offset:.7},
        {opacity:0,strokeDasharray:String(length),strokeDashoffset:"0"}],click?850:650,{delay:click?120:240,easing:"steps(4,end)"});
    }else if(name==="terminal-context"){
      writing(svg);
      if(click){write(part(svg,"arrow"),200,400);play(part(svg,"packet"),[{opacity:0,transform:"translateX(0)"},{opacity:1,transform:"translateX(0)",offset:.2},{opacity:1,transform:"translateX(8px)",offset:.75},{opacity:0,transform:"translateX(8px)"}],800);write(part(svg,"source"),0,350);}
    }else if(name==="send"){
      if(!click)write(part(svg,"trail"),0,450);
      else play(part(svg,"plane"),[{transform:"translate(0,0)",opacity:1},{transform:"translate(7px,-3px)",opacity:0,offset:.5},{transform:"translate(-5px,2px)",opacity:0,offset:.51},{transform:"translate(0,0)",opacity:1}],750);
    }else if(name==="attach"){
      write(part(svg,"loop"),0,click?700:500);if(click)write(part(svg,"inner"),350,300);
    }else if(name==="pointer"){
      play(part(svg,"signal"),[{opacity:0,strokeWidth:1.7},{opacity:1,strokeWidth:click?7:4,offset:.5},{opacity:0,strokeWidth:1.7}],click?650:450);
    }else if(name==="warning"){
      write(part(svg,"mark"),0,300);play(part(svg,"dot"),[{opacity:1},{opacity:.15,offset:.5},{opacity:1}],300,{delay:150,iterations:click?2:1});
    }else {
      writing(svg,click?180:0);
      if(click && name==="clipboard")play(part(svg,"echo"),[{opacity:0,transform:"translate(0,0)"},{opacity:.65,transform:"translate(3px,-3px)",offset:.35},{opacity:0,transform:"translate(5px,-5px)"}],750);
      if(click && name==="library")play(part(svg,"lid"),[{transform:"translateY(0)"},{transform:"translateY(-2px)",offset:.4},{transform:"translateY(0)"}],700);
      if(click && name==="browser")write(part(svg,"tab"),0,350);
      if(click && name==="chat")write(part(svg,"shell"),0,420);
      if(click && name==="menu")parts(svg,"write").forEach((line,i)=>play(line,[{transform:"translateY(0)"},{transform:`translateY(${(i-1)*3}px)`,offset:.4},{transform:"translateY(0)"}],650,{delay:i*45}));
      if(click && name==="about-you")write(part(svg,"page"),0,500);
    }
  }
  function setAgentState(node,state="ready"){
    if(!agentStates.includes(state))throw new Error("unknown_radhouse_agent_state");
    const svg=node.matches?.('.rh-icon[data-icon="agent"]')?node:node.querySelector('.rh-icon[data-icon="agent"]');
    if(svg)svg.dataset.agentState=state;
  }
  function create(name){
    if(!Object.hasOwn(paths,name))throw new Error("unknown_radhouse_icon");
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
    for(const [key,value] of Object.entries({viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-width":"1.7","stroke-linecap":"round","stroke-linejoin":"round","aria-hidden":"true",focusable:"false"}))svg.setAttribute(key,value);
    svg.classList.add("rh-icon");svg.dataset.icon=name;
    if(name==="agent")svg.dataset.agentState="ready";
    for(const [d,role] of paths[name]){
      const path=document.createElementNS(svg.namespaceURI,"path");path.setAttribute("d",d);path.dataset.part=role;svg.append(path);
    }
    return svg;
  }
  function decorate(node,name,label=node.textContent.trim(),{compact=false,accessibleLabel=label}={}){
    let svg=node.querySelector(":scope > .rh-icon"),text=node.querySelector(":scope > .rh-action-label");
    if(svg?.dataset.icon!==name || !text){svg=create(name);text=document.createElement("span");text.className="rh-action-label";node.replaceChildren(svg,text);}
    text.textContent=label;node.classList.add("rh-action");node.dataset.icon=name;
    node.classList.toggle("rh-action--compact",compact);node.setAttribute("aria-label",accessibleLabel);
    if(compact)node.dataset.tooltip=accessibleLabel;else delete node.dataset.tooltip;
    if(!bound.has(node)){
      node.addEventListener("pointerenter",event=>{if(event.pointerType!=="touch")motion(node);});
      node.addEventListener("focus",()=>{if(node.matches(":focus-visible"))motion(node);});
      node.addEventListener("click",()=>motion(node,true),{capture:true});bound.add(node);
    }
    if(name==="check" && svg!==node._radhouseCheckedSvg){checking(svg);node._radhouseCheckedSvg=svg;}
    return node;
  }
  function busy(node,pending){node.setAttribute("aria-busy",String(pending));if(pending)node.dataset.state="pending";else delete node.dataset.state;}
  applyPreference();
  return Object.freeze({create,decorate,busy,press:node=>motion(node,true),hover:node=>motion(node),setAgentState,agentStates,
    names:Object.freeze(Object.keys(paths)),appearanceControl,setEnabled,setMotionPreferences,enabled:()=>enabled,effective,reduced:()=>reduced.matches});
})();

// Presentation only. Each page owns its session check and private content.
(() => {
  const icons = window.RadhouseIcons;
  for (const [id, name] of [["logout", "signout"], ["library-refresh", "refresh"], ["refresh", "refresh"],
      ["open-browser-context", "browser"], ["open-terminal-context", "terminal"]]) {
    const node = document.getElementById(id); if (node) icons.decorate(node, name);
  }
  const attach = document.getElementById("attach"); if (attach) icons.decorate(attach, "attach", "Attach files");
  const terminalContext = document.querySelector("#terminal-context-chip label > span");
  if (terminalContext) icons.decorate(terminalContext, "terminal-context", terminalContext.textContent);
  const shell = document.querySelector(".shell, .admin-shell");
  const nav = document.getElementById("management-nav");
  const header = shell?.querySelector("header");
  const main = shell?.querySelector("main");
  if (!shell || !nav || !header || !main) { return; }

  const preferenceKey = "radhouse.navigation.collapsed";
  const mobile = window.matchMedia("(max-width: 760px)");
  let authenticated = false, drawerOpen = false, collapsed = false, focusedInPanel = null;
  try { collapsed = localStorage.getItem(preferenceKey) === "true"; } catch (_) { /* Optional presentation preference. */ }

  const panel = document.createElement("aside");
  panel.id = "navigation-panel"; panel.className = "navigation-panel"; panel.hidden = true;
  nav.before(panel); panel.append(nav);
  const heading = document.createElement("div"); heading.className = "navigation-heading";
  const label = document.createElement("span"); label.textContent = "Navigation";
  const closeButton = document.createElement("button");
  closeButton.type = "button"; closeButton.id = "navigation-close";
  icons.decorate(closeButton, "close", "Close menu", {compact: true});
  heading.append(label, closeButton); panel.prepend(heading);

  const toggle = document.createElement("button");
  toggle.type = "button"; toggle.id = "navigation-toggle"; toggle.hidden = true;
  toggle.setAttribute("aria-controls", panel.id);
  icons.decorate(toggle, "menu", "Open menu", {compact: true}); header.prepend(toggle);
  let agentLink=nav.querySelector('a[href="/agent"]');
  if(!agentLink){agentLink=document.createElement("a");agentLink.href="/agent";agentLink.textContent="Your Agent";nav.prepend(agentLink);}
  agentLink.id="agent-profile-link";agentLink.classList.add("rh-agent-nav");
  const identity=document.createElement("div");identity.className="rh-header-identity";identity.hidden=true;
  const portraitLink=document.createElement("a");portraitLink.href="/agent";portraitLink.className="rh-header-portrait";portraitLink.setAttribute("aria-label","Customize Your Agent");
  const portrait=document.createElement("img");portrait.alt="";portrait.width=portrait.height=44;portrait.decoding="async";portrait.hidden=true;
  const fallbackPortrait=icons.create("agent");portraitLink.append(fallbackPortrait,portrait);
  const identityName=document.createElement("span");identityName.className="rh-header-name";identityName.textContent="Your Agent";
  const liveStatus=document.createElement("span");liveStatus.className="rh-header-status";liveStatus.setAttribute("role","img");liveStatus.setAttribute("aria-label","Agent status unavailable");liveStatus.hidden=true;
  liveStatus.append(icons.create("agent"));identity.append(portraitLink,identityName,liveStatus);header.append(identity);
  let profile=null,profileEntry=null,agentStatus=null;
  function renderProfile(){
    const name=profile?.name || "Your Agent";identityName.textContent=name;portraitLink.setAttribute("aria-label","Customize "+name);
    icons.decorate(agentLink,"agent",name);
    let navPortrait=agentLink.querySelector(".rh-nav-portrait");
    if(profileEntry){
      portrait.src=profileEntry.asset;portrait.hidden=false;fallbackPortrait.setAttribute("hidden","");
      if(!navPortrait){navPortrait=document.createElement("img");navPortrait.alt="";navPortrait.className="rh-nav-portrait";navPortrait.width=navPortrait.height=26;navPortrait.decoding="async";agentLink.prepend(navPortrait);}
      navPortrait.src=profileEntry.asset;agentLink.querySelector(".rh-icon").setAttribute("hidden","");
    }else{
      portrait.removeAttribute("src");portrait.hidden=true;fallbackPortrait.removeAttribute("hidden");navPortrait?.remove();agentLink.querySelector(".rh-icon").removeAttribute("hidden");
    }
  }
  const destinations = {"/agent": "agent", "/": "chat", "/library": "library", "/browser": "browser", "/terminal": "terminal",
    "/about-you": "about-you", "/settings": "settings", "/infrastructure": "infrastructure"};
  for (const link of nav.querySelectorAll("a[href]")) {
    const name = destinations[new URL(link.href).pathname]; if (name) icons.decorate(link, name);
  }
  const backdrop = document.createElement("button");
  backdrop.type = "button"; backdrop.className = "navigation-backdrop";
  backdrop.setAttribute("aria-label", "Close menu"); backdrop.tabIndex = -1; backdrop.hidden = true;
  shell.append(backdrop); shell.classList.add("navigation-shell");

  const inertBeforeOpen = new Map();
  function modalContent(disabled) {
    for (const node of [header, main]) {
      if (disabled) {
        if (!inertBeforeOpen.has(node)) { inertBeforeOpen.set(node, node.inert); }
        node.inert = true;
      } else if (inertBeforeOpen.has(node)) {
        node.inert = inertBeforeOpen.get(node); inertBeforeOpen.delete(node);
      }
    }
  }
  function visibleLinks() { return [...nav.querySelectorAll("a[href]")].filter(node => !node.hidden); }
  function render() {
    const open = authenticated && (mobile.matches ? drawerOpen : !collapsed);
    toggle.hidden = !authenticated; nav.hidden = !authenticated; panel.hidden = !open;
    identity.hidden=!authenticated;
    toggle.setAttribute("aria-expanded", String(open));
    const toggleLabel = open ? "Close menu" : "Open menu";
    toggle.setAttribute("aria-label", toggleLabel); toggle.dataset.tooltip = toggleLabel;
    toggle.querySelector(".rh-action-label").textContent = toggleLabel;
    shell.classList.toggle("nav-active", authenticated);
    shell.classList.toggle("nav-collapsed", !open);
    shell.classList.toggle("nav-drawer-open", mobile.matches && open);
    closeButton.hidden = !mobile.matches;
    backdrop.hidden = !(mobile.matches && open);
    if (mobile.matches && open) {
      panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true");
      panel.setAttribute("aria-label", "Navigation");
    } else {
      panel.removeAttribute("role"); panel.removeAttribute("aria-modal"); panel.removeAttribute("aria-label");
    }
    modalContent(mobile.matches && open);
  }
  function close(returnFocus = true) {
    if (mobile.matches) { drawerOpen = false; }
    else {
      collapsed = true;
      try { localStorage.setItem(preferenceKey, "true"); } catch (_) { /* Optional presentation preference. */ }
    }
    render();
    if (returnFocus && authenticated) { toggle.focus(); }
  }
  toggle.addEventListener("click", () => {
    if (mobile.matches) {
      drawerOpen = !drawerOpen; render();
      if (drawerOpen) { (visibleLinks()[0] || closeButton).focus(); }
    } else {
      collapsed = !collapsed;
      try { localStorage.setItem(preferenceKey, String(collapsed)); } catch (_) { /* Optional presentation preference. */ }
      render();
    }
  });
  closeButton.addEventListener("click", () => close());
  backdrop.addEventListener("click", () => close());
  document.addEventListener("keydown", event => {
    if (!mobile.matches || !drawerOpen || !authenticated) { return; }
    if (event.key === "Escape") { event.preventDefault(); close(); return; }
    if (event.key !== "Tab") { return; }
    const items = [closeButton, ...visibleLinks()];
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
  nav.addEventListener("click", event => {
    if (mobile.matches && event.target.closest("a[href]")) { close(false); }
  });
  document.addEventListener("focusin", event => {
    focusedInPanel = panel.contains(event.target) ? event.target : null;
  });
  mobile.addEventListener("change", () => {
    const previousFocus = focusedInPanel;
    drawerOpen = false; render();
    if (previousFocus && authenticated) {
      if (panel.hidden) { toggle.focus(); }
      else if (!previousFocus.getClientRects().length) { (visibleLinks()[0] || toggle).focus(); }
    }
  });

  window.RadhouseNavigation = Object.freeze({
    update(session) {
      authenticated = Boolean(session);
      for (const link of nav.querySelectorAll("[data-management]")) { link.hidden = session?.management?.read !== true; }
      for (const link of nav.querySelectorAll("a[href]")) {
        if (new URL(link.href).pathname === location.pathname) { link.setAttribute("aria-current", "page"); }
        else { link.removeAttribute("aria-current"); }
      }
      if (!authenticated) { drawerOpen = false;profile=null;profileEntry=null;agentStatus=null;liveStatus.hidden=true;renderProfile(); }
      render();
    },
    setProfile(value,entry=null){profile=value;profileEntry=entry;renderProfile();},
    setAgentState(state,text){
      if(!icons.agentStates.includes(state)){agentStatus=null;liveStatus.hidden=true;return;}
      agentStatus={state,text:String(text || state)};icons.setAgentState(liveStatus,state);liveStatus.setAttribute("aria-label",agentStatus.text);liveStatus.hidden=false;
      document.dispatchEvent(new CustomEvent("radhouse-agent-state",{detail:{...agentStatus}}));
    },
    agentStatus:()=>agentStatus ? {...agentStatus} : null,
    close,
    isOpen: () => !panel.hidden,
  });
  render();
})();
