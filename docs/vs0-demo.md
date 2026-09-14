# First controller proof: VS0-A

VS0-A began as one durable synthetic task through two simulated operator
channels. The current harness also exercises VS1-B Increment A: a controller can
die after a fake agent run is admitted, and a fresh process reattaches through the
same durable dispatch key and runtime run ID. The operator can review and publish
the exact result through the other channel.

This is the first controller implementation. The channel labels are `radhouse`
and `buzz`, but both use in-process FastAPI test clients. There is no browser UI,
Buzz connection, Hermes process, model call, or deployed fleet in this proof.

## Run it

Prerequisites:

- Python 3.14 and uv on your development machine.
- A running Docker daemon selected by a local Unix-socket Docker context.
  Remote Docker contexts are refused. The runner does not start a daemon for you.
- At least 2 GiB free disk space in the checkout filesystem, plus sufficient
  Docker storage for the pinned PostgreSQL image. The first run downloads it.
- No Docker endpoint/context/TLS/API or PostgreSQL connection overrides in the
  environment. The runner reports the refused setting category without printing
  its value. An existing application database is never a test target.

From the repository root:

```sh
uv sync --locked
uv run python scripts/vs0.py verify
```

`verify` creates a fresh PostgreSQL fixture, runs both channel demonstrations,
runs the full suite once, and cleans up. It fails if a test fails or is skipped.
For just the two demonstrations and the unknown-receipt case:

```sh
uv run python scripts/vs0.py demo
```

Each command creates its own fixture. Plain `uv run pytest` is useful for quick
checks, but database-dependent tests skip without that owned fixture; it cannot
substitute for a successful `verify` run.

The terminal trace shows admission, recovery, and reviewed publication with
task, attempt, and run identities. The two successful tasks each create one fake
agent run. A third task deliberately produces no authoritative runtime result;
repeated recovery leaves it waiting for attention without creating another run.

## What is implemented

| Boundary | Behavior demonstrated |
| --- | --- |
| Durable work | PostgreSQL retains task identity, revisions, attempt ownership, budget reservations, resource claims, exact agent dispatches, mediated operations, review decisions, and channel deliveries. |
| Two operator surfaces | Both normalized channel paths invoke the same application service. Repeated deliveries and reused command keys cannot create a second task or authorize a different publication. |
| Current permission | Every operator request rechecks the actor, bot/project grants, and current conversation binding. The app factory requires an injected authentication adapter; request fields cannot assert identity, role, or MFA assurance. |
| Privacy | Task contents and history remain owner-only. An eligible named publication audience can read the released result, without access to private task history. Revoked access applies to subsequent reads and repeated decisions. |
| Protected decisions | Reviews bind content digest, audience, reviewer, task/state revisions, expiry, and synthetic fresh assurance. Changed or stale decisions fail; publication and delivery commit together. |
| Recovery | Fake runtime runs live in a separate SQLite target outside the controller transaction. The demonstration kills a child controller after admission commits, then reattaches through another child process. Missing or expired runtime evidence never permits a new run. |
| Provider changes | A task retains its selected provider binding while the fake provider changes its backing model. Capability failures block work without provider fallback or a fresh budget. |
| Bounded overlap | Independent assignments on one bot can hold active attempts. Conflicting resource use waits, and concurrent workers cannot claim the same task attempt. |
| Human control | Cancellation and independent pause/grant holds persist through provider recovery. Stale observations cannot resurrect closed work or assert a trusted external result. |

A paused, prepared attempt retains its owner, resource claim, dispatch key, and
spent budget reservation. Resume continues that same attempt; it neither spends
another attempt budget nor silently reassigns an unresolved dispatch. The claim
blocks conflicting work while paused; cancellation releases it once stopping
and the external outcome are resolved. This is a bounded prototype behavior to
qualify against the real runtime before building the operator experience.

## Fixture limits and cleanup

