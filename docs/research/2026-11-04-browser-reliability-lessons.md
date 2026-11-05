# Browser reliability: findings and repeatable acceptance

Date: 4 November 2026. Scope: the browser recovery, native interface and chat
mini-preview work of 3–4 November. This is an evidence-backed engineering
retrospective, not a claim that every device or underlying codec defect is fixed.
The [browser guide](../selkies-browser.md) owns current behavior. The private
operational dossier owns deployed identities, distribution receipts and original
screenshots; they do not belong in public Git.

## What we learned

There was no single “browser bug.” Service recovery, video initialization,
decoder progress, frame ownership, layout and product acceptance failed at
different points. A healthy service, connected socket or passing unit test did
not establish a usable browser. Repeated rendered transitions with preserved
drafts and privacy were the release criterion.

| Finding | Evidence and correction | Limit of the conclusion |
| --- | --- | --- |
| Startup readiness was incomplete | Reviewed source changes left recovery-manifest entries stale. Startup rejected them; a nominally running sandbox also lacked a valid placement. Provenance reconciliation and positive retirement/replacement restored startup. | Container health alone cannot prove guest recovery. Do not disable pin validation or replay uncertain creation. |
| iOS playback could connect without a first frame | The worker-produced video remained at zero video width/ready state until the foreground Browser WebView permitted silent playback. | This was a scoped Browser setting, not a reason to relax Terminal, origin, auth or background rules. |
| Android could receive video without decoding it | Decoder input accumulated without output. The pinned upstream watchdog skipped shared viewers. A second early return in its metrics caller also prevented the first correction from running. | The owned adaptation addresses observed stalls; it does not establish the underlying engine root cause or universal recovery. |
| Viewer lifecycle mattered across handback | Capability/generation changes now create fresh viewer documents; status messages must match both origin and the current frame's window. Initialization has one bounded video-only retry. | Reconnect must never replay navigation, input, takeover, return or another uncertain mutation. |
| A blank mini was sometimes a layout failure | Actual video dimensions differ from page viewport dimensions. Width-fit/top clipping made the mini readable; a night-theme hover rule then covered the running video, and autofocus could scroll an overflow-hidden preview. Selector specificity, `overflow:clip` and `min-height:0` corrected those cases. | Neither socket counters nor “Live” text proves the pixels are visible to the user. Test themes, hover, focus and constrained height. |
| Diagnostics could change the symptom | In one live web reproduction, detaching the browser automation debugger initialized the stalled viewer without a reconnect or code change. | This is an observed diagnostic interference case, not proof that every stall is caused by automation. Retain evidence of both attached and detached states. |
| Functional opening was insufficient product acceptance | The owner required native address/privacy/tools controls, a useful expanded viewport and a live mini within chat. An embedded copy of the full web application did not meet that requirement. | The remote page remains a streamed desktop surface. Duplicate remote Chrome controls were explicitly accepted for this release; a chrome-free launch was reverted and remains a separate design choice. |
| Activity and availability are different | A browser remains useful after a tool call finishes. `previewAvailable` keeps a dismissible Browser ready card; `active` describes current agent activity. New generation/activity resets dismissal. | Expansion grants no input authority. Hidden/private preview states must redact title/address as well as pixels. |

## Follow-up design: make browser handoff discoverable

Proposed 5 November. A physical phone user recovered agent navigation by taking
control of a paused browser and explicitly returning it. The visible **Live**
label described playback while **Browser paused** described control. Chat was
reachable without the handoff, and the navigation tool was offered even though
the turn lacked a control binding for the existing browser. The broad tool
error led the agent to tell the user to re-enable access without naming an
available action.

Use a persistent, compact handoff prompt beside the composer when a browsing
request is blocked. Keep the same action in the browser footer. Distinguish
**Private · Only you**, **Paused · Agent needs control**, **Agent can browse**,
and **Agent is browsing** from playback state. Label observation as read-only.
Keep ordinary chat and its draft available. No private title, URL or frame
belongs in the blocked chat card.

The first implementation uses the authenticated browser status to show
**Open browser to return** beside the web and native composers. It opens the
existing controls without taking control. On phones **Return to agent** sits
above the browser canvas so the keyboard cannot cover the button at the
bottom. A small optional canvas status indicates a return in flight. For
ordinary chat with a known live Human or Paused browser, the web service
freezes a handoff-required reason with the turn, omits browser tools and
prompts the agent to name the recovery action. Explicit Observe and handoff
still use their existing routes. First-use launch on an idle session is
available. Transport failure and uncertain execution remain distinct.

For a direct **Return to agent** from a paused browser, require a fresh,
authenticated owner action and server proof that this generation is safe to
return. The current route expects a live human lease; do not simulate one with
hidden takeover calls. Use **Review browser** when another device holds control,
the page changed, sensitive input needs clearing, or safety is uncertain.
Keep existing input-drain, clipboard, sensitive-field and prior-run checks.
During the handoff, show **Returning…** until the server acknowledges it.
Only offer **Return and retry** for an identified request the server confirms
did not execute. A view change or an ambiguous response cannot authorize replay.

