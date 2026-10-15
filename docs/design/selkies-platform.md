# Selkies browser in the Radhouse conversation workspace

Status: implemented and deployed for the owner’s platform pilot, 2026-10-14.
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
  shrinks the stream and allows scrolling rather than clipping the keys. Browser
  mode uses a compact phone/landscape header to leave room for those controls.
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
retire each browser/native/stream generation together. The authenticated X
display stays private to the service. Stop the retired stream server and watcher
before launching another Chrome or replacing its durable identity; an active or
unproven generation cannot be replaced. Preserve vault authority
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

## Two human-control privacy modes

Owner addition: default every new takeover to **Private**. The owner can switch
that same session to **Let agent observe** and back without navigation, another
browser or a control transfer. Both modes keep agent browser mutations denied.

Private denies agent snapshots, screenshots, metadata/page context and any
observer delivery. Normal chat remains usable without attaching private page
context. Explicit Return to agent drains input and obtains a fresh safe
observation before new agent admission; minimize/Chat navigation never does so.

Observe permits only owner-bound, read-only page observations for the matching
conversation/run. It grants no click, typing, navigation or credential access.
A lease-scoped observation epoch invalidates old observer grants whenever the
mode changes; expiry, logout, disconnect, retirement and a new lease revoke
them. Make private revokes first, discards pending observations and waits for the
observation boundary before acknowledging Private. Sensitive-field checks apply
to observations even in Observe mode. No raw keystroke/event recording or model
training is introduced. Conversation-only follow-along is the proposed default;
reusable walkthroughs require a separate explicit decision.

Expose plain-language status and a single obvious switch while human control is
active. Take control is labeled private. No silent switch to Observe, including
on reconnect, agent requests, changing workspace emphasis or new takeovers.
Qualification must prove default Private, explicit Observe, mutation denial in
both modes, foreign/expired/stale observer rejection, and no late delivery after
Make private acknowledges.

## Deployment acceptance

The actual authenticated platform, rather than only the standalone pilot, was
exercised with synthetic requests and Wikipedia: agent navigation and snapshot,
Chat mini-preview expansion, direct keyboard navigation in human control,
default Private snapshot denial, explicit Observe snapshot while retaining human
control, confirmed privacy revocation, fresh handback and close/reopen. The same
unsent draft survived workspace navigation. Strict native qualification separately
proved the sandbox, owner-bound relay, large asset delivery, live video and
negative authority cases. The Homelab change record owns frozen selections and
receipts. Desktop viewport emulation does not prove an actual phone OS keyboard.


## Mobile recovery and explicit device transfer

A video play rejection or paused inline video produces an explicit local
playback prompt. A synchronous same-origin helper retains the trusted tap;
it changes playback only, outside the remote input target. Playback readiness
is distinct from the input lease and actual frame presentation. A page resume
can request playback again but cannot reacquire control.

When another owner tab holds the input lease, expose Move control here rather
than a dead end. Only an authenticated viewer already eligible for control and
bound to the same principal can request it, with the current generation/revision
and an explicit typed move flag. Revoke the old durable lease before waiting for
the shared input/observation barrier; discard late reads, release held input and
clipboard state, then fence a new Private lease. Stale/view-only/foreign-owner
requests do not revoke the holder. Failed drain stays blocked. The old stream
can never resume input by reconnecting, and an old disconnect cannot revoke the
new lease. Qualify this boundary on the real native runtime, and test playback
policy rejection and trusted-tap recovery separately in Chromium and WebKit.


## Live usability follow-up, 15 October

The owner confirmed iPhone/desktop controls and authorized real browsing/chat
checks. Live testing found that the large portrait header consumes about 225px
in phone Chat and 170px on desktop, while a short phone chat drawer can place
Send below the viewport. The responsive fixture reproduces the latter in
landscape. This D1 correction changes presentation only: compact the portrait
header in Browser and phone Chat, keep the Browser heading and Chat toggle
reachable, and temporarily fold the browser display while the chat composer
has focus in a short/keyboard viewport. Preserve the same iframe, stream, draft,
privacy and control lease; restoring height or leaving the composer restores
the display. The nested app shell must follow the visual viewport height, and the draft
field and message-options menu must use that height for their bounds. Preserve
the options menu outside the composer rather than clipping its popup.

Affected files are conversation-workspace.css and the existing workspace browser
fixture. Verify both Chromium and WebKit, short landscape/phone heights, Send
bounds and touch size, privacy/context bars, draft retention, stream identity,
preview expansion/minimize and restored browser display. Then select web source
only and repeat the signed-in journey. Hermes, Selkies and input authority do
not change. The remote desktop remains 1280×900; Fit is an overview and Zoom
requires panning on phones. Persistent post-task previews are a later product
decision: the current requested behavior hides the preview when agent browser
work stops. These checks do not emulate a physical iPhone OS keyboard.


Live Zoom geometry also exposed unreachable left/top edges: the enlarged
1280×900 iframe inherited centered flex alignment, leaving negative offsets
that a scroll container cannot reveal. Anchor the zoomed iframe at the top
left so Chrome controls and the complete display are reachable by panning.
A regression checks both edges and the full scroll range, then returns to Fit.
