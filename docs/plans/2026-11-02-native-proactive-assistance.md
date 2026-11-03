# Native proactive assistance qualification

Status: merged and deployed for a private pilot. Native recurring execution,
real-source review and provider acceptance are verified. On 3 November 2026 the
owner also confirmed notification receipt and successful suggestion opening on
both iOS and Android after backgrounding or locking both phones. This does not
qualify timed reminders or every wider always-on capability.

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

## Implemented pilot contract

The source candidate adds **Responsibilities → Commitment suggestions** on web
and mobile. The owner enables recent-conversation review and confirms or dismisses
cited suggestions. Confirmation saves a commitment; automatic follow-up on that
commitment is not implemented. This recurring discovery responsibility is an
initial slice of the always-on design, not completion of the Guardian Angel and
Cognitive Amplifier roadmap. Bot mail remains an optional later source.

Hermes checks once per hour using one native script job. The application performs
cheap unchanged-input and in-flight checks before inference. Model reviews are
limited to four in a rolling 24 hours, with at most three suggestions per review.
These are conservative pilot defaults, not research-established optimal rates.
The source window is at most 30 exchanges over seven days, bounded to 24 KB of
text (4,000 user characters and 2,000 reply characters per exchange). Attachments,
Library, browser, other owners and shared Hermes memory/SOUL files are excluded.
A source message can yield at most one saved suggestion in this pilot; multiple
commitments in one message need a later evidence-identity refinement.

The explicit standing grant survives browser closure and sign-out. Current
account activity and conversation binding are checked without renewing a session.
Pause, binding changes, expiration and newer conversation evidence prevent stale
publication. An invalid model result is a failed review; an empty valid result is
quiet success. Review snapshots are erased at completion, pause or interruption;
review receipts age out after seven days when new work is admitted. Suggestions
remain until a future owner-controlled retention policy is implemented.

Review execution uses native `AIAgent` with no tools, memory, context files or
fallback model. A subprocess bounds a stalled call. The installed base runtime's
three scope-enforcement files must match their reviewed manifest. The worker uses
the operator-selected native provider and currently qualifies only the
`chat_completions` transport. Unsupported transports fail closed. It cannot
choose new sources, enable its own grant or authorize an external action.

Suggestions are durable before delivery. Existing authenticated push delivery
reconciles them; there is no second application scheduler. Each device explicitly
opts in to agent suggestions separately from reply notifications. Old clients
continue to receive only version 1 reply events. Version 2 uses exactly
`version`, `kind=commitment_ready`, `event_id`, and `item_id`; both IDs are UUIDs.
The lock-screen text is generic. Opening a notification requires a current
authenticated item read. At most two new suggestion events are admitted in a
rolling day, with a 24-hour expiry and quiet hours from 22:00 to 08:00 in the
explicitly configured timezone. Other suggestions remain in Responsibilities.
Any new conversation after publication conservatively suppresses the queued
notice, because it might contain a correction; the saved suggestion remains
reviewable. Pause, decision, revoked binding and device opt-out also suppress
pending delivery. Already provider-accepted notifications cannot be recalled.

Coverage is shown separately from permission and delivery. An enabled grant is
not a claim that the scheduler or provider is healthy. The UI shows failures,
interrupted runs, budget waits and missing recent coverage. Real model usefulness
and device delivery require live qualification beyond the synthetic checks.

## Configuration and recovery

The web service reads `RADHOUSE_COMMITMENT_REVIEW_CONFIG`, a private service-owned
regular JSON file with exactly `store_path`, `worker_bearer`, and `timezone`.
Use an absolute private SQLite path, a distinct random URL-safe bearer of at
least 43 characters, and an IANA timezone. An absent configuration exposes the
page's unavailable state but no worker endpoints or source grant. Enabling
configuration does not enable the responsibility; that is a separate authenticated
owner action. The worker bearer only permits claim/completion; it cannot change
the grant or choose an owner.

The native worker reads `RADHOUSE_COMMITMENT_WORKER_CONFIG`, also private and
service-owned, with exactly `endpoint`, `worker_bearer`, `model`, `provider`,
`ca_file`, `tls_server_name`, and `hermes_root`. The callback origin must be HTTPS
loopback through the established private forwarding path. TLS verifies the
configured certificate authority and server identity; ambient proxies and
redirects are disabled. Provider configuration stays in the existing native
profile. No credential values belong in source or public documentation.

Run the checked-in `runtime/hermes/commitment_worker.py provision` with the native
interpreter, profile and worker configuration. Provisioning copies the frozen
worker and base manifest under `HERMES_HOME/scripts/radhouse-review/<revision>/`:
the pinned native runner refuses scripts outside that directory tree. It creates
one paused native job, verifies effective schedule/script/interpreter/toolset/
delivery fields and reuses that identity on repeat. Unexpected configuration
pauses the owned job and requires reconciliation; duplicate jobs are not silently
accepted. `activate` resumes only the verified job. A production change must
preserve the singleton native scheduler, existing maintenance policy and admission
hold. A script job invokes the bounded worker, not an unrestricted cron agent.

The push database migrates transactionally from schema 1 to schema 2, preserving
existing device and reply rows and leaving suggestion consent off. Before rollout,
stop dispatch briefly and retain a verified SQLite backup of this separate store.
The old sender deliberately refuses schema 2: **rolling back source alone is not
sufficient**. Prefer pausing the native job and disabling the new responsibility
while retaining the compatible sender. If the older sender is required, restore
only the verified pre-migration push store while stopped; re-register devices and
account for notification replay/consent changes since the backup. Never restore
chat/auth databases as part of this rollback. Keep the new private commitment
store for recovery. No schema downgrade or production restore is automated here.

