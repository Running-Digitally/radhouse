# ADR-0004: Own the integration contract and qualify replaceable engines

Status: accepted owner direction; replacement qualification remains future work.

Date: 2026-10-15

## Context

Hermes and Selkies are selected dependencies for the current private pilot.
Future product learning, support or security problems may justify another agent
or browser engine. Avoiding a permanent fork is desirable, but importing a
package does not transfer responsibility for how Radhouse grants it access.
The runtime folder contains substantial Radhouse-authored behavior and patches.

## Decision

Retain Hermes and Selkies for the qualified pilot. Make their boundaries explicit
and testable before considering replacements. Names such as OpenClaw or
NemoClaw are possible future candidates, not selected or qualified alternatives.
This decision neither reopens the viewer choice in ADR-0002 nor introduces a
second harness, memory store, terminal implementation or credential vault.

Radhouse owns admission and identity checks; the permissions and state it grants
to engines; adapter behavior; its source transformations and patch deltas;
version and capability negotiation; redaction; update qualification; and recovery.
Upstream maintainers own their general implementation and release processes.
Radhouse still owns the decision to use a particular version on an enabled path.

Recovery includes the adapter's interruption and callback contracts. Cleanup must
retain ownership of uncertain effects; process termination and executor
cancellation must not silently become an ordinary retryable launch failure.
Qualification may defer interruption until owned child cleanup finishes, but
must then report an unsuccessful observation. Preserve concrete state types and
awaitable callback interfaces when addressing analyzer feedback. A warning is
not permission to weaken those contracts; record evidence for contextual review.

Inventory the active native chat/runtime contract separately from the earlier
platform's opt-in descriptor in `docs/runtime-contract.md`. Reuse existing typed
contracts and tests. Do not imply that a descriptor from the earlier lane already
qualifies the native chat pilot. Expose only capabilities positively supported
by the configured, qualified adapter. Missing or incompatible capabilities fail
closed; they never enable broader tools or silent fallback.

The minimum replacement contract covers:

| Boundary | Required property |
| --- | --- |
| Identity and authority | Owner, conversation, run, browser generation and lease are checked at the enforcing boundary; model text cannot create permission. |
| Work admission | Durable request identity, explicit status and cancellation; an uncertain acknowledgement never causes blind replay of effects. |
| Browser ownership | Private takeover by default, separate observation consent, revocation/drain and fresh handback; viewing does not confer input. |
| Credentials | Exact-origin use, minimal exposure, no secret-bearing output or transcript; Radhouse does not invent a second vault. |
| Terminal | Explicit human-only opening and input; context sharing is opt-in and scrubbed; no implicit agent shell authority. |
| State and recovery | Declared ownership of transcript, runtime memory, browser profile, vault and terminal state; preserve or explicitly retire each state type. |
| Compatibility | Pinned source/images and capabilities, evidence of patch application, explicit migration/rollback limits, and fail-closed mismatch handling. |

A contract stub can exercise denied capabilities and failure modes now. It does
not prove that a second real engine is interchangeable. A future replacement
must pass the same behavioral checks on the actual candidate and demonstrate
state export/migration or an explicitly accepted continuity limitation. Engine
replacement is a controlled operation with admission held, in-flight effects
reconciled, credentials scoped, and recovery proven; never a live hot-swap by
changing a package name.

For a material upstream vulnerability: establish whether the deployed version
and enabled path are affected, prefer a qualified upstream fix, otherwise
disable or constrain the affected capability, or qualify a replacement. A
narrow emergency patch is possible with an owner, tests, expiry/review trigger
and an upstream/removal path. This does not authorize a general upstream cleanup
programme or an indefinite fork. If containment cannot be demonstrated, do not
continue exposing the affected capability while waiting for a replacement.

## Consequences and alternatives

This keeps improvements useful if product packaging changes. The first work is
an ownership map, minimal contracts and negative-path tests, not eight package
extractions or a new abstraction over every API. A small amount of duplication
can be preferable to a premature general framework; duplicated authority rules
cannot silently diverge.

Ignoring everything under `runtime/` would hide owned risk. Maintaining all
upstream code would overwhelm the product. Responsibility follows the behavior
Radhouse adds, the authority it grants, and the versions it chooses to run.

Execution: [ownership map](../runtime-ownership.md) and
[bounded plan](../plans/2026-10-15-boundary-stabilization.md).
