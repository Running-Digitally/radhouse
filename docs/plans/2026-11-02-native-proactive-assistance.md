# Native proactive assistance qualification

Status: implementation and isolated qualification in progress. No production
activation is established by this document.

The [research](../research/2026-11-02-hermes-proactive-assistance.md) grounds this
slice in the pinned Hermes source, human-AI interaction research and community
experience. It implements the accepted [proactive assistance direction](../proactive-assistance.md).

## Ownership and scope

Hermes owns recurring schedules, heartbeat state and agent execution. Radhouse
owns a versioned standing responsibility, authorized source selection,
confirmation and attention state, and delivery to the authenticated owner.
Neither a prompt nor a scheduler job is an access-control grant.

The first personal responsibility is to suggest possible commitments from recent
conversation for confirmation. No suggestion becomes an accepted commitment on
its own. Reading attachments, Library, browser state, other conversations or
contacting third parties is outside this initial scope.

## Qualification sequence

1. Execute bounded tests against the exact native source: persistence, restart,
   missed-tick behavior, pause/resume, silent completion and API/tool boundaries.
   Use synthetic state and no model/provider or personal data.
2. Implement the narrow responsibility and attention contract with source
   citations, correction/dismissal, duplicate suppression and explicit authority.
3. Integrate a native schedule through a scope-checked adapter. Verify saved
   settings before activation; reconcile uncertain creation instead of blindly
   creating another job. Use no duplicate application scheduler.
4. Deliver durable proactive items through the existing authenticated product
   and push outbox. A proactive item is not a fabricated user turn. Recheck
   authority before publication and delivery; keep lock-screen text generic.
5. Qualify the whole path, including browser closed, process restart, source
   revocation, pause, quiet hours, unchanged input, runtime failure and delivery
   failure. Record the actual production result separately from source tests.

## Native constraints to resolve

- The pinned Jobs HTTP create handler ignores toolset and script/no-agent fields.
  An accepted HTTP response is insufficient evidence of restricted execution.
- Cron can load shared memory and merge MCP toolsets. A fresh session alone is
  insufficient source isolation for the bounded conversation pilot.
- Native HTTP `send()` cannot deliver into Radhouse. The existing push transport
  observes human-initiated reply completion and needs an explicit proactive
  event contract; passing a new kind requires mobile compatibility evidence.
- Heartbeat state persistence can fail without throwing. Read-back and execution
  receipts are necessary before reporting an active responsibility.
- Existing per-run Radhouse document/browser grants are tied to admitted Runs
  API identities. They must not be copied onto unrelated scheduled agents.

These are integration constraints, not reasons to build another scheduler or
expose unrestricted native cron tools to the assistant.

## Acceptance and release evidence

The owner can see scope, cadence, current coverage and the last meaningful
result, pause the responsibility and confirm or reject a cited suggestion.
Unchanged or non-actionable checks stay quiet. A failed check is never reported
as “nothing to do.” Corrected, dismissed or expired suggestions do not re-alert
without new evidence. Restart cannot duplicate the same published event.

Keep notification availability distinct from responsibility execution: an
expired signed-in device may stop delivery without granting another session.
No notification extends authentication or adds a recipient.

This is an early part of DW-6's standing-work direction. It does not require
helper fleets, cross-host placement or broader source access. The public
[roadmap](../../ROADMAP.md) remains the single engineering backlog.
