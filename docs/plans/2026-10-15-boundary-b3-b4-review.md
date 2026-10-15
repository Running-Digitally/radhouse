# B3/B4: interruption, recovery and analyzer contract review

Date: 2026-10-15. Owner: repository maintainer.

Status: source review and candidate verification complete. Exact-main analysis
is a separate post-merge step. This record does not authorize or claim another
pilot deployment.

## Scope and result

Continue the proportional boundary plan from the deployed S1/B1 and B2 slice.
Review the three broad-exception findings, ten state-return findings and six
async callback findings individually. Allocate the 41 runtime complexity records
by responsibility; retain the existing review date of 14 November, accelerated
by changes to authority, recovery, dependencies, exposure or the affected code.
The private register retains issue membership and source-function evidence.

One concrete interruption defect needs a small owned bridge fix. Two broad
handlers and all sixteen contract-sensitive findings have evidence supporting
retention of their current contracts. They remain open on the server pending the
separately authorized finding-review process. A contextual review is not a
claim that SonarQube closed the issue or that the complete quality gate passes.

## B3: keep cleanup ownership and preserve interruptions

The owned browser launch path tracked native work and attempted exact-process
cleanup on any failure, but then converted cancellation, keyboard interruption
and process exit into an ordinary `browser_launch_failed` rejection. The fix
keeps the existing cleanup path and sanitized ordinary errors, then re-raises
non-Exception interruptions to the owning executor. It does not broaden tools,
retry a launch, relax process verification or infer retirement from absence.

The regression covers interruptions before native spawn and after a native
launch attempt, with both verified and unverified process identity. Nine cases
fail before the fix. Verified retirement releases resources; unverified native
work remains tracked and another Open cannot launch a replacement. Ordinary
launch failures retain the fixed rejection code.

The other two findings are in `bootstrap.qualification_output`: its initial
wait and direct child reaping deliberately catch interruptions until the bot
canary finishes its own cleanup. A missed deadline, signal or failed wait must
never produce a successful qualification. Narrowing those handlers could
abandon browser descendants. Existing signal/timeout/late-signal tests and
expanded repeated-interruption and real-child-finally tests support retaining
the handlers. The observer never kills the canary to meet its deadline. A hung
child therefore remains an operational recovery obligation, not a successful
qualification or permission to proceed with maintenance.

The complexity inventory is allocated to these enduring responsibilities:

| Responsibility | Review action |
| --- | --- |
| Browser launch, identity, ownership and recovery | Focus the fix and failure tests on launch; preserve exact-process proof, retained generations and admission fencing. |
| Human input, native ACKs and terminal dispatch | Retain lock/sequence/lease checks and uncertain-effect behavior. Run actual UDS and PTY regressions; no dispatcher rewrite. |
| Qualification, source staging and sandbox evidence | Preserve fail-closed observations, child cleanup ownership and source-pin checks; no generic exception-narrowing sweep. |
| Inference configuration, registration, rendering and remaining request routing | Defer structural cleanup to changes in the relevant product boundary, with the recorded review trigger. |

This class-level allocation does not claim every complex function has been
fully audited. Decomposition is justified when it makes an invariant easier to
prove, rather than merely moving branches until a threshold passes.

## B4: retain concrete state types and awaitable contracts

All ten return findings are in `browser_control.BrowserController`:
`admit_run`, `complete_agent`, `request_takeover`, `confirm_takeover`,
`heartbeat`, `observation_mode`, `begin_return`, `begin_close`, `pause` and
`retire_browser`. They load a `ControlState` and use `dataclasses.replace`;
the operation constructs the same concrete dataclass, including its nested
lease/owner types. The declared `ControlState` return type is correct.

A full takeover/observe/handback/re-admission/close sequence verifies concrete
state and lease types, unchanged earlier snapshots, owner/generation binding
and equality with a freshly opened durable controller after each transition.
Existing tests retain stale-owner, uncertain-input and privacy denial coverage.
No annotation is weakened, cast inserted or replacement wrapper introduced.

| Async finding | Actual contract |
| --- | --- |
| Platform `clear_clipboard` | `StreamingControl._drain_locked` awaits it and requires a positive clear result before handback. |
| Platform `resume` | `StreamingControl.handback` awaits it after revocation, draining and fresh observation; it publishes typed handover proof. |
| Qualification `clear_clipboard` | Uses the same awaited drain callback; qualification must preserve the production interface. |
| Qualification `resume` | Uses the same awaited handback callback and admits a fresh typed run. |
| Qualification `status` | Registered as the aiohttp GET handler for `/qualification/state`. |
| Qualification `diagnostics` | Registered as the aiohttp GET handler for `/qualification/diagnostics`, with the existing viewer authorization check. |

These functions have synchronous bodies but asynchronous consumer contracts.
Removing `async` would change the returned object and break those consumers.
No dummy awaits or additional scheduling points are added. The unchanged Linux
qualification remains evidence for its original source; local contract tests
are not a fresh Linux/X11 or installed-pilot qualification of this new commit.

## Validation and remaining stage

Candidate verification passes all 1,782 tests with zero failures, errors or
skips, including native PTY tests with pinned public Hermes source. Coverage
checks pass and the owned synthetic fixture cleanup is complete. The focused
boundary run passes 278 tests; nine regression cases fail before the fix.

Retain the exact merged-main scan receipt in the private session record. Preserve the
existing rules, gate, analysis scope and new-code period. Use a follow-up PR if
the processed scan reveals a relevant new defect; do not suppress warnings to
claim closure.

B3/B4 source review does not close S5 by itself. Effective deployed browser
network-policy enforcement remains an explicit evidence gap. The prior scanner
failure's diagnostic-retention follow-up also remains open. Product latency and
model tool-use observations are separate from these Sonar findings. Wider
complexity, style and assertion cleanup retain their owners and review triggers;
no upstream engine fork or zero-issue campaign is part of this change.
