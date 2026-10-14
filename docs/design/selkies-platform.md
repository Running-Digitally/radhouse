# Selkies browser in the Radhouse conversation workspace

Status: accepted owner direction; implementation in progress, 2026-10-14.
Design depth: D2. [ADR-0002](../decisions/0002-selkies-browser-viewer.md) owns
package selection. This document owns its platform integration and interaction.

## Outcome and baseline

Replace the platform's frame polling and individual human-operation UI with
Selkies video/input around the actual agent-owned Chromium. Preserve the deployed
`4702ac5` UX baseline, existing authentication, conversation, drafts, queued turns,
Library, browser preferences, saved-login vault and seven native agent tools.
The isolated 8444 pilot has proven the package; it is not the platform browser.
VM220 serves the web app; VM270 owns Hermes, its browser controller and Chromium.

## Conversation and browser presentation

Use one persistent browser component/stream and one existing chat/composer DOM.
Changing emphasis must not create a browser, remount the stream, lose a draft,
move keyboard focus into the remote page, or transfer control.

- Chat is dominant by default. A small live browser card appears while the agent
  is using its browser (or a human intervention remains active). Hide it when
  no browser work is active. The card is viewing-only; click/Enter opens Browser.
- Browser is dominant in its navigation tab. On desktop, keep the same chat and
  composer alongside it. Minimize switches emphasis to Chat, preserving both
  sessions and scroll/draft state. Opening Browser never takes control itself.
- On phones, prioritize the browser and offer a Chat drawer with a message badge
  and the same composer. Chat focus dismisses remote keyboard assistance. Remote
  keyboard focus keeps browser controls reachable; a reduced visual viewport
  shrinks the stream and allows scrolling rather than clipping the keys.
- Retain the full-width three-column Keys panel, 44px touch targets, safe-area
  padding, explicit keyboard override and compact status. Fit/zoom remains local.
- Clearly show agent/human/paused/disconnected state. Reconnect must not replay
  input or take control. Closing/minimizing a view does not resume an agent run.

## Runtime and ownership

Keep the authoritative BrowserController and native channel in Hermes. Add a
small Selkies platform adapter in that same process, using its actual OwnedBrowser
identity and the existing StreamingControl lock/drain boundary. The private
single-owner deployment permits one active streaming browser; refuse another
identity until the previous one is positively retired. Do not route chats to a
shared independent pilot browser or create another controller database.

Launch a private Xvfb display and headed sandboxed Chromium for that owned
browser; the restricted native driver attaches to the same process. Track and
retire the display/browser/native processes together. Preserve vault authority
and verified browser binary identity. Package Selkies and its client assets in
a frozen, root-owned release, isolated from the existing Hermes dependency tree;
verify effective dependency versions and source hashes before activation.

The adapter exposes owner-bound viewers minted only through authenticated browser
status/control calls. Bind each token to principal, conversation, auth-session
digest/revision, browser tab and generation, with authentication expiry. Never
return service credentials, CDP addresses or native sockets to the client.

Reuse Selkies' secure viewer/mk-role handling and existing restricted stream input
allowlist. All takeover, handback, agent admission, expiry, disconnect and close
paths share the same input lock, fence, held-input/clipboard drain and fresh
observation. A typed private handover proof may admit only the matching fresh
run after a successful drain. Legacy human input endpoints must not provide a
second injection path when streaming is selected. Keep explicit saved-login
operations under their existing owner/lease checks.

## Web transport and contracts

The web app serves authenticated `/chat/browser/stream/…` HTTP/WebSocket routes
through its existing Hermes tunnel. Hermes relays only the fixed browser stream
path to a private local Selkies listener, preferably a service-user Unix socket.
No public route, new LAN listener, root broker or new account is needed.

Every HTTP request and socket upgrade requires current app authentication and
same-origin checks. WebSocket connections recheck authentication and close on
logout/expiry; Selkies still checks the generation/lease for every input event.
Strip app cookies before forwarding and retain the existing service-token
boundary. Deny upstream dashboard, terminal, files, media, settings and resize
APIs. Do not log viewer tokens, socket query strings, text or clipboard payloads.

Browser status adds validated stream metadata and agent-activity state to its
existing generation/control/page context. A status read may mint/reuse an
owner-bound viewing token but cannot create a browser or grant control. Existing
Open/Take/Return/heartbeat/close contracts keep auth, origin, CSRF and tab binding.

## Delivery and evidence

1. Preserve the exact deployed UX source, freeze the adapter/UI contracts and
   qualify a disposable browser through the actual native and stream boundaries.
2. Implement shared workspace emphasis and responsive controls; test mini-preview
   visibility, click/keyboard expansion, draft/history retention, chat focus,
   authority transitions, view-only/foreign-session denial and keyboard-sized
   viewports. Test expired/logout sockets and recovery without input replay.
3. Freeze a paired web/runtime release. Recheck current source, idle work,
   credentials/profile integrity, capacity and containment before selection.
   Retain code/state evidence and patch forward; no rollback or data restore.
4. Deploy the actual platform replacement, log in to Radhouse and exercise an
   explicit synthetic browsing conversation, takeover, keyboard, Chat/Browser
   emphasis, handback and reconnect. Do not claim fixture checks as a logged-in
   model journey. Retain sanitized counts/screenshots, not owner conversation text.

The existing pilot's non-ASCII X11 mapping limitation remains open; do not claim
international-text acceptance from ASCII checks. iPhone keyboard opening was
owner-confirmed; revised physical-phone layout/Android acceptance is distinct.
