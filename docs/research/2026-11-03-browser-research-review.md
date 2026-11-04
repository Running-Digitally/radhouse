# Browser recovery and selected public research: review record

This records the candidate review for the [implementation plan](../plans/2026-11-03-browser-and-public-research.md).
Browser and research controls have been exercised on both native simulators.
Several reviewed follow-ups are merged and deployed; the acceptance findings and
processed-main analysis below distinguish those results from work still pending.
Physical-phone publication remains a separate release gate.

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

Both final simulator bundles restored their saved sign-in, displayed the live
browser and navigated to a public example page through native keyboard controls.
Private takeover, explicit observation and handback were exercised on each;
agent control and browser closure propagated across devices. The Android viewer
stalled on a later handback while the existing server assets were still deployed.
The candidate's bounded reconnect control has separate Chromium/WebKit coverage;
its deployed simulator acceptance remains a rollout gate. Temporary inspection
was removed from the simulator builds and Safari's developer setting was restored.

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
| `src/radhouse/chat/browser.py`: `96b7978c-846a-41ed-897a-051c703414bb`, `cb28af5a-b937-4582-a862-6a3912ecaad0`, `596c1981-7606-4330-ab2d-1cc1c783259e` | Subsequently addressed by extracting status validation, admission checks and vault item validation in the continuity follow-up below. Closure awaits its processed-main scan. |

The post-merge cycle must inspect both all-code and new-code findings, fix
applicable findings introduced by this change in a follow-up PR, and rescan the
follow-up merge. Existing backlog and a failed quality gate must remain visible.

## Native browser follow-up

The first functional changes merged in backend PR 129 and mobile PR 12. Their
processed-main scans were not clean: backend main `975aad56e2d2c470f63fc1b88fb51988a1b476db`
failed the new-code coverage/issue conditions; mobile main
`e45dc4749d0740fb392847c1a3e1a597d6a230e4` had one open nested-ternary finding.
Those merges did not establish native mobile UX acceptance or phone publication.
The owner subsequently required native controls and a live chat preview.

The follow-up adds a dedicated authenticated canvas document and a closed native
presentation/action contract. Native chat displays the view-only preview only
while the agent is active and controls the browser. Expansion preserves the
same tab and mounted conversation without taking control. Native address and
tools sheets, explicit Private/Observe and handback, reading zoom, reconnect and
foreground/session handling replace the full embedded web workspace. Reading
zoom blocks remote input so local panning cannot become a page action.

Simulator checks caught two platform-dependent failures before publication.
An initially hidden preview must still read browser status without mounting its
stream; otherwise it can never discover agent activity. Android also reports a
message's source origin, whereas iOS supplies the document URL. The Android
origin form is admitted only while the exact trusted canvas is loaded, with
navigation confined to that canvas and the owned stream. Remote web content
continues to execute in the isolated browser and contributes pixels only.

The earlier research simulator harness bypassed `SessionClient` and missed a
missing `research` action in its allowlist. The follow-up fixes that path and
adds real-client/component integration coverage for explicit enable, refreshed
saved revision and revocation. Earlier component-only evidence must not be read
as proof of the production client's authenticated request path.

The follow-up backend gate passed 2,470 tests, no failures/errors/skips, four
JavaScript browser checks and owned coverage with complete fixture cleanup.
It used pinned Hermes `818c13be1dc4fd28987e1e881a9408224afd4535` and a disposable
synthetic profile. The tested source fingerprint was
`d6ee22e3c9265d85f93b4bbd66c80fe7185180743814733e7f1dfb77b96771d6`.
A prior run correctly failed because it lacked the pinned source and skipped 68
checks; that run is not qualification evidence. The canvas separately passes
Chromium and WebKit preview/control/privacy/uncertain-outcome/expiry checks.
Mobile passes typecheck, lint, 161 application tests and 15 tooling tests.

Native simulator evidence includes preview, expansion, explicit takeover,
Private/Observe, handback and conversation continuity on iOS and Android. iOS
also shows the actual software keyboard with a compact preview and an accessible
native address sheet. These are synthetic-data checks; real deployed stream
navigation and physical phone publication/receipt remain separate release gates.

The broader web regression reproduced Send being pushed outside a narrow browser
chat drawer by the conversation toolbar and privacy bar. The targeted CSS change
reserves the focused drawer for chat and compacts its secondary toolbar/history
padding at keyboard height, retaining the privacy controls and mounted stream.
It also consolidates the duplicate privacy selector and overridden flex property.
The CSS change follows the full fixture run and has separate Chromium/WebKit
responsive regression verification; the merged-main scan must regenerate fresh
coverage for the complete final source.

The touched-file corrections address research collection/validation complexity,
ambiguous test assertions, unconditional JavaScript formatting, a redundant
conditional expression in the coverage launcher and the mobile nested ternary.
Closure is established only by the next processed merged-main analysis.
Additional pre-existing findings remain explicitly deferred:

