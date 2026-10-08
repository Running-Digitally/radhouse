"use strict";
// Local presentation fixture. Only this specimen has an in-memory browser adapter.
(() => {
  const icons=window.RadhouseIcons;
  const motions={
    agent:["Radhouse agent","Hover · ink travels around the hearth","Click · the hearth lights up and a little smoke escapes the chimney"],
    clipboard:["Copy","Hover · the lines are written onto the clipboard","Click · a second sheet peels away; actual success draws a check"],
    refresh:["Refresh","Hover · the clean arc is re-inked, ready to go around","Click · one full reload sweep; a real request keeps it turning"],
    key:["Saved logins","Hover · the key’s bow and teeth are traced","Click · insert, turn the key, and withdraw"],
    keyboard:["Keyboard","Hover · four individual keys are typed","Click · a faster eight-key phrase finishes with the space bar"],
    eye:["Hide view","Hover · one natural blink","Click · close the eye, hold, then reopen with a second blink"],
    close:["Close","Hover · the arms gather into a point and spark back to life","Click · collapse into a point, vanish in a star, then redraw"],
    check:["Checked","Hover · a hand draws the short leg, pauses, then finishes","Click · replay the same deliberate check stroke"],
    infrastructure:["Infrastructure","Hover · server LEDs blink as the racks buzz","Click · a longer burst with activity traced across the vents"],
    menu:["Menu","Hover · three lines are written in sequence","Click · the lines fan open and return"],
    chat:["Chat","Hover · two lines are written inside the bubble","Click · trace the conversation bubble, then write its lines"],
    library:["Library","Hover · the folder’s lines are written in sequence","Click · lift the folder tab, then write the contents"],
    browser:["Browser","Hover · two clear strokes load below the active tab","Click · trace the active tab, then load the page"],
    settings:["Settings","Hover · the sliders adjust in opposite directions","Click · a wider adjustment returns to its setting"],
    back:["Back","Hover · draw the shaft toward the previous page","Click · the arrow travels farther in its direction"],
    forward:["Go","Hover · draw the shaft toward the next page","Click · the arrow travels farther in its direction"],
    signout:["Sign out","Hover · draw the exit arrow","Click · the arrow exits the doorway and returns"],
    attach:["Attach files","Hover · thread the paperclip from end to end","Click · a full loop followed by the inner strand"],
    send:["Send","Hover · the flight path is drawn","Click · the paper plane flies away and a new one arrives"],
    pointer:["Take control","Hover · a small pulse appears at the pointer’s tip","Click · a stronger contact pulse"],
    warning:["Needs attention","Hover · draw the warning stroke and dot","Click · two dot pulses call attention to the message"],
    terminal:["Terminal","Hover · draw the prompt, blink the cursor, type a short command","Click · a longer phrase is typed as the cursor blinks"],
    "terminal-context":["Share terminal context","Hover · draw the terminal prompt","Click · a packet travels out of the terminal along the sharing arrow"],
    "about-you":["About You","Hover · write the saved memory’s lines","Click · trace the read-only note and write its contents"],
  };
  const choice=document.getElementById("motion-choice"),stage=document.getElementById("motion-stage"),description=document.getElementById("motion-description");
  for(const [name,[label]] of Object.entries(motions)){
    const option=document.createElement("option");option.value=name;option.textContent=label;choice.append(option);
  }
  function showMotion(){
    stage.replaceChildren();description.textContent="Hover to discover; click to play the fuller action.";
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
  icons.decorate(document.getElementById("desktop-browser"),"browser","Browser");
  icons.decorate(document.getElementById("desktop-terminal-context"),"terminal-context","Share terminal context");
  for(const name of icons.names){
    const cell=document.createElement("div");cell.className="icon-cell";
    const button=document.createElement("button");button.type="button";
    icons.decorate(button,name,motions[name][0]);
    button.dataset.sample=name;
    cell.append(button);document.getElementById("icon-grid").append(cell);
  }
  for(const [name,icon,label,state] of [["Default","clipboard","Copy",""],["Hover / focus","refresh","Refresh",""],
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
  const copy=document.getElementById("try-copy");copy.dataset.label="Copy";copy.dataset.copyKind="answer";copy.dataset.accessibleLabel="Copy answer";
  icons.decorate(copy,"clipboard","Copy",{accessibleLabel:"Copy answer"});
  copy.onclick=()=>window.RadhouseFormat.copyText("A small step, taken consistently, makes room for the rest of the day.",copy);
  document.getElementById("appearance-preview").append(icons.appearanceControl());
  const agentState=document.getElementById("agent-state"),agentStage=document.getElementById("agent-stage");
  const agent=icons.create("agent");agentStage.prepend(agent);
  const agentDescriptions={ready:"Ready · the hearth is still.",idle:"Idle · little zzz drift from the chimney.",
    thinking:"Thinking · smoke curls from the chimney while the hearth breathes.",working:"Working · smoke rises and ink circulates around the hearth.",
    waiting:"Waiting · three gentle dots leave room for the next step.",paused:"Paused · the house holds two still pause bars.",
    complete:"Complete · a check settles inside the hearth.",error:"Needs attention · the hearth carries a warning."};
  let journeyTimers=[];const journey=document.getElementById("agent-journey");
  function showAgent(state){agentState.value=state;icons.setAgentState(agent,state);document.getElementById("agent-description").textContent=agentDescriptions[state];}
  function stopJourney(){journeyTimers.forEach(clearTimeout);journeyTimers=[];journey.disabled=false;}
  for(const state of icons.agentStates){
    const option=document.createElement("option");option.value=state;option.textContent=state.charAt(0).toUpperCase()+state.slice(1);agentState.append(option);
    const cell=document.createElement("div");cell.className="agent-state-cell";
    const mark=icons.create("agent");icons.setAgentState(mark,state);
    const caption=document.createElement("span");caption.textContent=option.textContent;cell.append(mark,caption);
    cell.dataset.agentSample=state;document.getElementById("agent-states").append(cell);
  }
  agentState.addEventListener("change",()=>{stopJourney();showAgent(agentState.value);});
  journey.addEventListener("click",()=>{
    stopJourney();journey.disabled=true;showAgent("thinking");
    for(const [i,state] of ["working","waiting","paused","complete","idle"].entries())journeyTimers.push(setTimeout(()=>showAgent(state),(i+1)*2200));
    journeyTimers.push(setTimeout(stopJourney,11000));
  });showAgent("idle");
  for(const [id,icon,label] of [["future-terminal","terminal","Open terminal"],["future-hide","eye","Hide terminal"],
    ["future-close","close","Close terminal"],["future-about","about-you","About You"]])icons.decorate(document.getElementById(id),icon,label);
  const contextLabel=document.getElementById("future-context-label");contextLabel.prepend(icons.create("terminal-context"));
  const context=document.getElementById("future-context");
  context.addEventListener("change",()=>{
    if(context.checked)icons.press(contextLabel);
    document.getElementById("future-context-note").textContent=context.checked ? "On · selected or recent output can accompany a message." : "Off · output stays in the terminal.";
  });
  const terminalNote=document.getElementById("future-terminal-note");
  document.getElementById("future-terminal").onclick=()=>{terminalNote.textContent="Interactive session open · icon study only.";};
  document.getElementById("future-hide").onclick=()=>{terminalNote.textContent="Hidden · session retained.";};
  document.getElementById("future-close").onclick=()=>{terminalNote.textContent="Closed · session ended.";};
  document.getElementById("future-about").onclick=()=>{document.getElementById("future-about-note").textContent="A separate view of saved memory, with read-only content.";};
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
