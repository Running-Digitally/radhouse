# Durable requested outcomes

The redesign adds a durable outcome above an agent task, shared web/Buzz
commands and independent controller loops. This remains an additive, opt-in
artifact workflow. Software delivery, delegation, routines and fleet cutover
need their own qualification before replacing the existing project workflow.

Each artifact request has its own work ID, original brief, owner, accountable
agent, scope revision and pinned `artifact-v1` workflow. Its one
`deliver-artifact` step links to the existing task/attempt/dispatch records.
`work_items` and the queued task commit in the same transaction. The queued task
is the durable wakeup: a controller restart discovers it without an in-memory
queue or channel connection. No new queue service, model provider or credentials
are required.

A completed agent run does not complete work. `StepResultV1` in
`src/radhouse/domain/work.py` is the executable untrusted-output contract.
`artifact-present-v1` accepts a nonempty text artifact tied to the expected work,
step and scope. This verifies artifact delivery and integrity, **not** factual
accuracy, successful software release, or an external action. Those workflows
need their own evidence predicates in later slices. Missing/invalid JSON,
duplicate fields, wrong identities, unsupported versions, oversized output and
explicit blocked/incomplete outcomes cannot produce “Done.” Nullable fields are
required and validated explicitly.

Artifacts and verification receipts are retained separately from raw runtime
claims. Artifacts are inserted once, identified by an application-computed SHA-256
digest and producer attempt, and checked on retrieval. Status and artifact reads
check current ownership, project membership, bot grants and channel binding.
A project member cannot read another person's private result. Output is downloaded
as text and previewed through the existing sanitized Markdown renderer. A result
that failed acceptance stays in the visible current-work group, even though its
agent task has ended. Status reads do not start an agent or alter work.

The work card and attention list share `project_work`. Infrastructure and
incomplete-output blockers do not ask the operator for a meaningless decision.
A live permission request uses the same work ID in the card and attention list.
Pause, resume, cancellation, resource claims, exact-run recovery and dispatch
idempotency reuse the existing task path. Terminal output is verified in that
same short database transaction, with no network call under its lock.

## Enablement and API

The controller configuration accepts `durable_work_enabled: false` (default).
Enabling it exposes artifact creation in the web composer and permits new
`POST /v1/work` admission. It does not silently switch Buzz routing or migrate
old project snapshots. Turning it off prevents new admission while existing
work remains readable and execution remains recoverable.

- `POST /v1/work`: existing authenticated envelope and `start` shape, for text
  artifact work. The caller cannot choose a verifier or supply authority.
- `GET /v1/work/{work_id}`: authorized `WorkResponse`, using conversation and
  binding-revision query parameters.
- `POST /v1/work/{work_id}/commands`: guidance, pause, resume or cancel, with
  the existing authenticated envelope, `expected_state_revision` of the work,
  `scope_revision`, and `text` only for guidance. Returns the original command
  receipt, current authorized work and `application_state`.
- `GET /v1/work/{work_id}/artifacts/{artifact_id}`: authorized immutable text
  artifact with no-store/attachment headers.
- `GET /work-home`: retains legacy task cards, adds an optional `work` projection,
  attention work IDs, and the admission flag.

Commands retain existing principal-scoped keys and source-event conflict checks.
A lost reply is retried with the original envelope, producing the same work and
task. Different payloads under the same identity conflict. The result contract is
application-generated context, not a public request field or a grant.

Work controls extend the existing command/delivery ledger. Receipt, revision
fence and task intent commit together. Guidance uses the existing exact-run
control operation; a lost runtime reply remains `unknown`, without another POST.
Acceptance of guidance does not imply the model applied it. Application states
are `accepted`, `applied`, `not_applied` and `unknown`; confirmed dispositions
remain stable even when the current work state changes. Resume cannot reopen
terminal work. Current grants and binding checks apply to every replay too.

## Buzz ownership and independent progression

A conversation configured with `workflow_version: artifact-v1` freezes that
owner in its enrollment snapshot. Signed ingress resolves the original work
and freezes its revisions before issuing the same application command as web.
Known status questions read work without a model call. Explicit `pause`,
`resume` and `cancel` steer the resolved work; ambiguous targets ask for context.
Independent requests retain independent work IDs. Replies to terminal work
return its retained state. Explicit work references and contextual questions
use a read-only fallback; ambiguous references show bounded contextual choices.
A richer model interpreter remains unqualified. Notifications use the canonical verified work projection and never
publish raw result-protocol JSON as a completed artifact.

The default conversation mode remains `legacy`. A configuration edit does not
transfer an enrolled legacy channel: a mismatch is refused. A new owned
artifact enrollment and an explicit disposition of existing work are required
for cutover. Artifact mode cannot acquire automatic software-release policy.
See [Buzz integration](integrations/buzz.md) for the remaining client gates.

Use one active continuous controller process for this mode:

```sh
radhouse coordinator --config /etc/radhouse/base.yaml \
  --overlay /etc/radhouse/private.yaml
```

