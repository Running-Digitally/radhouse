# Browser recovery and selected public research: review record

This records the candidate review for the [implementation plan](../plans/2026-11-03-browser-and-public-research.md).
Final browser simulator acceptance, merged-main analysis and rollout are still pending.
Research controls have been exercised on both native simulators with synthetic data.

## Behavior and boundaries

- A failed browser launch can be replaced only after positive retirement proof.
  Ambiguous lifecycle acknowledgements remain blocked, including after restart.
- Viewer reconnect changes only the viewer connection; it does not replay a
  browser operation or change Private, Observe or agent control.
- An unavailable retired download outbox is disclosed separately from a current
  collection failure. Missing files are never reported as saved.
- Research requires an explicit public question on a confirmed active commitment.
  Only that question reaches the qualified native web provider. Collection has
  no owner browser profile, credentials, private conversation or model tools.
- Collection and publication recheck the review, grant, commitment revision and
  source snapshot. Stop, snooze, completion, corrections and permission changes
  invalidate stale work. Research can be stopped while global reviews are paused.
- Citations must match captured source IDs and exact excerpts. Source dates and
  authority still require judgment; provenance validation does not prove truth.
  An outage preserves the last successful fingerprint to avoid duplicate alerts.

## Candidate verification

The final backend verification completed 2,466 tests with no failures, errors or
skips, generated owned Python/JavaScript coverage, and completed fixture cleanup.
It includes the pinned native Hermes qualification, browser checks and synthetic
database recovery paths. The recorded checkout commit was `06957467f01bf0ec2f34bbf10028fdd6fad6eac8`;
the tested candidate source fingerprint was
`9258c22b9ef459161c334aa28b46e0e7bb08310038d879a85647778fce311fc1`.
This is candidate verification, not a merged-main SonarQube result.

Separate Chromium and WebKit checks exercised stalled-viewer reconnection without
replaying input. Web research controls exercised enable, exact-question submission,
coverage, inert text rendering, citations and stop at desktop and mobile widths.
Native public collection plus tool-free inference also produced a structurally
valid, source-checked result from a synthetic public question. Native simulator
interaction and physical-device delivery remain separate acceptance gates.

## Native simulator findings

Both native research flows exercised explicit question submission, coverage,
citations, independently stopping research and completing a follow-up. iOS also
covered revocation during a global pause, progress, snooze and resume. Android's
citation tap opened the exact public source URL. These use the actual routes and
components with synthetic commitment data; they do not grant research to an
owner commitment or establish physical-phone delivery.

The iOS browser reproduced an independent playback issue: its worker-generated
video track stayed at readyState 0 and videoWidth 0 while native WebView required
a playback gesture. With playback permitted for the foreground Browser view,
the track reached readyState 4, videoWidth 1280 and visibly presented frames.
The final simulator bundle, without inspection or diagnostics, also navigated
to the public example fixture through its keyboard controls. Mobile typecheck,
lint, 151 application tests and 15 scanner-tooling tests pass. The initial canvas
diagnosis was incomplete: the pinned client had selected its
worker VideoTrackGenerator path. No canvas workaround is needed. Terminal keeps
its existing playback policy; the shipping viewer has no diagnostic script or
inspection flag. See the [WebView API](https://github.com/react-native-webview/react-native-webview/blob/master/docs/Reference.md#mediaplaybackrequiresuseraction).

A disconnect during browser relay cleanup also raised an uncaught
WebSocketDisconnect. The relay now handles an already-disconnected peer, with a
real ASGI/WSProto transfer regression that also exercises cleanup failure.

## Touched-file SonarQube review

The existing processed-main findings were re-read before changes. Local fixes
address repeated platform literals, unused callback parameters, launch complexity,
unnecessary gateway iteration copying, ambiguous JavaScript condition formatting,
nested ternaries and composite/ambiguous test assertions. Closure must be checked
by a processed scan of the merged revision; none is claimed from local edits.

The following existing findings remain explicitly deferred. No issue disposition,
quality gate, rule or coverage exclusion was changed.

| File and issue keys | Reason and follow-up |
| --- | --- |
| `runtime/selkies/platform.py`: `1978e5ca-62a5-4172-b9c9-d4d2823b08b1`, `bda4d41f-1938-4159-ab1a-149154d0435e`, `96c5af21-9237-4aca-8432-39a9cedf94e5`, `0c289519-a416-4afd-a87d-41c1df3cccab` | Existing configuration, startup/teardown and streaming coordination complexity. A broader extraction needs separate pinned-runtime and cancellation qualification; this change limits lifecycle edits to positive retirement reconciliation. |
| `runtime/selkies/platform.py`: `1e1f7c99-0ecb-44ba-838c-8114eb634479`, `e20c09d5-af1c-4b4b-8007-6293272e1553` | These functions implement asynchronous callback contracts even when their bodies need no await. Keep the contract; review a contextual disposition separately rather than adding artificial awaits. |
| `runtime/selkies/platform.py`: `19d2ce96-2cad-4cc4-a607-efb5c476d71f` | The loop removes viewers from the iterated mapping, so its list snapshot is required. Source now explains this; no suppression or false-positive status is applied. |
| `runtime/selkies/platform.py`: `5d7e2a71-4a3e-486a-aca1-320761dcc7bf` | `mkdtemp` creates a private directory and the authority file is mode 0600. Retain the hotspot for explicit contextual review; do not replace safe temporary creation with a predictable name. |
| `runtime/selkies/space_gateway.py`: `dcc0d072-b2e5-482e-9d6f-fe5a1a833bcd`, `072afbe9-5688-4f53-af93-d7d1ec16ea80` | Existing attachment rotation and authenticated forwarding complexity. Refactoring the admission/proxy path is broader than the retired-outbox receipt change and needs independent transport qualification. |
| `src/radhouse/chat/browser_transport.py`: `0cca92cd-eab0-4044-8e29-9126d17c96f7` | Existing route-installation complexity spans authenticated HTTP and WebSocket admission. Keep the observed disconnect fix bounded; extraction needs separate relay qualification. |
| `src/radhouse/chat/browser.py`: `96b7978c-846a-41ed-897a-051c703414bb`, `cb28af5a-b937-4582-a862-6a3912ecaad0`, `596c1981-7606-4330-ab2d-1cc1c783259e` | Existing browser status, reconnect and activity state-machine complexity. This change only propagates the prior-outbox availability field; consolidate the state machine in the established stabilization work. |

The post-merge cycle must inspect both all-code and new-code findings, fix
applicable findings introduced by this change in a follow-up PR, and rescan the
follow-up merge. Existing backlog and a failed quality gate must remain visible.
