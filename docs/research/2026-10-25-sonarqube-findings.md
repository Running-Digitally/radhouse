# SonarQube findings — 25 October 2026

This is a report-only snapshot after merging
[Radhouse #109](https://github.com/Running-Digitally/radhouse/pull/109).
The analyzed source is merged main
`5ab9a8ab333582d5810978903f82abf748ce50ea`. Findings were not remediated,
accepted, suppressed or marked false positive during this scan. The existing
quality gate, profiles, exclusions and new-code definition were retained.

## Dependency fixes and verification

Before the merge, DOMPurify was updated from 3.4.16 to 3.4.17 and markdown-it
from 15.0.2 to 15.0.3, including the required argparse 3.0.4 lockfile update.
`npm audit --prefix web --json` reports zero vulnerabilities at this snapshot.
The web build, all 14 Node tests and the PostgreSQL-backed browser Markdown
walkthrough passed. That walkthrough exercises sanitization, blocked scripts
and unsafe links, source fidelity, preview, review and follow-up behavior.

Upstream release records: [DOMPurify 3.4.17](https://github.com/cure53/DOMPurify/releases/tag/3.4.17)
and [markdown-it 15.0.3](https://github.com/markdown-it/markdown-it/releases/tag/15.0.3).
These dependency fixes are separate from the SonarQube findings below. This
pass did not deploy the dependency updates to a running instance.

## Processed analysis and quality gate

The reviewed `scripts/sonarqube.py` launcher cloned remote main and ran its
owned synthetic fixture before uploading source and coverage. The full run
passed **2,069 Python tests with zero failures, errors or skips**, three browser
coverage checks and fixture cleanup. The dependency-specific web checks above
also passed. No owner profile or live conversation data was used.

| Evidence | Result |
| --- | --- |
| Server | Community Build 26.8.0.126808, MQR mode |
| Analysis ID | `7d96540b-51ce-48ad-a4ca-8fcf5781ce56` |
| Processing task | `a12fd293-a51e-4505-8a8e-71bd454be0b7` |
| Server processing | `SUCCESS`, completed 2026-10-25 22:17:20 UTC |
| Quality gate | **Failed**, two conditions failed |
| New-code definition | Previous version, beginning 2026-10-07 23:02:55 UTC |
| New-code issues | **712**, required zero |
| New-code coverage | **66.9%**, required at least 80%; 14,616 lines to cover |
| New-code duplication | **1.09313%**, passes the maximum 3% condition |
| Overall coverage | **71.4%**, 24,934 lines to cover |
| Overall duplication | **1.1%** |
| Open issues / affected files / rules | **811 / 136 / 55** |
| Older-code issues | **99** outside the configured new-code period |
| Security / reliability / maintainability impacts | **22 / 137 / 781**, overlapping categories |
| Test-source / main-source issues | **455 / 356** |
| Accepted issues / reported security hotspots | **0 / 0** |

The 712 new-code findings cover the period since 7 October, **not just PR #109**.
The dashboard reports a net increase of 74 open issues since the previous
16 October analysis (737 to 811). Several changes landed between those scans;
this is not an attribution of all 74 to the recovery PR or of every issue to a
demonstrated defect. Impact counts overlap and must not be summed as unique
issues. Security and reliability ratings are D; maintainability is A.

Both Python XML and JavaScript LCOV were parsed by the scanner. The launcher
exited 3 on the failed gate and conservatively retained
`test_coverage_imported=false`; its receipt is unchanged. Successful server
processing and the following fresh component measures independently confirm
coverage import. A failed quality gate is distinct from a failed upload or a
failed test run.

| New recovery module | Server coverage | Line coverage | Branch coverage |
| --- | --- | --- | --- |
| `scripts/hermes_offline_restore.py` | 97.1% | 98.8% | 91.7% |
| `scripts/recovery_set.py` | 98.9% | 99.2% | 98.0% |
| `src/radhouse/chat/worker_control.py` | 98.0% | 99.1% | 94.7% |

These are whole-module measures, not proof that every recovery condition is
correct and not the project's new-code coverage. Existing test failures were
not hidden to generate the reports.

The server reported one encoding-warning category. The scanner log identifies
38 binary media files (26 WebP, six MP4, three WebM and three PNG) being inspected
as UTF-8. This did not prevent processing. It is recorded for later scanner
configuration review; no assets, source encoding or exclusions were changed.
Community Build also reports limited injection analysis. This scan and the
clean dependency audit do not establish complete application security.

## Findings to use as a cleanup index

All 811 unique open issue records were retrieved through the signed-in,
read-only issue API in two pages (500 and 311). The
[machine-readable file index](2026-10-25-sonarqube-file-index.json) records
counts for every affected file. It is an index, not a replacement for the
server's individual issue records. Source paths and issue keys below refer to
the analyzed commit; line numbers can move.

| Largest rule families | Open issues | Review focus |
| --- | --- | --- |
| Python `S9073` | 236 | Composite assertions; retain every asserted guarantee. |
| JavaScript `S8784` | 113 | Assertions outside recognized test cases/hooks; inspect the actual harness. |
| Python `S3776` | 94 | Cognitive complexity; preserve admission and cleanup invariants during refactoring. |
| Python `S5778` | 94 | Exception-test boundaries; ensure the intended operation triggers the assertion. |
| Python `S1192` | 28 | Repeated literals. |
| JavaScript `S3358` | 28 | Nested ternaries. |
| CSS `S4666` | 25 | Repeated selectors. |
| JavaScript `S3776` | 14 | Cognitive complexity. |
| JavaScript `S2681` | 14 | Conditional-statement scope; verify intended behavior. |
| Python `S5886` | 12 | Return-type contracts, including dataclass replacement paths. |

The largest file concentrations include `tests/interface-browser.mjs` (41),
`runtime/hermes/bridge.py` (25), `tests/quiet-chat-browser.mjs` (25),
`tests/test_browser_control.py` (24), `tests/test_hermes_browser_sessions.py`
(24) and `tests/test_selkies_control.py` (22). Counts alone do not set risk
priority; a smaller security or reliability finding may matter more.

### Security and reliability examples for later review

These remain open and unadjudicated by this pass. A rule label is not evidence
that an attack is possible, and a contextual explanation is not a waiver.

| Issue key | Rule and location | Follow-up when the file is touched |
| --- | --- | --- |
| `d6ed098d-21cd-429a-9ab9-804cb15c5303` | `python:S2612`, `src/radhouse/chat/worker_control.py:123` | Review the 0755 control-directory permission against operator/worker ownership. |
| `50fa1149-40de-4c3c-bf5b-56569d90db1e` | `python:S2612`, `src/radhouse/chat/worker_control.py:125` | Review the 0644 admission-lock permission and required read/lock access. Do not change it mechanically. |
| `da748fb1-8bfc-4fd3-9da9-9374acd90757` | `python:S5443`, `runtime/selkies/space_guest.py:137` | Verify shared X11 socket-path observation and display ownership/collision handling. |
| `5d7e2a71-4a3e-486a-aca1-320761dcc7bf` | `python:S5443`, `runtime/selkies/platform.py:119` | Review shared temporary-path handling in its existing lifecycle context. |
| `6ee62fe0-f758-44a7-9504-1e855248af68` | `python:S5443`, `runtime/selkies/qualification.py:436` | Verify fixture temporary-path ownership and cleanup assumptions. |
| `dea89b1f-b405-49c9-a2c4-466dee302b95` | `python:S7487`, `runtime/selkies/network_worker.py:201` | Review synchronous subprocess behavior inside an async function. |
| `5e6fdd67-00bd-4a0b-a720-3d9d715e468c` | `javascript:S7059`, `src/radhouse/chat/static/owner-terminal.js:26` | Review asynchronous constructor work and lifecycle/error propagation. |
| `d05291be-02cb-434d-878d-0913f1a5d591` | `css:S4657`, `src/radhouse/chat/static/conversation-workspace.css:66` | Verify the intended `flex-basis` behavior before changing the overriding shorthand. |

Other security families concern private-address policy constants, HTTP paths,
UI pseudorandomness and an image's default user. Prior contextual assessments
are in [baseline remediation](../sonarqube-remediation.md) and the
[boundary stabilization plan](../plans/2026-10-15-boundary-stabilization.md).
Those assessments must be checked against current source; this scan did not
change their external status.

### Recovery-code maintainability findings

| Issue key(s) | Location | Finding |
| --- | --- | --- |
| `7a0d169f-81da-4953-875f-1cff493fbc42` | `src/radhouse/chat/worker_control.py:68` | `S3776`, cognitive complexity 17 against 15. |
| `ac396703-2a7c-48c2-9dca-be22e1708b80` | `scripts/recovery_set.py:52` | `S3776`, complexity 21 against 15. |
| `b97515d5-429a-4d4f-b60e-ecbd2936e4eb` | `scripts/recovery_set.py:101` | `S3776`, complexity 30 against 15. |
| `741d66f4-5bfa-4b51-97b2-460c9395ee74`, `1c062395-e8ea-4a1e-922b-2823d2e53bc3` | `scripts/recovery_set.py:69`, `:92` | `S1192`, repeated payload/manifest literals. |
| `5bb319b6-0c78-4099-aadd-c102a717942f` | `scripts/recovery_set.py:55` | `S1940`, negated identity comparison. |
| `ae4296aa-fd6e-468b-8e3f-480876fb7e19` | `scripts/hermes_offline_restore.py:43` | `S1192`, repeated archive-name literal. |
| `c8695f25-5cf4-4c0e-b24f-7ff72c571f0a` | `scripts/hermes_offline_restore.py:51` | `S7494`, dictionary-construction style. |
| `06e064a9-2e9e-4549-bf80-c3a5800edc6f` | `tests/test_hermes_offline_restore.py:28` | `S5778`, exception-test structure. |
| `eed8117e-3b2a-46e7-9a57-73003d719ddf`, `98265379-cb68-4028-9816-cff06448ea73`, `32bf785a-9266-4c9c-813f-e92b63f9c3f8`, `7d130916-fc2f-442f-b2ad-15e5836f2eca` | `tests/test_worker_replacement.py:91`, `:137`, `:154`, `:160` | `S5778`, exception-test structure. |

No open issue was returned for `tests/test_recovery_set.py` in this snapshot.
That is not a claim of complete test adequacy.

## Evidence retained

Local receipts and coverage remain under the ignored directory
`.sonarqube/20261025T221054222694Z-5ab9a8ab3335/`: `receipt.json`,
`verification.json`, `python.xml`, `lcov.info`, `scan.log` and `report-task.txt`.
The public index contains only source paths, counts and analysis identifiers;
it excludes issue authors, credentials, local paths and operational records.
The later documentation-only closeout does not change analyzed source; the
scan above remains explicitly tied to `5ab9a8ab333582d5810978903f82abf748ce50ea`.

## Using this report during ordinary development

When editing an analyzed first-party source or test file, check its current
open findings and address applicable ones alongside the intended change.
Prioritize security and reliability; preserve behavior, ownership boundaries
and meaningful test assertions. Do not rewrite unrelated files to clear a
metric. If a finding needs context, a larger design decision or work outside
the current task, record its key, reason and follow-up explicitly.

This snapshot is a routing aid, not a completed adjudication of every issue.
Check current source and server state before acting. Confirm closure with a
later authorized merged-main scan. A local edit, test pass or proposed
false-positive explanation does not establish SonarQube closure.

The owner-local `AGENTS.md` contains the touched-file cleanup instruction and
is deliberately ignored and untracked. The public scan contract remains in
[the SonarQube guide](../sonarqube.md). An explicit report-only instruction,
including this pass, takes precedence over the default cleanup workflow.