Acceptance starts with the reported path: take private control, go to Chat,
request a public navigation, and recover from the visible prompt while
preserving the draft. Check web, iOS and Android with the keyboard open, then
verify the live mini returns only after handoff. Exercise second-client
ownership, stale state, sensitive fields, and an unconfirmed handoff.
See [Apple feedback guidance](https://developer.apple.com/design/human-interface-guidelines/feedback)
and [Microsoft's human–AI interaction guidelines](https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/).

The candidate also separates tool capability validation from tool selection
(`3207b2d1-7493-438f-b0be-60ac5d781b8a`) and browser status application from
polling (`ac2593e3-7739-4ac9-9781-b195ac4b63a9`). The browser session tests
separate the existing compound assertions and isolate the two expected error
calls. Closure requires analysis of the merged changes. Broader dispatch
preparation and reply polling refactors (`5fd15e74-64ec-4b0b-ae18-0d3cb9b3a079`,
`1ac36a71-6302-41ee-99b6-757dc7bd1772`) remain separate, as do the four
remaining chat client findings below. The conversation history's focusable
scroll area (`a4f7fee7-7b32-45b8-93c4-9f485267b396`) stays keyboard reachable
pending a separate cross-browser accessibility check.

## Contracts that must survive future changes

- Keep the remote browser, its generation, controller lease, viewer connection
  and presentation mode distinct. Replacing a video document is not replacing
  the remote browser or authorizing a control action.
- The current initialization retry waits five seconds, remounts video once, then
  waits ten seconds before exposing a stalled/reconnect state. It resets for a
  new capability/generation; it must not become an indefinite reload loop.
- Preserve the native conversation and composer while expanding/collapsing.
  Draft preservation during navigation/resume is not a promise of native draft
  persistence across force quit. Web persistence has its own storage contract.
- Native controls own the app interaction; only the fixed authenticated canvas
  is embedded. The native bridge accepts a closed set of commands and validated
  presentation fields, never arbitrary remote-page code or credentials.
- Private takeover fences agent reads/actions and removes other clients' preview
  content. Backgrounding, expiry and sign-out remove native preview content.
  The controlling web client can still see its own private browser. Test these
  per-client semantics instead of treating every hidden frame identically.
- Public research on confirmed commitments remains a separate, explicit opt-in
  using an isolated collector. Interactive browser access does not grant access
  to owner profiles/cookies or authorize research, messages or external changes.
  A validated citation establishes captured-source provenance, not factual truth
  or whether an old discussion represents a current requirement.

## Troubleshoot by locating the failing boundary

1. Record the exact server source, client build, OS/WebView, theme, foreground
   state, selected generation/control mode and whether debugging is attached.
   Do not log capabilities, cookies, input, credentials or private page text.
2. Prove launch/recovery identity and readiness. A retired or uncertain remote
   execution needs lifecycle reconciliation; a video refresh cannot repair it.
3. Distinguish authentication/transport, incoming encoded frames, decoder output
   and actual frame presentation. “Connected but black” is not a diagnosis.
4. If decoding/presentation progresses, inspect computed layout, video aspect,
   overlays, clipping, hover/focus and scroll position before changing transport.
5. Compare full and mini views, then takeover/handback, background/resume and a
   second client under Private. Check capability changes and ignore stale-frame
   events. Use a fixed public fixture and a recognizable unsent draft.
6. If behavior differs under automation, run one bounded comparison without the
   debugger. Do not repeatedly restart the guest to conceal a viewer failure.
7. Change the smallest implicated layer; first prove that case is fixed. Preserve
   failed evidence as failed. Do not count a Connecting screenshot or an old
   in-memory asset document as candidate acceptance.

## Repeatable release acceptance

Write this matrix before implementation. A pass names its source/build and
evidence; a test plan, prepared build or earlier revision cannot fill the cell.

| Journey | Required observation |
| --- | --- |
| Web, three consecutive cycles | Open/expand → private control → visibly rendered public page → return to agent → rendered mini. No manual reconnect; draft unchanged. |
| Android, three consecutive cycles | The same sequence in the actual native app, including native address entry. Retain screenshots of full/private and returned-mini states. |
| iOS | Fresh foreground/resume, private takeover and return, rendered frames and unchanged draft. Check the actual native layout, not only a responsive web fixture. |
| Agent browsing | A bounded public navigate/snapshot task visibly changes the mini and completes with the expected page titles. Restore any test draft; do not authorize unrelated agent work. |
| Privacy across clients | While one client controls privately, other clients show neither stream nor page title/address. Verify view-only expansion and background/session removal. |
| Release identity | Candidate acceptance → reviewed commit → merged-main analysis → deployed hashes → signed package → store/group availability → physical installation. Record each separately. |

The three web and three Android cycles, iOS checks, cross-client privacy and
bounded agent use passed on the presentation candidate. A final web smoke test
passed after the subsequent behavior-preserving Sonar extraction. These are
web/simulator observations; physical-phone acceptance was still unconfirmed at
the recorded closeout.

## Regression ownership and validation order

| Concern | Existing executable protection |
| --- | --- |
| Decoder recovery is actually reachable | `tests/selkies-decoder-recovery.mjs` invokes the patched metrics-timer caller, not only the watchdog helper. |
| Full/mini lifecycle and usable layout | `tests/conversation-workspace-browser.mjs`: repeated real return handlers, draft retention, dismissal reset, video/page aspect mismatch, night-theme hover, no mini scrolling, keyboard and constrained viewports. |
| Native canvas recovery/authority | `tests/mobile-browser-recovery.mjs`, `tests/test_mobile_browser_canvas.py` and the mobile repository's `__tests__/native-browser.test.tsx`. |
| Draft/history client behavior | `tests/chat-client.test.mjs`; its synthetic DOM must implement the APIs used by the actual source without replacing the behavior under test. |

The merged-main gate caught a missing `querySelector` method in the synthetic
chat DOM: four cases failed before reaching their draft/history assertions.
Adding stable child lookup corrected the fixture without weakening assertions.
This small Node lane belongs in local targeted validation before the expensive
full gate. A helper-level test also missed the upstream caller's early return;
tests must exercise the production invocation path.

Use focused tests and live visual acceptance while fixing the defect. Once the
matrix is green, review/merge and run required gates on frozen source. SonarQube
Community Build here scans committed remote main, not the invoking feature
checkout. Fix an actionable finding in a small follow-up, validate that delta,
merge and scan that exact revision. A fresh code change or failure justifies a
repeat; unchanged uncertainty does not justify another broad cycle.

## Why the session took too long

The initial definition of done was narrower than the requested experience.
Functional, visual, privacy and release evidence were mixed together. Several
repairs were accepted at a lower layer before the full transition was proved.
Builds/scans and simulator checks then repeatedly encountered new blockers, and
“final checks” overstated how close the work was to completion.

The corrective workflow is one live acceptance matrix and one release ledger,
updated with the current blocker, next discriminating check and smallest fix.
Agree a bounded simulator window early, coordinate shared devices, and batch UI
work while the Mac is available; continue independent preparation during locks.
Existing authorization persists, but authentication expiry remains a real
dependency. Report “uploaded, assignment unverified” rather than “released.”
Archive superseded candidates and prevent them from being used as current proof.

## Reviewed source and closing analysis

Backend [PR 139](https://github.com/Running-Digitally/radhouse/pull/139) contains
the viewer/mini corrections; [PR 140](https://github.com/Running-Digitally/radhouse/pull/140)
repairs the DOM fixture; [PR 141](https://github.com/Running-Digitally/radhouse/pull/141)
extracts preview activity state. Final analyzed backend main:
`6d9eb4af29047226682171f439ecc24e17a6d062`.
Mobile [PR 17](https://github.com/Running-Digitally/radhouse-mobile/pull/17)
merged as `03e397c4dd796d84734e84323150024f5ac24581`.
Reviews were recorded as source-review comments; no independent approval is
claimed. The earlier [decoder investigation](2026-11-03-viewer-decoder-recovery.md)
retains its failed intermediate approach and caller correction.

Closing verification passed 2,490 backend tests, four browser checks, complete
fixture cleanup, and 19 focused workspace checks in each of Chromium/WebKit.
Mobile passed typecheck/lint, 161 Jest and 15 tooling tests. Its processed gate
passed with zero open issues and 90.1% new/90.3% overall coverage.

The new backend `javascript:S3776` finding
`afae46b6-e9eb-41a1-95a9-cf06373521ed` was server-confirmed Closed (Fixed).
The existing backend gate remained FAILED: 667 issues in its configured new-code
period, 68.8% new coverage, 0.88% new duplication and zero hotspots; overall
coverage was 72.1%. A processed analysis is not a passing gate. The launcher
retains `test_coverage_imported=false` on nonzero gate exit; submitted reports
and the processed UI measures are separate evidence. No gate/profile/exclusion
or issue disposition was relaxed.

Five older touched-file findings remain explicitly deferred: `ac2593e3-7739-4ac9-9781-b195ac4b63a9`
(`refreshBrowser`), `56c916b0-7282-4d10-bdfa-611b2cac0939` (`showPage`),
`f8164a38-858a-4d11-aed1-a22fe619d3d7` (`recoverOutgoing`),
`ac545e96-e756-4d5c-918f-c9d4001f940e` (composer submission), and
`d4f47b60-734e-434c-a06d-13a8c579a367` (startup async IIFE). The first four
need broader status/navigation/outbox refactoring; the last changes the classic
script startup contract. They remain in the existing backlog, not a duplicate
delivery plan in this retrospective.