## Qualification and remaining release gates

The isolated qualification runs actual pinned heartbeat, cron storage, claim and
script execution, including restart, pause, missed ticks, silent results, script
scope and callback-locator environment behavior. `scripts/qualify_commitment_agent.py`
clones the exact native source into disposable storage, applies the reviewed base
overlay, and invokes the real `AIAgent` against a loopback synthetic provider.
Non-loopback sockets are denied in that test. The resulting request exposed zero
tools and none of the canaries planted in SOUL, AGENTS and memory files. This proves
runtime wiring and source isolation for that fixture, not semantic judgment by a
production model.

The web test `tests/responsibilities-browser.mjs` checks desktop/phone layout,
source evidence, confirmation, pause, CSRF and rendering untrusted output as text.
Backend tests exercise bounded source selection, revocation, newer evidence,
idempotency, failure visibility, budget, quiet hours, delivery consent and API
separation. Mobile tests cover versioned payloads, authenticated navigation,
sign-out races, explicit opt-in and confirmation controls.

The original release gate required a frozen integrated web/native/mobile candidate; current
service identity and idle checks; the separate privileged service-change gate;
verified backup and rollback; actual selected-provider semantic qualification;
and foreground/background/cold-start notification acceptance on the owner's
phones. Existing reply-push evidence does not establish proactive-push delivery.
Those isolated tests alone did not authorize the standing grant or establish production coverage.

A fresh 3 November [touched-file Sonar read](../research/2026-11-03-proactive-touched-findings.json)
returned eight existing findings. The candidate addresses six: consistent resource
collections, redundant exception handling, observer complexity, semantic status
outputs and a checkbox's initial accessible label. Two are retained for explicit
contextual review: `a4f7fee7-7b32-45b8-93c4-9f485267b396` preserves keyboard access
to the scrollable conversation; `eb78fb9e-c41e-462e-b51a-8612354c9cd3` retains the
parentheses needed to call `total_seconds()` on a datetime difference. No issue
status, rule or gate changed. A current mobile project read returned zero open
issues. New source and closure require the normal authorized post-merge scan;
this branch has not been scanned as main.

Validation completed on 3 November: 2,376 backend tests passed with no failures,
errors or skips using an owned PostgreSQL 17.11 fixture; cleanup completed with no
residual resources. This is native PostgreSQL evidence, not the pinned Docker
qualification. The existing web build and 14 Node tests passed. Desktop/mobile
Chromium responsibility checks passed and rendered screenshots were inspected.
The actual pinned-agent qualification made one synthetic provider request with
zero tools and no unscoped context canaries. After the small touched-file cleanup, 100 focused backend tests and all three
Chromium journeys passed. Mobile quality passed 135 Jest
behavior tests, 15 tooling tests, typecheck, lint and coverage; both iOS and
Android production JavaScript bundles built. Signed application builds and live
model/device acceptance remain separate gates.


## Private pilot rollout — 3 November 2026

The implementation was rebased after the preceding OpenAI/chat release, merged,
and deployed under explicit owner authority. The native hourly script job was
created paused and its effective schedule, tool exclusion, script, interpreter
and local delivery fields were read back before activation. The selected local
provider passed a synthetic semantic check. A real native-ticker review then
produced two strictly cited suggestions; the transient source snapshot was erased.
The separate push store migrated with a verified backup and preserved explicit
mobile consent. The provider accepted one resulting suggestion for both platforms.
On 3 November the owner confirmed receipt on both backgrounded/locked phones
and that both notification taps opened the intended suggestion. Together with
the native review and durable provider receipts, this completes the pilot's
end-to-end push acceptance. Force-quit cold-start behavior was not separately
tested, and tapping did not grant permission to act on a suggested commitment.

Live qualification found and corrected two integration defects: a single Markdown
JSON fence was rejected despite otherwise structured output, and ordinary chat
lacked application capability facts. The parser now accepts only that outer
envelope while preserving all schema, size and exact-citation checks. New chat
requests receive current source permission and latest review outcome without
copying suggestions or granting tools; retry inputs remain immutable. A live chat
check accurately distinguished background assistance from unsupported timed
reminders. The cooperative local-model budget is 180 seconds within the unchanged
240-second process deadline, two iterations and 2,500-token per-call limit.

Signed iOS 1.0 (8) and Android 1.0 (6) were published to the existing owner-only
test channels. No audience, model provider, source permission or recurring quiet
hours were expanded. One owner-requested immediate delivery check bypassed only
quiet hours for its exact fresh item; normal authority, source freshness, expiry,
device consent and outbox deduplication still applied.

The merged web correction passed 2,385 tests with zero failures, errors or skips
using the owned Docker/PostgreSQL fixture; cleanup completed. Mobile merged-main
quality and SonarQube gates passed. The bounded backend findings closed; its
overall gate remains affected by pre-existing coverage and issue backlog. No
findings were suppressed and no gate was changed. Three existing service
complexity findings remain explicit follow-up work in PR121.

This pilot proposes commitments and prepares text. It does not create a timed
reminder, schedule a follow-up when confirmed, or automatically perform the
proposed step. Suggestion wording remains subject to human review, including
stale historical claims about platform status; current coverage is displayed
separately. Initial qualification consumed the four-review rolling daily budget.
Unchanged-input checks continue without inference; new-source inference waits
for that budget to renew. This is a visible pilot limitation, not continuous
coverage of every new message.
