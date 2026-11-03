// Thin UI adapter over the pinned Selkies keyboard/composition input path.
import {hardwareKeyboard} from "./hardware-keyboard.js";
import {chordEvents, parseChord} from "./touch-controls.js";

export function installMobileInput(notify) {
  const watch = hardwareKeyboard();
  const coarse = window.matchMedia("(pointer: coarse)");
  let touched = coarse.matches, last = "", wasReady = false, navigation = 0;
  const ready = () => window.webrtcInput?.isInputAttached() === true;
  const field = () => document.getElementById("keyboard-input-assist");
  function clear() {
    navigation++;
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
    ["backspace", "Backspace"], ["address", "Ctrl+l"],
    ["back", "Alt+Left"], ["reload", "Ctrl+r"]]);
  function press(name) {
    navigation++;
    if (!ready() || !keys.has(name)) return false;
    for (const event of chordEvents(parseChord(keys.get(name)))) {
      window.dispatchEvent(new KeyboardEvent(event.type, {key: event.key, code: event.code,
        ctrlKey: event.state.Control, altKey: event.state.Alt, metaKey: event.state.Meta,
        shiftKey: event.state.Shift, bubbles: true, cancelable: true}));
    }
    if (name === "address") show();
    return true;
  }
  async function navigate(value) {
    if (!ready() || !field() || typeof value !== "string" || value.length > 4096) return false;
    let url;
    try { url = new URL(value); } catch { return false; }
    if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) return false;
    // Explicit owner address submission uses the same role-bound keyboard path.
    // No clipboard, remote resize, extra transport command or automatic replay.
    if (!press("address") || !ready()) return false;
    const input = field();
    const controller = window.webrtcInput, ticket = navigation;
    // The pinned keyboard core suppresses text echoes for 250 ms after a
    // shortcut. URL text is a separate entry, so let that window expire first.
    // Recheck authority and cancellation; never replay a partially sent action.
    await new Promise(resolve => setTimeout(resolve, 300));
    if (ticket !== navigation || document.hidden || !ready()
        || controller !== window.webrtcInput || input !== field()
        || document.activeElement !== input) return false;
    input.value = url.href;
    input.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: url.href}));
    const sent = press("enter");
    clear();
    return sent;
  }
  watch.subscribe(publish);
  window.addEventListener("touchstart", () => { touched = true; publish(); }, {capture: true, passive: true});
  coarse.addEventListener("change", event => {
    touched ||= event.matches;
    publish();
  });
  window.addEventListener("focusin", publish);
  window.addEventListener("focusout", publish);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clear();
    publish();
  });
  window.addEventListener("pagehide", clear);
  // Readiness is the core's role-bound input attachment, not screen size.
  setInterval(() => {
    if (wasReady && !ready()) clear();
    wasReady = ready();
    publish();
  }, 300);
  window.radhouseInput = Object.freeze({status, show, hide: () => { clear(); publish(); }, press, navigate});
  publish();
}