- `app.py`: `9c62afc9-bc71-4a57-b73e-d177e0d6e32a` and
  `f6953f63-a3ca-49cc-8058-5f51bda10c54` concern application assembly and controlled
  routes outside the three static-asset routes. Refactoring their authentication
  and lifecycle paths requires a separate bounded change.
- `scripts/release.py`: complexity findings `aed15df4-f811-4b25-970e-89b5a2a56810`,
  `e8cfb83b-1928-40e6-9ce7-8d1027fa16bb`, `8cbb5336-b7c9-4acf-ad53-d38034ffb0c9`,
  `cfcf6769-e937-48e8-aa8e-60bda092fcd4`, `ab2f5c61-b8a1-4678-9039-eee4037b4bb7`,
  `c8a160d6-e03e-4e8b-a55d-e6922cd240f6`, `be247303-2834-4a4c-a40c-63ead861c001`,
  `78a201f9-06d9-49b0-8bb7-6cf8c2d7c412`, and `cbb33f75-8d66-4239-a83a-8f7a1d4d09db`
  concern release admission, manifests and operational transitions. This change
  only extends static-route verification; refactor the broader release lifecycle
  independently with its recovery qualification.
- `scripts/release.py`: `1a97b4c5-fa8c-498c-b7e2-d8e9fcefb73f`,
  `52a60062-a057-40b7-a3d1-f8fc1934b207`, and `ac2a6bdf-2c17-446c-a556-f2b1c98d8c9e`
  identify the standard private-network ranges in an address-admission check,
  not deployment endpoints. Retain the check and review the contextual findings
  explicitly; no suppression or server disposition is applied.

## Live reopen follow-up

Shipping-source simulator acceptance exposed a lifecycle conflict after a retired
browser: the next Open held the launch lock while finishing the previous stream,
whose already-completed native retirement tried to acquire that same lock. A
regression reproduced the conflict before the fix. Completed retirement now
returns without taking the lock only when the exact controller generation is
retired, its owned handle is absent, and its retained PID/start-time identity is
positively gone. Unknown or live drivers remain on the guarded path. The
regression also checks that missing process-exit proof cannot use that path.
Pinned Hermes qualification and adjacent browser, stream and native integration
checks passed: 418 tests. Live repeat-open acceptance remains pending rollout.

The processed `47a00a281d665b112b86b260bac4e200378c80d9` analysis had no findings
in the new mobile canvas or research contract files. Its overall gate remains
ERROR (new coverage 68.6%, 686 new-code issues); its owned verification passed
2,470 tests. This is an existing project backlog, not a clean backend gate.
Mobile main `7577fe0b2c92d39bb37252a97c42af491f2bdf53` passed its gate with
90.0% new coverage, zero duplication and no open issues.

The touched bridge's current findings were inspected. Repeated digest/name/page
literals and unused bindings were corrected (`329046f8-61cb-4a66-bdf4-6044c5fe236e`,
`3bc03915-8e81-49e2-83dd-b5875f9b61b1`, `87c29697-f84a-43ea-9258-7c599531a363`,
`43c18135-fb09-46ce-a84c-ad37828308f3`, `7ac86e2d-2e31-4165-96ee-569e14968f6a`,
`cf314fb6-d34f-4cfc-8288-f2d1af715e48`, `6ec542aa-8863-42d9-9dd5-d0a24f6a148b`,
`bbd06c69-2b14-4f7f-8c0a-6d2a2cfa5090`). Closure requires the follow-up scan.
The reconnect regression file had no open findings.

Bridge findings deferred with explicit reasons:

- Complexity findings `b81d52a2-9db9-4209-bd51-090a92954dc7`,
  `71fff00e-2072-469c-9fc7-c4e6e60d8963`, `81dbeb47-078a-49cf-b860-fdb05948ba4c`,
  `15ca4aeb-26e0-4af8-b102-035dcbf81890`, `e433bf86-6402-4761-97bd-8efce4022bfb`,
  `90932e63-e5f6-48e0-8e73-81ce9d93a1e6`, `8207f1ac-6ef5-4431-b0d7-f35f01e4b62f`,
  `919ebe0a-446d-43fc-aea1-d37cdf6d3d8c`, `95039eaf-25dc-4761-a25d-f1408dbdb34f`,
  `b1472bc1-191c-4ab9-8d71-c6d9454cb472`, `7f28feeb-dd3e-4a9b-9f89-59ded1589cc0`,
  `963b5c74-aaf2-4de7-98b8-54a1e5329f09`, `6d494d1d-f17d-48da-84d7-7d94e119ff00`,
  `fa279f40-990b-4fd5-b732-f204180c8bab`, `f7bdab05-b505-4f9b-94eb-a3732b3c96c3`,
  and `40a1d39c-3dad-4a5a-9848-cd0556882713` span callback, admission and lifecycle
  coordination. Their broader extraction belongs in the bounded stabilization
  work, with independent cancellation and pinned-runtime qualification.
