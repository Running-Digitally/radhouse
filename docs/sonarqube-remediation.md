# SonarQube baseline remediation

Baseline: main `0585e0b222777255d2e603e4a8c30f2db22c7b39`, scanned locally on operator workstation
on October 7, 2026. Project `Running-Digitally_radhouse` has 484 distinct open
issues, including overlapping impacts: 8 security, 11 reliability and 469
maintainability. The passing gate does not resolve the baseline. Displayed
0.0% coverage reflects no imported coverage report, not measured test coverage.

Source remediation is complete on `codex/radhouse-sonarqube-remediation`, separate from
setup PR #69. Issue retrieval uses the signed-in SonarQube UI; the existing
analysis-only token correctly refuses issue-read API access. No finding status,
rule, profile or exclusion has been changed. No feature-branch analysis is
published. Final scanner proof requires the owner's later merge instruction,
then local analysis of the exact clean merged main commit. Community Build's
limited injection analysis does not establish complete application security.

## Reliability fixes

| Baseline issue | Rule | Location | Change and verification |
| --- | --- | --- | --- |
| `25a24518-20a5-4f5f-a4d1-13b1eb242248` | `javascript:S1143` | `src/radhouse/chat/static/chat.js:412` | Guard repaint after draft persistence without returning from `finally`. Keep pending errors visible when sign-out changes the session. Node regression tests exercise error propagation, sign-out during persistence, and successful cleanup; the error test fails on unchanged main. |

Affected call path: sign-in/startup → `openConversation` → history request →
draft persistence → current-session repaint. Session identity checks and draft
retention remain enforced. Validation: `node --test tests/chat-client.test.mjs`,
`node --check src/radhouse/chat/static/chat.js`, and focused Python chat,
configuration, provider and title tests. PostgreSQL-dependent tests require the
owned local fixture at closeout.

## Security dispositions proposed for owner review

These findings need contextual disposition, not altered allowlists or listeners.
They remain open in SonarQube pending approval for any external status change.

| Issue | Rule | Baseline location | Evidence and proposed disposition |
| --- | --- | --- | --- |
| `a22e818a-11b0-4a45-b431-c54996898963` | `python:S5332` | `deploy/production/model_catalog_proxy.py:73` | HTTP listener binds literal `127.0.0.1:8643`; deployment uses an SSH-forwarded catalog. No external listener or credentials are served by this catalog. Source-context not-applicable finding for the listener; upstream transport qualification remains separate. |
| `1db53da8-1949-4faa-95a5-98ec25cbc5a1` | `python:S5332` | `site/preview.py:65` | Static preview binds literal `127.0.0.1:8931`, serves site assets and synthetic QA routes, and is not the public deployment. Source-context not-applicable finding. |
| `4229c782-ed4d-4ebd-83ce-71c58fe60acb` | `python:S1313` | `src/radhouse/config.py:18` | RFC1918 range `172.16.0.0/12`, not a configured endpoint. False positive. |
| `448c2a1c-7d60-4890-98b1-8e74e72a4863` | `python:S1313` | `src/radhouse/config.py:18` | RFC1918 range `10.0.0.0/8`, not a configured endpoint. False positive. |
| `677610be-fc78-4e33-95e6-1f54b2cd63a0` | `python:S1313` | `src/radhouse/config.py:18` | RFC1918 range `192.168.0.0/16`, not a configured endpoint. False positive. |
| `64523602-7ba5-4d42-8c9e-bc3e6825c834` | `python:S1313` | `src/radhouse/integrations/openai_compatible.py:23` | RFC1918 range `172.16.0.0/12`, not a configured endpoint. False positive. |
| `79a4d240-69e6-4bed-a573-326ce80b1f06` | `python:S1313` | `src/radhouse/integrations/openai_compatible.py:23` | RFC1918 range `10.0.0.0/8`, not a configured endpoint. False positive. |
| `d52f3a5a-6c3f-44ec-827e-07616caf17d0` | `python:S1313` | `src/radhouse/integrations/openai_compatible.py:23` | RFC1918 range `192.168.0.0/16`, not a configured endpoint. False positive. |

