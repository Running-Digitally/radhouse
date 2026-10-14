// Forward status only; clipboard payloads and input text never enter the outer UI.
import {installMobileInput} from "./mobile-input.js";
installMobileInput(value => window.parent.postMessage({type: "mobileInputStatus", ...value}, location.origin));
window.addEventListener("message", event => {
  if (event.origin !== location.origin || event.source !== window) return;
  if (event.data?.type === "pipelineStatusUpdate") window.parent.postMessage(event.data, location.origin);
});
let attached = false, lastNotice = -Infinity;
const observer = new MutationObserver(attach);
observer.observe(document.documentElement, {childList: true, subtree: true});
function attach() {
  const video = document.getElementById("videoStream");
  if (!video || attached || !video.requestVideoFrameCallback) return;
  attached = true;
  function presented(now) {
    if (now - lastNotice > 1000) {
      lastNotice = now;
      window.parent.postMessage({type: "framePresented"}, location.origin);
    }
    video.requestVideoFrameCallback(presented);
  }
  video.requestVideoFrameCallback(presented);
}
attach();