- `895a5f32-9083-4332-9b99-7c3b9584f137`: the loop can remove retired entries;
  its list snapshot is required and is now explained in source.
- `03ffcee4-abb4-4f4d-8270-10d906345f19`: retain ASCII-only native element IDs;
  replacing `[0-9]` with Python's Unicode `\d` would broaden accepted input.
- `058a0c21-a5f8-4297-bb52-da8db5c0aa94`: retain the existing dispatch keyword
  contract; a signature change needs coordinated caller qualification.
- `3c00a263-32d2-44e4-9b4a-9293df2afdfd`,
  `865f9450-a2ae-403d-bc72-e2adb59ef7c7`: retain grouping around multiline
  retirement/outcome expressions during this bounded lifecycle correction.

No findings were suppressed or accepted, and no quality gate was changed.

## Live acceptance follow-up: address text and research references

The shipping-source iOS simulator reached the live private browser, but native
address submission selected the remote address bar without entering the URL.
The pinned Selkies core suppresses text echoes for 250 ms after a shortcut. The
adapter now waits 300 ms before the separate URL entry, rechecks the same input
controller, focus and visibility, and cancels on dismissal or intervening input.
The native canvas awaits that result and blocks overlapping commands. It does
not replay uncertain input or grant additional authority.

A native-provider acceptance case also returned a valid quotation alongside an
unsupported criterion number. Research publication now rejects unsupported
numbered references and URL references even when another quotation is valid.
The prompt explicitly asks for a general verification step when collected
sources only establish historical discussion. This bounded check does not
claim to prove every semantic statement in generated prose.

Review checked authority changes during the input delay, asynchronous failure
reporting, exact source identity, and preservation of the existing quiet and
notification cadence. Validation: 102 commitment/research tests, eight address
sequencing/cancellation cases, and native canvas journeys in Chromium and
WebKit. The latest processed merged-main SonarQube search found no existing
open issues in the five modified analyzed files. Post-merge analysis and live
navigation remain required before owner distribution.


## Live acceptance follow-up: browser continuity and native research output

Shipping-source iOS and Android both passed native address submission, Private,
Observe and explicit return to agent against the deployed service. A subsequent
ordinary chat request exposed a separate admission defect: the interface showed
agent control, but a new turn without explicit page context remained outside the
prior run's browser admission. The new turn now carries a server-frozen browser
binding only when the current live session already belongs to the agent. The
native controller still checks generation, revision and the previous run's
terminal state. Human, Observe, paused and recovering sessions are never acquired
implicitly; ordinary text does not attach page metadata. Retries reuse the saved
binding without resampling browser state. An optional browser outage leaves
ordinary chat available without inferring browser authority.

The native Hermes worker now uses fixed JSON-object output mode and deterministic
temperature through its supported request overrides. Provider-supplied arbitrary
overrides remain excluded. The worker has no tools, memory, identity files or
fallback model, and retains its existing time and token bounds. Publication still
checks the complete schema, owner quotation, source identity and exact excerpt.
The prompt now explicitly requests concise prose, the original owner quotation
and one quotation per cited source.

Live isolated acceptance retained failed results for malformed output, wrong
owner quotation, duplicate citations and an unsupported criterion reference.
Another rejection revealed that a historical-coverage caveat could name the
version in the owner's approved question without inventing a source claim. The
reference guard now permits numeric scope identifiers from that trusted question,
while still rejecting new criterion identifiers or uncaptured source URLs.
This is bounded identifier validation, not semantic proof of generated prose.
A subsequent real native-provider run completed in 49.09 seconds and published a
validated check-in from the isolated synthetic commitment. It cited one exact
excerpt and disclosed that the collected W3C mailing-list discussion was
historical, insufficient to establish the current final standard. This does not
claim exhaustive source coverage or physical-phone delivery.

The complete candidate gate passed 2,488 tests with no failures, errors or skips,
owned Python/JavaScript coverage, pinned native Hermes qualification and fixture
cleanup. The touched browser complexity findings above were refactored; the two
research-contract S6353 findings (`90b005de-d484-4090-acfe-766fd26bedce` and
`bf851f97-db6a-42c8-943f-f4d953fb2cd7`) use `\d` with explicit ASCII semantics.
The existing application-factory and controlled-route complexity findings remain
explicitly deferred: extracting their authentication and lifecycle assembly is
broader than the three-line replay compatibility correction. No suppression,
quality-gate change or coverage exclusion was applied. Follow-up merged-main
analysis and deployed mini-preview acceptance remain pending.
