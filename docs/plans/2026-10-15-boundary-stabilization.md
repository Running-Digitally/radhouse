# Immediate boundary stabilization plan

Date: 2026-10-15. Owner: repository maintainer. Implementer: the continuing
coding session, with review of each bounded change. Status: scope expansion and
planning prepared; expanded merged-main analysis and final prioritization pending.

This is the implementation handoff for the current session. It does not claim
that planned controls, tests or remediation have already been delivered.

## Outcome and limits

Establish an honest baseline for all owned code, then make the current pilot's
trust boundaries sufficiently explicit and tested that product changes do not
accidentally widen authority or corrupt state. Preserve useful product learning.
The target is low residual risk and manageable debt, not a zero-finding trophy.

The owner reports no customers and private-LAN-only deployment with no public
ingress. Verify the relevant runtime assumptions privately before relying on
them for a finding's disposition. Public source development continues with
synthetic examples and sanitized evidence; raw security evidence stays private.

Research is still shaping customer outcomes, managed-service responsibilities
and package boundaries. Treat Chat, Runtime, Computer, Knowledge, Guard, Work,
Attention and Evals as candidate logical responsibilities, not eight services
to build now. Preserve the current assistant and its state. Qualify stable
boundaries before extracting packages, and require product value for each later
extraction. No new engine, second harness/memory system, vault rewrite, terminal
rewrite, or general Hermes/Selkies cleanup is part of this stage.

Decisions: [ADR-0003](../decisions/0003-proportionate-security-and-public-development.md)
and [ADR-0004](../decisions/0004-replaceable-runtime-adapters.md).

## Baseline and uncertainty

The pre-expansion review inspected all 620 open issue records from the
2026-10-15 14:32:23 UTC analysis of merged source
`c67faa907fad844e9b3bf0d57e9b9efb3ee08e7c`. It grouped all rule families and
checked material source examples. It did not adjudicate each issue as a defect
or false positive. Main had subsequently advanced to
`00071e45a46eeed49acc5c5395503345f7a48220` when planning began.

| Observation | Pre-expansion result | Interpretation |
| --- | --- | --- |
| Open issues / files / rules | 620 / 93 / 42 | Includes all overall findings; 542 are in the configured new-code period. |
| Security / reliability / maintainability impacts | 15 / 145 / 598 | Impact categories overlap; do not add them as separate issues. |
| Test-source findings | 433 | Much of the count concerns assertions/test structure; preserve their guarantees. |
| Current chat / other Python / scripts / site / earlier web / deploy | 107 / 27 / 23 / 21 / 6 / 3 | Remaining 187 records, grouped by location. |
| Overall / new-code coverage | 75.8% / 69.2% | Existing new-code threshold is 80%; runtime was outside source scope. |
| Overall duplication | 1.6% | Existing new-code threshold is 3%. |
| Accepted issues / security hotspots | 0 / 0 | Neither means there are no security risks. |

The 15 security-impact records concerned private-address policy constants,
loopback HTTP and non-security randomness. They need contextual verification;
their labels alone are not evidence of exposed credentials or exploitable paths.
Conversely, an omitted runtime cannot be presumed safe. Expanded findings and
relevant dependency/runtime evidence may change every priority below.

The largest existing families are Python composite assertions (208), JavaScript
assertions at script level (132), exception-test structure (82), and cognitive
complexity (58 across Python/JavaScript/TypeScript). Blanket mechanical rewrites
would be a poor first step. Inspect actual exception boundaries, failure exits,
state transitions and readable assertions before choosing a fix.

## Delivery order and review units

Each row is a reviewable unit; split it further if its behavior or recovery
cannot be reviewed together. S1 findings determine which of S2-S4 need code
changes. Existing passing evidence may satisfy a requirement when its source,
configuration and execution scope actually match; do not rebuild working
controls simply to make this plan appear implemented.