The entrypoint pins PostgreSQL 18.6 Bookworm to this official registry index:

```text
sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af
```

One run owns one container and one volume, each named and labeled with a random
run identifier. It verifies a fresh volume's ownership before mounting it. The
container uses one CPU, 512 MiB RAM, no extra swap allocation, a 128-process cap,
and a dynamically allocated port bound to `127.0.0.1`. It has no privileged mode,
host network, host bind mount, or Docker socket mount. The execution deadline is
15 minutes, with a separate bounded cleanup allowance of up to 45 seconds.

The bootstrap creates a fresh fixture-only schema. The controller connects as a
separate DML role that cannot create schema objects, temporary tables, or change
the ownership marker. The adapter refuses remote connection targets and checks
the database's exact fixture identity on each connection. This is intentionally
not a production migration or restore interface.

Cleanup checks exact ownership before removing the run's container and volume,
and removes its fake-target SQLite files. It retains the image cache and
sanitized evidence under `.vs0/<run-id>/`. A daemon failure or ownership mismatch
leaves a reported residual for inspection rather than deleting an unrelated
resource. Read the manifest before any manual cleanup; do not use a broad prune.

`deploy/dev/compose.vs0.yaml` documents the corresponding container profile.
Use the Python entrypoint for the proof: a bare Compose start does not perform
the runner's ownership, schema, authority, deadline, or cleanup checks.

## Original VS0 verification record

The final 2026-09-12 local arm64 run used Python 3.14.4 and the committed
dependency pins:

- **111 tests passed; zero failures, errors, or skips.**
- Both channel directions recovered in a fresh controller process, confirmed
  one effect per completed task, and published one reviewed result.
- The unknown-receipt case stayed blocked without another execution.

VS1-B adds Hermes wire-contract, durable dispatch, retention-expiry,
lost-admission-reply, exact cancellation, sibling isolation, and grant-withdrawal
coverage to this suite. Run the canonical command above for current release
evidence rather than treating the historical VS0 count as the current total.
- Cleanup completed with no retained fixture container or volume.

The retained local manifest identifies the pre-commit source baseline separately
from the implementation file hash. Its verification identities are:

```text
run_id: f6b005b7d0b245a09d2f8290924e2b3d
source_sha256: 8bec7d86921fecc20867ca57f6a2c0f70309305a6528419dfd6c1bdec8c454fe
dependency_lock_sha256: 722e0a96bb9b239cfe2b1e904239214a7f0e375eabee3ed93e2a04dd40727de0
```

Every run records its own source commit, source/dependency hashes, interpreter,
image, results, and cleanup outcome in `.vs0/<run-id>/manifest.json`. Generated
manifests and raw execution artifacts are ignored by Git. Source hashing covers
`src`, `tests`, `scripts`, and `deploy/dev`; subsequent documentation edits do not
change those verified implementation bytes.

The pinned test stack emits upstream deprecation warnings for Starlette's
HTTPX 0.28 test client and anyio's `BlockingPortal` alias. They do not fail the
proof. Update the pins through a reviewed compatibility change; do not install
a prerelease client just to hide a warning.

## What remains to qualify

The database adapter serializes short fixture transactions with a per-run
advisory lock. The race tests use real separate connections and verify
invariants, but do not establish fleet throughput or a production scheduler.
Synthetic authentication cannot prove local accounts, SSO, MFA, signed chat,
session revocation, or the security of a real deployment. Fake runtime stopping
and authoritative receipt lookup must be established separately for actual
Hermes and service adapters.

The next steps are [VS1-A service qualification and VS1-B's useful task through
both real interfaces](architecture-review.md#prepared-infrastructure-and-the-path-into-the-live-pilot).
They add the thin TypeScript work home and native Buzz review path against
qualified services. Installation-specific addresses, credentials, and evidence
belong in a private deployment overlay; this repository keeps reusable contracts
and synthetic examples.
