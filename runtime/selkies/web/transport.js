"use strict";
// This embedded viewer has one qualified transport. A stale dashboard preference
// or transient HTTP 409 must not switch it to an unavailable WebRTC endpoint.
Object.defineProperty(window, "__SELKIES_STREAMING_MODE__", {
  value: "websockets", writable: false, configurable: false,
});
