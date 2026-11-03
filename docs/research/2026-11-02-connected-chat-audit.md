# Connected chat usability audit and implementation

Date: 2 November 2026. Scope: authenticated web chat and the native mobile
`Connected` screen. This is an engineering audit with synthetic data, not a
user study or a production rollout receipt. The mobile development preview is
not the implementation target.

## Research and design decisions

Nielsen Norman Group's [AI chatbot design research](https://www.nngroup.com/articles/ai-chatbots-design-guidelines/)
identifies continuity across pages, progressive disclosure, reading without
forced scrolling, and saving/sharing answers as useful design patterns. We
apply those findings to a persistent personal conversation: keep the composer
available, preserve drafts and loaded history, disclose model settings on
demand, and make returning to the latest answer explicit. Search and quoting
extend these patterns to longer-running work. Their effectiveness in Radhouse
still needs owner feedback; the research does not validate this implementation.

[WCAG status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)
supports announcing progress without moving focus. Status labels distinguish
saved, queued, working, complete, and failed states. They do not invent token
streaming or expose hidden reasoning. [WCAG target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
sets a 24 CSS-pixel minimum with exceptions and recommends larger important
targets. Our primary chat actions use at least 44px/points. That design choice
is not a claim of complete WCAG conformance.

The prior mobile planning and LifeOS chat design work informed fixed composers,
keyboard clearance, visible model selection, draft continuity, and readable
answers. Radhouse adds per-provider capability discovery, immutable retry
settings, safe loaded-history search, and selectable native reply text. Product
flows remain tied to Radhouse's actual backend capabilities.

## Findings and changes

| Observed problem | Implemented response | Verification |
| --- | --- | --- |
| Connected mobile chat was a transcript/form with limited navigation and presentation | Dedicated conversation surface; distinct user bubbles and assistant answers; headings, lists, inline formatting, safe links, horizontal code blocks | Actual `Connected` component tests and iOS simulator |
| Composer competed with history and tabs when typing | Composer outside the scrolling transcript; existing iOS keyboard avoidance and Android resize retained; tabs hide while keyboard is visible | Software keyboard on iPhone simulator; component event regression |
| Mobile could not select the web model/thinking contract | Authenticated discovery; model sheet with selected radio state; supported thinking choices; visible next-message selection | API-body test, connected-screen tests, model admission/wire tests |
| A lost response could make retry settings ambiguous | Freeze request ID, text, provider, model and thinking together; explicitly retry the identical payload | Lost-acknowledgement regression |
| Model discovery failure could undermine confidence in a selected model | Retain selection, mark it unavailable and block a new selected-model send; explicit Default remains usable | Missing-model and discovery-failure regressions |
| Returning to a conversation required scanning everything | Search loaded exchanges; web result navigates and focuses the original exchange; mobile filters loaded exchanges; earlier history merges by stable ID and sequence | Web keyboard/phone checks; native pagination/search tests |
| New data could disrupt reading or discard older loaded history | Follow latest only while already at the bottom; explicit Latest action; merge polls with earlier history | Native no-jump and history-retention regressions |
| Reusing an answer meant retyping | Quote a bounded excerpt into the existing draft; web keeps Copy; native uses selectable text and platform Share | Source-fidelity assertions; simulator draft preserved through model changes |
| Web settings were easy to overlook | Always-visible model summary; settings remain in a disclosure panel; OpenAI context notice; distinct question/answer layout | Chromium desktop, 390px and 320px checks; visual review |
| Screen reader model button omitted current selection | Announce the current model/thinking as the control's accessibility value | Component contract and source review |

Search is explicitly limited to loaded history. Quoting is capped at 1,200
characters and never sends automatically. Native drafts remain in memory across
workspace tabs and foreground transitions; they are not durable across force
quit. Signing out clears private screen state. Native Markdown is a deliberately
small text renderer, not full Markdown/HTML parity; remote images are not loaded.

## Model contract

See [OpenAI setup and qualification](../openai-models.md). Both clients use the
same `radhouse.inference.v1` discovery and per-message selection contract. The
server handles credentials, model availability, effort admission and native
transport. No provider key belongs in either client bundle.

## Verification and boundaries

- Full repository verification: 2,323 tests, zero failures, errors or skips,
  with owned PostgreSQL fixture cleanup complete. Model/runtime targeted suite:
  272 passing tests against the pinned Hermes source.
- Three live synthetic Responses API tool-call/answer round trips: Astra, Terra,
  Sol, all completed using the configured key. No owner conversations were sent.
- Chromium: search, quote, exact selected model payload, capability-dependent
  thinking, unavailable-selection recovery, keyboard focus through an active-reply poll, and 320/390px layouts.
- Mobile: full quality command, including type checking, lint, component/session
  tests (105 passing) and tooling tests (15 passing), 95.44% line coverage;
  iOS Release simulator and Android debug builds, plus Android production JS bundle.
- Native visual check: separate synthetic-only app using the production
  `Connected` screen. Draft survived model selection; software keyboard left
  model, draft and Send visible; navigation tabs hid while typing.

Android physical-device keyboard behavior, screen-reader end-to-end use, large
Dynamic Type, sustained very long transcripts, and real-world owner task timings
remain release acceptance checks. The synthetic harness does not prove live
push, network latency, or production model enrollment. No store submission or
production rollout is included in this implementation.

## Touched-file quality review

The latest dated [SonarQube report](2026-10-25-sonarqube-findings.md) was used as
an index, then current processed findings were read from the signed-in server.
The mobile project's processed baseline had no open findings. Web/runtime
cleanup separates inference discovery/admission helpers, simplifies status
rendering and conditionals, reuses media-type constants, and puts the touched
browser assertions in a recognized test case. Release tooling received bounded
literal/unused-variable/assertion cleanup alongside the new asset and test entries.

[Issue-level dispositions](2026-11-02-chat-touched-findings.json) retain all
reviewed keys, including deferred authenticated-route/browser/stream/release
lifecycle complexity and contextual classifications. Larger lifecycle refactors
are follow-ups with their own regression scope. No issues were suppressed,
accepted, or closed on the server. Local cleanup is not merged-main scan closure.