| Step | Deliverable and likely files | Dependency | Exit evidence |
| --- | --- | --- | --- |
| S0 — Expand measurement | `sonar-project.properties`, `pyproject.toml`, agent instructions, ADRs, security policy and ownership map. | None | Reviewed merge, normal exact-main scan, all-source inventory including owned runtime; coverage provenance and scope verified. |
| S1 — Triage the expanded baseline | Private issue register plus sanitized public summary; active capability/dependency/patch inventory. | S0 | Every open issue inventoried and assigned to fix-now, fix-when-touched, defer-with-trigger, upstream action, or candidate contextual/false-positive review; every material boundary issue individually reviewed. |
| S2 — Lock current authority contracts | Minimal active-lane contract documentation and focused negative tests around `bridge.py`, browser controllers, `native_control.py`, and chat routes. | S1 | Identity, capabilities, observation consent, generation fencing and uncertain-effect behavior proven; no speculative replacement engine. |
| S3 — Resolve material boundary defects | Only confirmed findings and gaps in credentials, terminal, browser/network containment, admission and data handling. | Relevant S1/S2 evidence | Regression reproduces the defect before the fix and passes after; relevant browser/runtime qualification passes. |
| S4 — Qualify recovery and dependency response | Pinned adapter/patch compatibility, state ownership, release/rollback evidence and candidate replacement checklist. | S1 and affected S2/S3 changes | Interrupted work, incompatible pins, unavailable engine and rollback preserve authority/data; unsafe capability can be disabled without silent fallback. |
| S5 — Close and establish the ongoing budget | Fresh overall/new-code comparison, residual-risk register, documentation and implementation receipt. | Required S2-S4 complete | Immediate acceptance criteria met, unresolved debt owned, follow-up triggers explicit, next product slice identified. |

Suggested planning allowance: one short stabilization iteration. Re-estimate
after S1 rather than promising a date from the old count. If serious findings
make it larger, contain/disable the relevant capability and re-plan that risk
explicitly. Keep unrelated product research moving. After S5, start with roughly
one fifth of engineering capacity for debt and boundary tests, plus defects
fixed in touched code; adjust against actual incidents, change friction and
product learning. This is a planning recommendation, not a scheduled automation.

## S0: exact procedure

1. Confirm worktree, branch, HEAD, dirty state and remote main. Use an isolated
   checkout so concurrent sessions and uncommitted work remain intact.
2. Include `runtime/` as first-party source. Exclude only the immutable upstream
   Hermes fixture tree; classify the owned Selkies fixture as tests. Retain
   existing source/test roots and generated/vendor exclusions. See the
   [ownership inventory](../runtime-ownership.md).
3. Include Python runtime execution and unexecuted namespace modules in coverage.
   Check the produced report contains all 21 owned non-fixture Python modules
   at the planning revision. Do not claim imported runtime JavaScript execution:
   the current LCOV converter has a documented scope gap. Those source files
   still enter SonarQube's source/coverage denominator.
4. Run focused scan-safety/privacy checks and a coverage-scope experiment. Review
   the diff for private data. Commit, create a PR and integrate the bounded
   scope change under the owner's authorized merge/rescan sequence.
5. Use the reviewed launcher from [the runbook](../sonarqube.md). The normal
   command installs locked dependencies and runs the owned full fixture before
   scanning. Preserve its no-skips, exact-source, digest and cleanup requirements.
   A qualification failure must be repaired; do not silently use `--static-only`
   to manufacture a successful baseline.
6. Record the merged SHA, server analysis/task ID, timestamp, processing result,
   gate result, overall/new-code measures and scan-context scope. Verify material
   runtime files are indexed. A quality-gate failure is expected to be possible
   and is distinct from a failed upload or failed server processing. Resolve
   the launcher receipt's conservative import status against server evidence.
7. Fetch all open issues and hotspots, paginate until totals reconcile, deduplicate
   issue keys and retain a private export. Include older findings. Do not apply
   `inNewCodePeriod`/new-code-only filters. If the API result window truncates,
   partition by disjoint components/rules and reconcile the union.
8. Update this plan with actual expanded counts and S1 priorities in a follow-up
   commit/PR. A scope increase is an observation change, not an increase in
   defects caused by this PR. Keep the old scoped baseline for comparison.

