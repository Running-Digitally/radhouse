// Forward status only; clipboard payloads and input text never enter the outer UI.
import {installMobileInput} from "./mobile-input.js";
installMobileInput(value => window.parent.postMessage({type: "mobileInputStatus", ...value}, location.origin));
window.addEventListener("message", event => {
  if (event.origin !== location.origin || event.source !== window) return;
  if (event.data?.type === "pipelineStatusUpdate") window.parent.postMessage(event.data, location.origin);
});
// Activity stays inside the owned document; the parent never reads a denied
// or redirected iframe's document. No key, clipboard or text payload is sent.
let lastActivity = -Infinity;
function activity(event) {
  const now = performance.now();
  if (!event.isTrusted || now - lastActivity < 1000) return;
  lastActivity = now;
  window.parent.postMessage({type: "browserActivity"}, location.origin);
}
for (const type of ["pointerdown", "keydown", "wheel", "touchstart", "input", "compositionend"])
  document.addEventListener(type, activity, {capture: true, passive: true});
let currentVideo = null, lastNotice = -Infinity, lastPlayback = "";
function playback(state) {
  if (state === lastPlayback) return;
  lastPlayback = state;
  window.parent.postMessage({type: "browserPlaybackStatus", state}, location.origin);
}
function presented(now = performance.now()) {
  if (now - lastNotice > 1000) {
    lastNotice = now;
    window.parent.postMessage({type: "framePresented"}, location.origin);
  }
}
function play() {
  const video = currentVideo;
  if (!video) return false;
  video.muted = video.defaultMuted = true;
  video.playsInline = true;
  video.setAttribute("muted", "");
  video.setAttribute("playsinline", "");
  video.setAttribute("webkit-playsinline", "");
  playback("connecting");
  try {
    // Call in the parent's click stack, before any asynchronous work. Safari
    // may reject autoplay even for silent inline video (for example on battery).
    const result = video.play();
    result?.then(() => { if (currentVideo === video) playback("playing"); })
      .catch(error => { if (currentVideo === video) playback(error.name === "NotAllowedError" ? "tap_required" : "unavailable"); });
  } catch (error) {
    playback(error.name === "NotAllowedError" ? "tap_required" : "unavailable");
  }
  return true;
}
// Same-origin presentation helper, like keyboard focus. No remote input or
// permission changes; no postMessage command channel or arbitrary operations.
window.radhousePlayback = Object.freeze({play});
function attach() {
  const video = document.getElementById("videoStream");
  if (!video || video === currentVideo) return;
  currentVideo = video;
  video.muted = video.defaultMuted = true;
  video.playsInline = true;
  video.setAttribute("muted", "");
  video.setAttribute("playsinline", "");
  video.setAttribute("webkit-playsinline", "");
  const active = () => currentVideo === video;
  video.addEventListener("loadeddata", () => { if (active() && video.paused) play(); });
  video.addEventListener("playing", () => {
    if (!active()) return;
    playback("playing");
    if (!video.requestVideoFrameCallback && video.readyState >= 2) presented();
  });
  video.addEventListener("pause", () => { if (active() && video.readyState >= 2) playback("tap_required"); });
  video.addEventListener("error", () => { if (active()) playback("unavailable"); });
  video.addEventListener("timeupdate", () => {
    if (active() && !video.requestVideoFrameCallback && !video.paused && video.readyState >= 2) presented();
  });
  if (video.requestVideoFrameCallback) {
    function frame(now) {
      if (!active()) return;
      presented(now);
      video.requestVideoFrameCallback(frame);
    }
    video.requestVideoFrameCallback(frame);
  }
  if (video.readyState >= 2) {
    if (video.paused) play();
    else playback("playing");
  }
}
const observer = new MutationObserver(attach);
observer.observe(document.documentElement, {childList: true, subtree: true});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && currentVideo?.paused && currentVideo.readyState >= 2) play();
});
attach();
