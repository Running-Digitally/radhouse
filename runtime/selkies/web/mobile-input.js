// Thin UI adapter over the pinned Selkies keyboard/composition input path.
import {hardwareKeyboard} from "./hardware-keyboard.js";
import {chordEvents, parseChord} from "./touch-controls.js";

export function installMobileInput(notify) {
  const watch = hardwareKeyboard();
  const coarse = window.matchMedia("(pointer: coarse)");
  let touched = coarse.matches, last = "", wasReady = false;
  const ready = () => window.webrtcInput?.isInputAttached() === true;
  const field = () => document.getElementById("keyboard-input-assist");
  function clear() {
    const assist = field();
    if (assist) { assist.value = ""; assist.blur(); }
  }
  function status() {
    return {ready: ready(), touch: touched, hardware: watch.attached(),
      focused: !!field() && document.activeElement === field()};
  }
  function publish() {
    const value = status(), serialized = JSON.stringify(value);
    if (serialized !== last) { last = serialized; notify(value); }
  }
  function show(override = false) {
    if (!ready() || !field()) return false;
    if (override) watch.reset();
    clear();
    // Keep the existing invisible assist input in the visual viewport on iOS.
    Object.assign(field().style, {position: "fixed", left: "0", top: "auto", bottom: "0", fontSize: "16px"});
    field().focus({preventScroll: true});
    publish();
    return document.activeElement === field();
  }
  const keys = new Map([["tab", "Tab"], ["enter", "Enter"], ["escape", "Esc"],
    ["backspace", "Backspace"], ["address", "Ctrl+l"]]);
  function press(name) {
    if (!ready() || !keys.has(name)) return false;
    for (const event of chordEvents(parseChord(keys.get(name)))) {
      window.dispatchEvent(new KeyboardEvent(event.type, {key: event.key, code: event.code,
        ctrlKey: event.state.Control, altKey: event.state.Alt, metaKey: event.state.Meta,
        shiftKey: event.state.Shift, bubbles: true, cancelable: true}));
    }
    if (name === "address") show();
    return true;
  }
  watch.subscribe(publish);
  window.addEventListener("touchstart", () => { touched = true; publish(); }, {capture: true, passive: true});
  coarse.addEventListener("change", event => { touched ||= event.matches; publish(); });
  window.addEventListener("focusin", publish);
  window.addEventListener("focusout", publish);
  document.addEventListener("visibilitychange", () => { if (document.hidden) clear(); publish(); });
  window.addEventListener("pagehide", clear);
  // Readiness is the core's role-bound input attachment, not screen size.
  setInterval(() => {
    if (wasReady && !ready()) clear();
    wasReady = ready();
    publish();
  }, 300);
  window.radhouseInput = Object.freeze({status, show, hide: () => { clear(); publish(); }, press});
  publish();
}
