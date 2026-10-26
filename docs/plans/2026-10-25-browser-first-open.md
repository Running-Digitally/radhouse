# Browser first-open connection

Date: 25 October 2026. Design depth: D1. Status: diagnosed; native acceptance passed on 26 October; no runtime patch required by this reproduction.

An explicit Open should start the viewer for the allocated browser without a
parent-page reload. The investigation must distinguish document initialization,
stream readiness and video playback; a blank viewer alone does not identify
which layer failed. Preserve Private/Observe authorization, generation and
lease checks, the authenticated fixed-path relay, and existing security headers.

Inspect the Open response through `BrowserView.update`, `BrowserStream.mount`
and the iframe's document/scripts, then the Selkies transport and first frame.
Add a regression that fails for the demonstrated cause before changing that
path. The correction should not replay browser actions, allocate another guest,
relax security policy or add a periodic page-reload workaround.

Acceptance: multiple fresh Open/Close cycles without reload, live video, human
input, Private/Observe controls, and a final idle runtime. Distinguish foreground
and background-tab observations. Test the fixed source locally, freeze it for
deployment, and retain installed evidence in Homelab.

The installed reproduction reached the viewer index on the server with HTTP200,
but Chrome showed its navigation as pending/Stalled, with provisional request
headers, no response headers, no script loads and an initial blank document.
It reproduced in the foreground, so background throttling alone did not explain
it. Detaching the browser automation debugger immediately released the existing
navigation: the index, scripts, WebSocket and video loaded without a parent
reload, another Open, server restart or source change.

Three subsequent native-only Open/Close cycles all produced live video on the
same parent page, with a distinct viewer connection each time. Native keyboard
input navigated the remote browser to Example Domain. Private → Observe →
Private kept human control and showed the corresponding privacy state. Final
Close left the installed worker idle, with its process unchanged. Operational
identities and evidence remain in the private Homelab record.

The observed trigger is debugger attachment in this acceptance session; the
debugger's internal defect is not established. Do not generalize this to every
automation session or claim that all possible first-open failures are solved.
The original transport interruption is a separate unresolved cause. The
already-deployed reconnect repair remains selected; this pass deploys no
runtime change and changes no authentication, privacy or network policy.

The existing `tests/conversation-workspace-browser.mjs` journey now starts idle
and exercises three explicit Open/Close cycles before its workspace checks. It
uses an external synthetic viewer script under same-origin CSP/frame headers,
including a delayed document. Assertions require live presentation, private
takeover, a unique connection per generation, one viewer load per Open, no
parent reload, status polling without remounting and iframe removal on Close.
This is lifecycle regression coverage; it does not simulate the installed
debugger failure or prove real video/input transport by itself.
Chromium and WebKit each passed all 17 checks in this journey. No production
source changed, so this pass makes no new runtime coverage or Sonar gate claim.

For installed acceptance, first use native UI controls without an attached
automation debugger. If an instrumented attempt stalls before scripts run,
compare native-only behavior and correlate the exact document request with
server status before blaming readiness, playback or the iframe mount order.
Do not export raw network headers, cookies or viewer token fragments as evidence.
Reopen the product investigation if the same symptom occurs without debugger
attachment, retaining document/asset/transport phase evidence. Avoid automatic
reload loops, action replay, extra guest allocation and security-header changes.
