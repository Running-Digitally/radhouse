# Durable requested outcomes

The first redesign slice adds an outcome above an agent task. It is an additive,
opt-in foundation; it does not qualify the complete redesign or replace the
existing Buzz/project delivery workflow yet.

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
- `GET /v1/work/{work_id}/artifacts/{artifact_id}`: authorized immutable text
  artifact with no-store/attachment headers.
- `GET /work-home`: retains legacy task cards, adds an optional `work` projection,
  attention work IDs, and the admission flag.

Commands retain existing principal-scoped keys and source-event conflict checks.
A lost reply is retried with the original envelope, producing the same work and
task. Different payloads under the same identity conflict. The result contract is
application-generated context, not a public request field or a grant.

Sharing these artifacts is deferred until review binds to the artifact itself.
The existing raw-task review endpoint refuses managed work, so a blocked JSON
report cannot be published as a verified result through that path. Existing
legacy task sharing remains available.

## Schema and rollout

Migration `0008_work_items.sql` adds work, step links, artifacts and verification
receipts; it changes no historical task contents. Exact schema identity remains
mandatory. The new binary requires schema 8 even with admission disabled.
Legacy-schema upgrade tests cover versions 1 through 7 and preserve tasks.

Deploying/migrating/enabling this path is a separate reviewed rollout. Do not run
an old schema-7 binary after migration, restore an old database under external
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
workflow versions. The real Chromium walkthrough creates two requests, safely
opens an artifact and confirms that blocked terminal-agent work remains visible
and consistent with the attention summary after reload.

Next slices are unified web/Buzz command ownership, each runtime's versioned
contract, maintenance/recovery, delegation, verified delivery, saved routines,
administration and fleet cutover. This foundation alone does not repair or
qualify legacy live delivery.