Execution, ingress and egress each have a bounded loop in that process. A stalled
relay cannot occupy the execution loop. Channel exceptions are isolated per
adapter; failures back off up to 60 seconds. Every 30 seconds the command emits
bounded loop health (cycles, errors, last completion/success and thread status).
SIGINT/SIGTERM stop all loops; an incomplete shutdown is an error. Adapter I/O
timeouts remain mandatory. Do not run multiple controllers or the old timer
alongside this process. `coordinator-once` refuses a Buzz-enabled durable-work
configuration or any configured artifact conversation, even with new admission
disabled, so retained work cannot silently return to serialized relay polling.

Signed artifact navigation now binds work, scope, manifest ID and digest to the
current enrolled owner. The URL fragment survives normal sign-in and opens the
exact sanitized artifact. It grants no authentication, approval or publication;
current web/channel binding and grant checks still apply. The original signed
notification remains immutable; a later status reply can issue a fresh link.
Changed scope/artifact/bytes invalidate navigation. General artifact sharing
and publication remain deferred until their audience/review workflow is qualified.
The existing raw-task review endpoint refuses managed work, so a blocked JSON
report cannot be published as a verified result through that path. Existing
legacy task sharing remains available.

## Schema and rollout

Migration `0008_work_items.sql` adds work, step links, artifacts and verification
receipts. `0009_work_commands.sql` links work receipts to the existing
principal-scoped command ledger. Neither changes historical task contents.
Migration `0010_runtime_observations.sql` constrains durable cursors on existing
dispatch snapshots; see the [runtime contract](runtime-contract.md).
Exact schema identity remains mandatory. This binary requires schema 10 even
with admission disabled. Upgrade tests cover versions 1 through 9 and preserve
tasks.

Deploying/migrating/enabling this path is a separate reviewed rollout. Do not run
an old schema-7/8/9 binary after migration, restore an old database under external
effects, or infer completed delivery from historical `completed` tasks. Disable
new admission, retain all new rows, hold dispatch if necessary, and repair forward
or use a verified compatible binary. Do not destructively down-migrate.

## Execution substrate selection

The selected executor is the existing Postgres-backed coordinator, with one
active controller process initially. It does not provide host-failure high
availability. Existing dispatch/effect identities, short transactions and
original-key reconciliation remain authoritative. Workflow versions are pinned;
an unknown version holds new execution visibly rather than replaying it under
incompatible code.

A disposable comparison of **DBOS 3.2.0 / Python 3.14.4** passed process crash and
restart, duplicate workflow identity, and cancellation. The lost-effect-response
exercise still needed a target-side idempotency key/lookup. DBOS was not rejected
for runtime incompatibility: its added checkpoint transactions and SQLAlchemy
integration did not simplify this first slice's existing atomic admission and
reconciliation. It was not qualified for all product upgrade or multi-executor
scenarios. Product dependencies remain unchanged. See
[DBOS's architecture](https://docs.dbos.dev/architecture) for its documented
recovery and idempotent-step requirements.

## Verification

Run the retained pinned-container gate when local Docker is available:

```sh
uv sync --frozen
npm ci --prefix web
node web/node_modules/@playwright/test/cli.js install chromium
npm test --prefix web
uv run python scripts/vs0.py verify
```

For a local native PostgreSQL installation, the optional fixture creates its own
random cluster, database, ownership marker and DML-only runtime role. It refuses
Postgres endpoint overrides and never connects to an existing server. It records
the actual version/binary digest, binds only loopback, and removes only its owned
cluster after a confirmed stop. No Docker daemon is started as a side effect.

```sh
RADHOUSE_VS0_NATIVE_BIN=/absolute/path/to/postgres/bin \
  .venv/bin/python scripts/vs0_native.py verify
```

Native Postgres evidence is not qualification of the pinned container image.
Lifecycle tests exercise atomic admission rollback, fresh-controller recovery,
lost start reply, incomplete/blocked/malformed output, scope/authority mismatch,
private/revoked artifact access, integrity failure, cancellation and unsupported
workflow versions. Shared-command tests also cover concurrent revision conflicts,
lost control replies, crash after stop intent and pause during capability I/O.
The signed Buzz harness proves duplicate admission, web/Buzz work correlation,
lost chat acknowledgement, frozen ownership, revoked queued delivery and actual
Postgres-backed completion during a relay stall. It does not qualify official
clients, live relay enrollment or duplicate local executors.

The real Chromium walkthrough creates two requests, safely opens an artifact
and confirms that blocked terminal-agent work remains visible and consistent
with the attention summary after reload. A second walkthrough pauses, resumes
and cancels an active assignment through the shared work API.

Next slices complete the conversation journey and artifact-bound review links,
then each runtime's versioned contract, maintenance/recovery, delegation,
verified delivery, saved routines, administration and fleet cutover. Source
tests do not repair or qualify legacy live delivery.