## S1: disposition and risk ordering

Record issue key, rule, file/line, analyzed SHA, source ownership, active or
retained lane, enabled capability, impact/exposure evidence, decision, owner,
required tests, dependency, review date/trigger and closure evidence. Keep
sensitive details private; public summaries can use sanitized categories and
linked fixes. SonarQube status changes require the applicable separate authority.

Prioritize reachable authentication/authority bypass, secrets/private-data
exposure, destructive replay, data-loss/recovery faults and containment failures.
Then address defects that threaten reliable use or make these boundaries hard
to review. Complexity matters where it obscures transitions and invariants;
splitting functions merely to meet a threshold is not sufficient.

Review each security-impact record, each high/critical reliability record and
each finding in an enforcing boundary individually. Lower-impact test/style
families may be grouped when their behavior and disposition match, retaining
per-issue membership. A supposedly unused path requires configuration/call-site
evidence; a missing graph edge or a future rewrite is not evidence of disuse.

For dependencies, record the actual pinned/deployed version and available
advisory evidence for Hermes, Selkies, Chromium, native browser components,
base images and application dependencies. Separate repository pins from actual
running versions. SonarQube first-party findings do not constitute a complete
dependency audit, infrastructure audit or prompt-injection assessment.

## S2-S4: boundary acceptance matrix

These are checks to verify or add, not claims that the current implementation
is defective. Reuse the tests listed and inspect whether they are executed by
the relevant qualification command. A test file's existence is not proof of a
passing release gate.

| Boundary | Required behavior | Starting evidence and likely changes |
| --- | --- | --- |
| Runtime admission | Authenticate before parsing privileged operations; owner/conversation/run identities stay bound; missing/incompatible capabilities fail closed; uncertain start does not duplicate work. | `tests/test_hermes_runtime_bridge.py`, `tests/test_runtime_private_configuration.py`, `tests/test_native_inference_runtime.py`; document active native API separately from earlier descriptor mode. |
| Human/agent browser control | Two tabs/conversations cannot gain simultaneous authority; Private denies reads and writes; Observe is explicit/read-only; stale epoch/generation and revoked/expired auth are denied; handback drains input and requires fresh observation. | `tests/test_browser_control.py`, `tests/test_selkies_control.py`, `tests/test_native_control.py`; relevant Selkies browser/security journeys. |
| Credentials | Validate exact origin and recheck navigation races before fill; never expose plaintext through return values, logs or transcript; wrong profile, bad key permissions and uncertain native acknowledgement fail safely. | `tests/test_vault_bridge.py`, `tests/browser-login-removal-browser.mjs`; owned bridge fixes only, no vault reimplementation. |
| Human terminal | Explicit open, authenticated owner input, no agent-shell grant; stale controls rejected; expiry/abandonment cleanup; uncertain partial input never replayed; context off by default, bounded and scrubbed. | `tests/test_native_owner_terminal.py`, `tests/test_owner_terminal.py`, `tests/owner-terminal-browser.mjs`; this owned integration remains in scope. |
| Untrusted content and network | Private ingress assumption verified separately; browser egress/redirect/DNS rules and sandbox match policy; imported content and model output cannot grant tools or authority. | `tests/test_selkies_public_proxy.py`, `tests/test_selkies_sandbox.py`, `tests/test_browser_network_policy.py`, `tests/test_chat_attachments.py`; inspect actual enforcement, not only classifier output. |
| Upgrade/recovery | Source-pin mismatch aborts before mutation; hold admission during change; uncertain effects stay uncertain; preserve newer chats/vault; schema-compatible rollback or explicit repair-forward. | `tests/test_hermes_rollback_compat.py`, `tests/test_repeatable_release.py`, `tests/test_release_candidate.py`, existing native fixture/overlay qualification; qualify exact patches and restored state. |
| Swap readiness | Radhouse contract remains independent of engine branding; capability mismatch is denied; document state portability and non-portable state; unavailable engine produces honest recovery state. | Minimal contract/failure stub now; a real replacement must later pass the same suite and migration/recovery evidence. No claim of proven interchangeability today. |

