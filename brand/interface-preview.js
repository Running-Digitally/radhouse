"use strict";
// Local presentation fixture. Only this specimen has an in-memory browser adapter.
(() => {
  const icons=window.RadhouseIcons;
  const motions={agent:["Return to agent","Hover · the hearth opens gently","Click · one hearth pulse settles inside the shelter"],
    clipboard:["Copy answer","Hover · the clipboard lifts","Click · a short lift and settle; success needs the real clipboard write"],
    refresh:["Refresh","Hover · a small turn hints at reload","Click · a full turn settles; an actual pending refresh keeps turning"],
    back:["Back","Hover · a nudge toward the previous page","Click · a directional push, soft recoil and settle"],
    forward:["Go","Hover · a nudge toward the next page","Click · a directional push, soft recoil and settle"],
    chat:["Chat","Hover · the speech bubble leans into the conversation","Click · a small compression and rebound"],
    library:["Library","Hover · the folder lifts","Click · a light lift and return"],
    browser:["Browser","Hover · the window opens a little","Click · a small compression and rebound"],
    settings:["Settings","Hover · the sliders shift in opposite directions","Click · the sliders travel and settle"],
    infrastructure:["Infrastructure","Hover · the stack lifts","Click · a small compression and rebound"],
    signout:["Sign out","Hover · the exit moves outward","Click · the arrow leaves and returns"],
    close:["Close browser","Hover · a small turn signals closure","Click · a short contraction and settle"]};
  const choice=document.getElementById("motion-choice"),stage=document.getElementById("motion-stage"),description=document.getElementById("motion-description");
  for(const [name,[label]] of Object.entries(motions)){
    const option=document.createElement("option");option.value=name;option.textContent=label;choice.append(option);
  }
  function showMotion(){
    stage.replaceChildren();description.textContent="Hover hints at the action; click gives a short settling response.";
    const [label,hover,click]=motions[choice.value];
    for(const caption of ["Hover hint","Click response"]){
      const cell=document.createElement("div");cell.className="motion-example";
      const title=document.createElement("p");title.textContent=caption;
      const button=document.createElement("button");button.type="button";icons.decorate(button,choice.value,label);
      button.addEventListener("pointerenter",()=>{description.textContent=hover;});
      button.addEventListener("click",()=>{description.textContent=click;});
      cell.append(title,button);stage.append(cell);
    }
  }
  choice.addEventListener("change",showMotion);showMotion();
  for(const name of icons.names){
    const cell=document.createElement("div");cell.className="icon-cell";
    const button=document.createElement("button");button.type="button";
    icons.decorate(button,name,name.charAt(0).toUpperCase()+name.slice(1));
    button.dataset.sample=name;
    cell.append(button);document.getElementById("icon-grid").append(cell);
  }
  for(const [name,icon,label,state] of [["Default","clipboard","Copy answer",""],["Hover / focus","refresh","Refresh",""],
    ["Pressed","back","Back","pressed"],["Selected","browser","Browser","selected"],
    ["Disabled","agent","Return to agent","disabled"],["Pending","refresh","Refresh","pending"],["Success","check","Copied","success"]]){
    const cell=document.createElement("div");cell.className="state";
    const caption=document.createElement("span");caption.textContent=name;
    const button=document.createElement("button");button.type="button";icons.decorate(button,icon,label);
    if(state==="disabled")button.disabled=true;
    else if(state==="pressed" || state==="selected")button.classList.add("state-"+state);
    else if(state)button.dataset.state=state;
    if(state==="pending")button.setAttribute("aria-busy","true");
    cell.append(caption,button);document.getElementById("states").append(cell);
  }
  const copy=document.getElementById("try-copy");copy.dataset.label="Copy answer";
  icons.decorate(copy,"clipboard","Copy answer");
  copy.onclick=()=>window.RadhouseFormat.copyText("A small step, taken consistently, makes room for the rest of the day.",copy);
  let mode="idle",revision=1,url="https://fieldnotes.example/a-calmer-morning";
  const state=()=>({state:mode==="idle"?"idle":"live",generation:mode==="idle"?null:"specimen-1",url,
    control:mode==="idle"?null:{mode,revision,can_take:mode==="agent",...(mode==="human"?{lease_id:"specimen-lease",lease_expires_at:Date.now()/1000+3600,next_sequence:1}:{})},
    can_return:true,vault_enabled:false});
  const view=new window.BrowserView(document.getElementById("preview-browser"),{persistent:true,tab:()=>"specimen-tab",
    request:async(path,body)=>{
      if(path.endsWith("/input")){if(body.operation==="navigate")url=body.arguments.url;return {outcome:"applied"};}
      mode=path.endsWith("/close")?"idle":"human";revision++;return state();
    },onReturn:async()=>{mode="agent";revision++;view.update(state());}});
  const pageSvg=`<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540"><rect width="960" height="540" fill="#fffefa"/><path d="M0 66h960" stroke="#e4e1d7"/><text x="64" y="43" font-family="Georgia,serif" font-size="25" fill="#293d33">fieldnotes</text><text x="623" y="40" font-family="Arial,sans-serif" font-size="12" fill="#647368">Journal</text><text x="710" y="40" font-family="Arial,sans-serif" font-size="12" fill="#647368">About</text><text x="786" y="40" font-family="Arial,sans-serif" font-size="12" fill="#647368">Subscribe</text><text x="64" y="119" font-family="Arial,sans-serif" font-size="11" fill="#a36b43" letter-spacing="2">EVERYDAY PRACTICE</text><text x="64" y="182" font-family="Georgia,serif" font-size="45" fill="#293d33">A calmer morning.</text><text x="64" y="220" font-family="Arial,sans-serif" font-size="17" fill="#647368">Make room for what matters before the day begins.</text><text x="64" y="261" font-family="Arial,sans-serif" font-size="11" fill="#647368">5 MIN READ · OCTOBER 8</text><rect x="64" y="302" width="462" height="1" fill="#e4e1d7"/><text x="64" y="344" font-family="Georgia,serif" font-size="18" fill="#384b40">Start small. Leave a little space. Let the first few</text><text x="64" y="373" font-family="Georgia,serif" font-size="18" fill="#384b40">minutes belong to you. A glass of water, an open</text><text x="64" y="402" font-family="Georgia,serif" font-size="18" fill="#384b40">window, one thing you want to give attention to.</text><text x="64" y="456" font-family="Georgia,serif" font-size="18" fill="#384b40">The aim is a rhythm you can return to.</text><rect x="596" y="114" width="300" height="370" rx="4" fill="#e7ecdf"/><circle cx="790" cy="225" r="61" fill="#f5ead2"/><path d="M596 365q150-160 300-45v164H596Z" fill="#b4c6af"/><path d="M596 418q165-140 300-28v94H596Z" fill="#8da98e"/><path d="M741 290v194m0-132q-72-39-53-79 54 9 53 79m0 44q69-48 68-91-54 4-68 91" fill="none" stroke="#496e53" stroke-width="4" stroke-linecap="round"/></svg>`;
  // Use the production viewport DOM and coordinate/ownership state, with static pixels.
  view._poll=async()=>{
    if(!view.active || !view.open)return;
    view.image.src="data:image/svg+xml;charset=utf-8,"+encodeURIComponent(pageSvg);
    await view.image.decode();view.image.hidden=false;view.viewport.hidden=false;
    view.displayedFrame={frame_id:"specimen-frame",viewport:{width:960,height:540}};
    view._label("Live browser");view._renderControlState();
  };
  view.controlEnabled=true;view.update(state());window.specimenBrowser=view;
})();
