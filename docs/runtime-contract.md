# Runtime contract and compatibility

One configured bot owns one authenticated runtime origin and persistent
workspace. Bot identity, profile, provider binding and runtime revision remain
deployment pins. They cannot be selected by a task or changed by output.

## Opt-in descriptor

`bots[].descriptor_contract: radhouse-runtime-v1` requires authenticated
`GET /v1/radhouse/descriptor`. Default `legacy` retains the current Hermes Runs
API, whose version is a configuration pin rather than verified remote identity.
An absent or incompatible opt-in endpoint never falls back silently. The
executable descriptor is `domain/fleet.py:RuntimeDescriptor`:

```json
{"contract":"radhouse-runtime-v1","bot_id":"researcher-001","profile":"researcher","runtime_revision":"qualified-runtime-pin","provider_binding":"local-chat","result_protocol":"work-result-v1","observations":"durable-sequence-v1","durable_runs":true,"durable_workspace":true,"admission":"ready","hold_reason":null,"max_parallel_runs":1,"observed_at":1790830800,"guidance_receipts":false}
```

The timestamp above is synthetic. Reports older than 60 seconds or more than
5 seconds ahead are refused. Identity/profile, runtime version and provider must
match configuration. The producer must prove durable start-key lookup and a
retained workspace; advertising these fields alone does not qualify a VM.
Descriptor and capability reports must agree about guidance receipts. Unknown
fields/versions, duplicate JSON fields, invalid types and integer substitutes
for boolean claims are rejected.

Admission is `ready`, `held` or `unavailable`. Only ready has a null hold reason;
other states name maintenance, manual stop, storage pressure, model unavailable
or runtime upgrade. Held runtimes remain observable and can accept exact-run
stop. Readiness does not start a stopped VM, clear a maintenance hold or grant
infrastructure authority. Reported capacity cannot expand controller concurrency.

## Durable observations

Runs retain existing authenticated POST/GET/start-or-attach, guidance and stop
operations. Opted-in run GET also provides a positive `observation_sequence`
integer up to 2^63-1. Persist and increment it for every change to status, output,
permission, guidance evidence or activity. Polling cannot manufacture progress
or refresh the timestamp of unchanged activity.

The controller retains sequence and a content digest on its existing dispatch
snapshot before consuming output. Older snapshots are ignored; changed content
under the same sequence stays unresolved. Identical replay can finish application
after a crash between cursor persistence and result promotion. Once a dispatch
has a durable cursor, missing sequence cannot downgrade it to legacy handling.
Current-attempt fencing remains mandatory. Coarse state labels remain available
when optional fine activity is absent. No second queue/observation service exists.

## Compatibility and qualification

| Controller path | Runtime requirement | Result | Evidence and enablement |
| --- | --- | --- | --- |
| `legacy` | Retained pinned Hermes Runs API and installed profile; existing idempotency/guidance features | Historical task result, or explicitly admitted artifact work | Compatibility retained; remote descriptor identity is not proven |
| `radhouse-runtime-v1` | Descriptor above, durable run sequence, original start-key lookup and persistent workspace | Existing `work-result-v1` / `artifact-present-v1` | Synthetic persistent HTTP runtime and isolated controller tests; each actual guest remains unqualified |

Current source requires schema 10 and additive migration
`0010_runtime_observations.sql`. Upgrades preserve schema 1–9 task history.
Descriptor mode remains opt-in. Do not enable it on an unpatched guest. Prepare
the exact producer/profile/controller manifest; prove identity, held observation,
lost-response recovery, exact stop and retained files in the approved deployment
window. This repository does not claim an installed guest implements the new
endpoint. No guest service/unit changes are performed here.

Schema-9-or-earlier binaries cannot read the new cursor snapshots as an
operational rollback. Retain rows, hold new admission and repair forward or use
a tested schema-10-compatible reader/recovery binary. Changing source mode cannot
downgrade the interpretation of an active durable observation.