Start with read-only review and existing tests. For an actual defect, add the
smallest behavioral regression, fix the enforcing boundary, and run affected
checks. Changes to a shared contract require consumer checks, including dynamic
imports, overlays and configuration-selected paths. Use full required gates at
review/scan closeout; do not repeatedly run unrelated suites without a new reason.

No deployment is authorized by this plan or the scan request. Any live change
uses the existing release workflow, explicit rollout authority and recovery
requirements. Record installed-state evidence privately and publish a sanitized
qualification summary, not operational endpoints or credentials.

## Building in public

Maintain [SECURITY.md](../../SECURITY.md) with honest support/exposure claims.
Verify a private reporting channel before inviting sensitive reports. At the
planning check, GitHub private vulnerability reporting was disabled and main
had no branch-protection rule. Enable/verify private reporting through the
maintainer's repository-settings decision; assess a small PR/review protection
policy compatible with the actual checks. Do not invent a pre-merge SonarQube
status check: this installation analyzes after merge. Settings changes are
tracked separately and are not implied by a scan.

Run `python scripts/public_privacy.py` before publishing. Review new documents
for private topology, real identifiers, chat exports/URLs and raw exploit detail.
The existing pattern/metadata check does not establish Git-history cleanliness;
investigate and rotate any actual exposed credential, rather than deleting only
its visible occurrence. Keep repository privacy controls distinct from runtime
access control. Public source is an acceptable development choice under this
limited scope, not a substitute for either control.

## S5: definition of done and later work

- Expanded analysis is complete and tied to the correct merged SHA; all open
  findings and hotspots are reconciled, with source and measurement gaps stated.
- All enabled trust boundaries have an owner, contract, negative-path evidence
  and known deployment assumptions. Confirmed high/critical reachable risks are
  fixed or the affected capability is disabled; no unknown material boundary
  risk is silently treated as accepted.
- All changed boundaries pass required regression and recovery checks. Existing
  SonarQube thresholds remain unchanged. Report a failed overall gate honestly;
  unrelated low-risk backlog may remain after this stage with explicit ownership.
- Every deferred class has an owner, reason and next review date or product
  trigger. Establish the date at S1 closeout; reassess at each relevant release
  and before onboarding or exposure/authority changes. Do not defer indefinitely
  using only the word "later" or an uncommitted future rewrite.
- A fresh scan confirms intended fixes. Reduction due to source retirement is
  recorded separately from correction; false-positive dispositions have evidence.
- Product work resumes with the highest-value next slice and the continuing
  debt allocation. Carry relevant fixes into new package boundaries.

Afterward: improve assertion clarity/test runners in coherent groups; reduce
complexity in touched code; add missing meaningful JavaScript execution coverage;
retire earlier platform code only after usage/compatibility evidence and a
separate decision; qualify new package boundaries when product outcomes justify
them. No blanket refactor to chase all 620 historical records.

## Same-session model handoff

Switching the current chat to GPT-6.1 is appropriate after the preparation and
expanded-baseline checkpoint is recorded and no tool operation is in flight.
Keep this chat; the checked-in plan and Git evidence provide the durable handoff.
The implementation model must read AGENTS.md, this plan and ADRs 0003/0004;
verify its actual worktree/HEAD/dirty state and remote main; inspect the latest
analysis SHA and receipt; and start at the first incomplete step.

Suggested continuation: "Implement S1 onward from the boundary stabilization
plan using the expanded scan. Work in bounded, reviewed commits, preserve the
current pilot and concurrent work, and use the authorized merge/rescan cycle.
Do not expand into upstream cleanup, package extraction or deployment. Report
each step's evidence and any decision that materially changes scope."

The owner authorized the scope-change merge and exact-main scan in this session.
Issue suppression, gate/profile changes, repository-settings changes and live
deployment remain separate. Completing this planning turn does not claim that
S1-S5 remediation is already done.