S1313 addresses infrastructure coupling when a target host changes. These three
standards-defined ranges instead constrain a deliberately explicit private HTTP
opt-in in both configuration validation and the runtime provider. Moving them
into configurable operator values or broadening them to `is_private` would
weaken the reviewed boundary. Existing configuration/provider tests check
loopback, public endpoints, explicit RFC1918 admission, redirects and proxies.
S5332 addresses interception of cleartext network traffic. Both reported
listeners are fixed to loopback; no runtime deployment claim is inferred from
source alone. No production service is modified or deployed by this work.

## Bounded parsing and baseline readability

The complete sanitized issue inventory is `sonarqube-baseline.json`. Each issue
keeps its original ID, rule, source location and current source/disposition status.
A source correction is not a claim that a later main scan has closed the issue.

The chat formatter now walks delimiters with bounded lookups rather than a
backtracking expression. It preserves text-only HTML handling, safe HTTP(S)
links, emphasis, lists and copyable code. Node checks cover those contracts and
100,000-character unmatched/whitespace inputs. Heading cleanup also uses bounded
string operations. Document locators use small independent checks; explicit
ASCII flags preserve the original numeric scope, including rejection of Unicode
digits and noncanonical zero-prefixed positions. Byte encoders now use code-point
APIs on their existing byte-only inputs. The attachment picker has an accessible
label and the attach button has visible text.

The 173 composite test assertions are separated without dropping conditions.
The 77 exception checks isolate the tested operation from fixture construction;
rollback and privilege tests keep their entire transaction inside a named action.
Four composition class-state mutations are restored with `monkeypatch`. Fourteen
redundant exception subclasses were removed while preserving their superclass
handling. Explicit comments document intentional preflight/preview empty bodies.

Validation so far: 609 Python tests passed without a PostgreSQL fixture (194
appropriately skipped); 192 focused parser/attachment/integration tests passed
(one fixture-dependent skip); the web build and nine unit tests passed. The first owned full gate ran 837 tests with no skips and two browser failures.
Both failures passed on an isolated rerun (three tests, including parameterization);
no reproducible cause is established. The final owned gate is recorded below. The local SonarJS linter
confirms the formatter's two complexity findings are removed; it does not
replace the required main-only server analysis.

Three S1110 findings propose removing necessary grouping from upgrade rollback,
service status and error reporting. Their source expressions rely on Python
precedence; retain them as proposed false positives. S3415 already compares the
observed receipt IDs on the left with expected admitted IDs on the right; its
literal-set heuristic misidentifies the actual side. These dispositions remain
reviewable and have not changed SonarQube.

## Routing, composition and client refactors

Conversation routing separates addressed text, reply authority, focused task
selection and route effects. Guidance reconciliation keeps revision monotonicity,
identity verification, terminal uncertainty and operation writes inside the same
transaction. Provider construction, Buzz authority validation, client ownership
and TOTP matching use smaller named helpers. Removed parameters were private or
internal helpers with verified repository call sites; the runtime retry window
still begins in `begin_dispatch`, rather than reserving an unsent message.

The chat client separates card rendering, pending replies, retained draft restore,
upload preparation and error recovery. Its opening cleanup is awaited from
`finally`, preserving pending errors and current-session repaint checks. Explicit
blocks clarify previously ambiguous adjacent statements. Failure handlers either
show their existing fallback or explain retained retry state; none logs content or
credentials. Public analytics uses top-level await in its existing ES module;
classic chat/admin scripts retain their startup loading contract. Conversation
panel actions are grouped internally, and pure DOM/time helpers leave the mount
closure. Attachment budgets and exact byte digests remain unchanged.

