# SonarQube baseline remediation

Baseline: main `0585e0b222777255d2e603e4a8c30f2db22c7b39`, scanned locally on Lisa
on October 7, 2026. Project `Running-Digitally_radhouse` has 484 distinct open
issues, including overlapping impacts: 8 security, 11 reliability and 469
maintainability. The passing gate does not resolve the baseline. Displayed
0.0% coverage reflects no imported coverage report, not measured test coverage.

Work is in progress on `codex/radhouse-sonarqube-remediation`, separate from
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
Four composition tests restore mutated class state with `monkeypatch`. Fourteen
redundant exception subclasses were removed while preserving their superclass
handling. Explicit comments document intentional preflight/preview empty bodies.

Validation so far: 609 Python tests passed without a PostgreSQL fixture (194
appropriately skipped); 192 focused parser/attachment/integration tests passed
(one fixture-dependent skip); the web build and nine unit tests passed. Owned
PostgreSQL and browser verification is in progress. The local SonarJS linter
confirms the formatter's two complexity findings are removed; it does not
replace the required main-only server analysis.

Three S1110 findings propose removing necessary grouping from upgrade rollback,
service status and error reporting. Their source expressions rely on Python
precedence; retain them as proposed false positives. S3415 already compares the
observed receipt IDs on the left with expected admitted IDs on the right; its
literal-set heuristic misidentifies the actual side. These dispositions remain
reviewable and have not changed SonarQube.