Five status regions now use native `output` elements. The CSS/SVG illustration
retains its composite image role, consistent with [WAI-ARIA 1.2](https://www.w3.org/TR/wai-aria-1.2/#img).
The history pane remains keyboard-focusable and is explicitly a named region,
consistent with [scroll-container accessibility guidance](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/overflow#accessibility).
These two contextual findings remain open for review.

An earlier owned targeted fixture passed 98 tests, including authentication,
enrollment, conversation routing, guidance and the real chat walkthrough; cleanup
completed. Focused provider/configuration/composition/chat checks passed 157
tests. Web compilation and nine unit tests pass, as do the chat client/formatter
regressions. Local SonarJS checks have removed the baseline JavaScript complexity,
nested-conditional and ambiguous-block findings. A local Python approximation
matches 51 of the 55 baseline complexity values exactly and is only an iteration
aid; the authoritative verification remains the later main analysis.

The work-home UI separates timeline, task and project rendering from session and
review-target loading. Every awaited helper is followed by a request-generation
check before its result is used. The owned targeted fixture passed 77 tests,
including browser walkthroughs, guidance, review links and chat; cleanup completed.
Local SonarJS checks report no findings across the selected eight rules.

## Document readers, runtime responses and route ownership

Format readers, bounded passage scanning, cursor authentication and result
construction use named helpers. Original file descriptors, source identity
verification, stream lifetimes, process limits and parser-slot cleanup are retained.
Runtime responses separately validate image budgets, approval requests, guidance
receipts and activity metadata. API registration uses route groups while keeping
authentication before data access and before/after browser pixel requests.

Provisioning accepts an `InitialWorkHome` for the initial project/bot grant and
keeps existing keyword calls through an explicitly typed compatibility adapter.
Unknown, missing or conflicting fields fail before hashing or database writes.
The Hermes work adapter explicitly implements its existing `AgentWorkPort`
interface, including the required attempt argument. Two LocalSession findings
are proposed analyzer false positives: Python 3.14 `dataclasses.replace` delegates
to `_replace`, whose `self.__class__(**changes)` preserves the concrete class.
No Sonar issue status was changed.

Focused batches passed 186, 232 (three fixture-dependent skips) and 100 tests.
The later owned authentication/enrollment/migration batch passed 75 tests and
exposed a real chat restoration race in one browser test. An older history load
could enable/save the composer during a newer draft restore in the same session.
An opening-generation check now guards restore, history acceptance and final
cleanup. The regression fails on the prior source and passes on the fix. The
owned rerun passed all three browser tests and completed cleanup. The final full
owned gate is recorded below.

## Workflow phases and closeout

The inventory records 466 source corrections and 18 proposed contextual or
false-positive dispositions. No genuine baseline finding remains pending in
source. Scanner closure remains unverified until the later authorized main scan.

Task dispatch separates current grant checks, durable submission, acceptance,
runtime observation and terminal writes. Human controls retain their initial
capability read, authorization recheck, non-replayable operation receipt and
monotonic response reconciliation. Conversation ingress, guidance messages and
signed outboxes retain exact parent-event correlation and their shared authorized
transactions. Project routing separates addressed/reply/intent selection and
review/deployment handoffs. A per-event state holder preserves the already saved
revision if a later substep rejects the message. Exact preview, source and review
revision predicates and the private-release opt-in remain unchanged.

Owned workflow batches passed 71 and 65 tests, with cleanup complete. Local
SonarJS checks report no findings across eight selected rules. The calibrated
Python approximation reports no function above complexity 15 in affected
modules, including new helpers. These local checks aid iteration; they do not
claim equivalence to the main-only SonarQube analyzer.

### Final validation receipt

The complete required gate `uv run python scripts/vs0.py verify` passed on the
clean source commit `f49a493171d16567b5ffce7f7236ea000de63147`:
846 tests executed; zero failures, errors or skips. The owned container and volume
were removed and the manifest confirms `cleanup=complete`. Run identity:
`9495ce46d6d248d29ef4e86ca3dfb032`. The fixture records the pinned PostgreSQL 18.6
image and Python 3.14.4. Source fingerprint:
`94a86f8a8e964a7dff7d6cde6e067b6919751ed56b3e402a57c0c39b22cebbdb`.

`npm --prefix web test` passed compilation and all nine web unit tests. The chat
client/formatter Node suite passed all ten tests, including the generation-race
regression. The branch includes the fetched main commit and has no pending code
changes. This receipt updates documentation only after testing; executable source
is unchanged. Draft PR #71 remains unmerged, with no deployment, issue-status
mutation, suppression or feature-branch SonarQube publication.
