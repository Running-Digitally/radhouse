# Hermes continuity: implementation gap check

Reviewed: 2026-10-25. Radhouse source baseline:
`2ed8aa89cb03e922e687a99ace1d946a36029698`.
Scope: current chat application, native integration, browser lifecycle and
relevant existing tests. This is source/documentation evidence, not a live host
inventory, an executed restore or a new deployment qualification.

## Finding

Hermes already implements persistent sessions, native memory and backup/import.
Radhouse already uses native session loading and durable keyed Runs admission.
The next work is controlled replacement of the runtime using retained state,
plus recovery packaging for the stores that belong to Radhouse. Do not introduce
another memory format, session engine or per-turn database checkpoint mechanism.

The [architecture](../design/durable-assistant-workspaces.md) and
[DW roadmap](../plans/2026-10-21-durable-workspace-roadmap.md) own the target and
delivery sequence. This assessment supplies evidence; it is not a second backlog.

## Exact upstream and integration scope

[source-lock.json](../../runtime/hermes/source-lock.json) names Hermes **v0.21.6**,
commit `818c13be1dc4fd28987e1e881a9408224afd4535`.
[base_overlay.py](../../runtime/hermes/base_overlay.py) applies the pinned base
contracts; [overlay.py](../../runtime/hermes/overlay.py) and the native bridge
compose the Radhouse-specific behavior. Upstream capability is not a reason to
discard those restrictions or move to unpinned `main`.

The relevant upstream contracts at that revision are:

- [Runs API][up-api]: an existing `session_id` loads the active transcript when
  the caller does not supply replacement history. Keyed retries retain their
  original admission identity within the documented retention period. An active
  run terminated by shutdown can become `interrupted`.
- [Memory][up-memory]: native notes live under the profile home. Independent
  agents should have separate profiles, rather than share writable memory files.
- [Migration][up-backup]: full backup/import moves native data; profile export
  is a different, credential-stripped operation. Neither is a runtime image.
- [Backup implementation][up-backup-code]: browser profiles and disposable
  runtime material are excluded; a full archive can contain credentials and
  report skipped files.
- [SQLite copy implementation][up-sqlite]: uses SQLite's backup API and refuses
  a failed snapshot. This does not establish a transaction across all of
  Radhouse's stores or all files in a live home.

[Upstream community tracking][up-community] also reports restart/reconnect and
idempotent-admission checks. Its listed revisions differ from the pin above;
these reports inform expectations and regression selection, not certification
of this integration. CLI or messaging-gateway auto-resume behavior must not be
substituted for the HTTP Runs contract used by Radhouse.

## Existing code and remaining gaps

| Area | Source evidence | Consequence |
| --- | --- | --- |
| Durable chat and identity | [ChatStore](../../src/radhouse/chat/store.py): `conversations`, `turns`, `reserve`, `session_id`, `attach`, `observe` persist the owner/session mapping, request/dispatch/run IDs, output/status and retry timing. | Reuse these records. A new run/session identity system is not the next build. |
| Native context loading | [ChatService._send](../../src/radhouse/chat/service.py) sends the stored session ID through [HermesRunsClient.start_or_attach](../../src/radhouse/integrations/hermes.py). The [pinned API fixture](../../runtime/hermes/fixtures/api_server_runs.snapshot) resolves the active native session and loads its transcript. | Keep Hermes as context owner. Displayed chat is not the native recovery format. |
| Retry after lost acknowledgement | ChatService freezes inputs/options, reuses the dispatch key and checks the retry deadline. HermesRunsClient sends `Idempotency-Key` and verifies the advertised durable capability. | Reuse the existing protocol and expiry refusal. A missing or expired receipt cannot authorize a new effect. |
| Follow-ups and reconnect | [ChatService.poll](../../src/radhouse/chat/service.py) observes the recorded run and advances only eligible never-attempted queued messages; [app._reply_lifespan](../../src/radhouse/chat/app.py) runs the observer without an open browser. | Add a replacement hold to this path as well as Send. Merely stopping HTTP submissions would leave an active dispatcher. |
| Interrupted work | `TERMINAL` in ChatStore includes `interrupted`; `poll` saves that outcome and does not automatically restart that run. Later queued work can advance after terminal status. | Preserve honest interruption. Review queued work before releasing a replacement hold. General automatic effect continuation is not implemented by session resume. |
| Library and tool access | ChatStore retains uploads in an adjacent `.files` directory and grants in SQLite. [DocumentBridge](../../src/radhouse/chat/document_bridge.py) checks saved grants and native run status; [bridge.py](../../runtime/hermes/bridge.py) binds callbacks to the trusted run context. | Keep file IDs, original bytes and callback identity stable. Preserve these stores separately from native backup; do not mount the whole Library into a worker. |
| Memory and logins | [about_you.py](../../runtime/hermes/about_you.py) reads native notes without creating a second memory store. [VaultBridge](../../runtime/hermes/vault_bridge.py) uses the native vault under the selected Hermes home. | Retain native formats and key custody. A home/archive can contain account authority; it is not a helper's input bundle. |
| Runtime lifecycle | [app_factory](../../src/radhouse/chat/main.py) configures a fixed Hermes endpoint. Native bootstrap/overlays prepare source; they are not a retained-home replacement service. The bridge's maintenance hold validates a specific weekly-maintenance contract. | Build bounded replacement/recovery orchestration; do not claim the existing maintenance hold is already a general migration API. |
| Browser lifecycle | [space_guest.py](../../runtime/selkies/space_guest.py) creates the profile inside a session directory and removes it on retirement. Native controller/viewer generations have their own authority. | Native agent recovery does not preserve browser cookies. DW-3 owns retained profiles and reset; stale viewer grants must not revive after replacement. |
| Release and rollback | [release.py](../../scripts/release.py) applies static web changes only. [rollback_compat.py](../../runtime/hermes/rollback_compat.py) preserves the qualified old-runtime/schema-31 interpretation without restoring an old database. | A paired native/application recovery lane remains necessary. Preserve newer data and the compatible source pair. |

The current app remains one configured owner and one web process. Process-local
send locks and the observer are not a distributed worker lease. Existing browser
generation fencing is valuable but does not fence writes to an entire Hermes home.
The earlier controller/fleet code retained in this repository is outside this
application; its task/recovery features must not be counted as active chat behavior.

## Retained-store contract to finish

| Store | Reuse | Remaining integration requirement |
| --- | --- | --- |
| Chat SQLite and adjacent originals | Current ChatStore schema and immutable file publication | Back up a coherent set; retain conversation/run mappings, grants and file references during replacement. |
| Hermes home | Native session DB, run-idempotency DB, memories, skills, configuration and required workspace data | Map the installation's actual files and any external provider state; attach to one runtime owner; use native recovery tools. |
| Native vault and browser-control DB | Existing vault and native controller storage | Locate both explicitly, preserve key custody, and reconcile/retire browser generations. Configured control storage is not assumed to be inside the native archive. |
| Browser profile | Separate future retained store | Implement its own backup/restore and exclusive attachment. Current profile contents are temporary. |
| Source, overlays, dependencies and private settings | Current pinned composition and deployment configuration | Keep a compatible runtime available independently of backups; validate source/schema and callback configuration before admission. |

The installation-specific manifest should contain identities, store roles,
locations, versions, backup digests and exclusions, never secret values. Private
paths and evidence remain in deployment records. This source review does not
claim to inventory every file or optional provider on a running host.

Keep a retained home outside disposable release/worker storage. For ordinary
replacement, stop its old owner and attach that same home to its successor; do
not restore an older archive over current work. For migration or disaster recovery,
use the native archive plus the other required stores. Initially quiesce relevant
writers to create the recovery set; copying a live SQLite main file alone is unsafe.
Host-loss recovery requires a separately protected copy, not just a persistent
directory on the worker host.

## What to build next

**DW-0/DW-1: an operator-controlled replacement/recovery path for one assistant.**
Its responsibilities are limited to store/source validation, protected recovery
packaging, holding dispatch, native drain/stop, exclusive state attachment,
successor readiness and run-status reconciliation. The current stable endpoint
can remain; no per-message frontend routing or runtime fleet is needed for this
slice. A later on-demand launcher can use the qualified lifecycle path.

Holding dispatch must cover Send, explicit Retry and automatic follow-ups. It must
survive coordinator interruption until ownership is reconciled. Before attaching
storage writable, confirm the prior gateway and relevant writers are stopped;
when that cannot be established, leave admission held. Keep source/version and
home identity checks outside model-controlled task input.

Finish with an installed acceptance check of the new boundary, using synthetic
state: reattach a retained home, continue the mapped conversation, read the saved
notes and Library file, and reconcile an interrupted run without redispatching
it. Separately restore the packaged recovery set to check coverage. The expected
native behavior comes from the upstream contract; this check verifies our wiring.

DW-2 adds the browser file-transfer bridge to the existing Library. DW-3 adds
browser-profile persistence and Reset browser data. These are independent of
proving native memory feasibility and can proceed once their contracts are agreed.
SPACE continues to supply the qualified browser slice; snapshot acceleration,
disposable shell execution, helpers and any alternative runtime remain separate
increments. This review changes no installed service or backend selection.

## Existing tests to reuse

These test bodies were inspected, not executed in this documentation pass:

- [test_minimal_chat.py](../../tests/test_minimal_chat.py):
  `test_restart_keeps_session_transcript_and_run_without_redispatch` and
  `test_never_attempted_reservation_can_prepare_after_restart`.
- [test_chat_followups.py](../../tests/test_chat_followups.py):
  `test_waiting_replay_restart_and_order`,
  `test_unknown_queued_admission_never_automatically_retries`,
  `test_restart_after_queue_promotion_before_dispatch_is_safe`, and
  `test_observer_advances_authorized_queue_without_browser_polling`.
- [test_chat_attachments.py](../../tests/test_chat_attachments.py):
  `test_image_and_code_are_preserved_across_restart_and_replay` and
  `test_slow_preparation_starts_recovery_window_at_first_post_and_keeps_it_across_restart`.
- [test_hermes_adapter.py](../../tests/test_hermes_adapter.py):
  `test_start_and_identical_replay_use_the_pinned_runs_contract` and
  `test_capability_preflight_requires_durable_bounded_idempotency`.
- [test_hermes_rollback_compat.py](../../tests/test_hermes_rollback_compat.py)
  covers the pinned rollback source transformation.

These use fixtures and cover important existing contracts; they do not prove
cross-host home attachment. Extend coverage only for the new replacement hold,
ownership checks, archive handling and source/store compatibility. Keep the
existing real-pilot qualification scoped to its recorded revision and behavior.

[up-api]: https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/website/docs/user-guide/features/api-server.md#runs-api-streaming-friendly-alternative
[up-memory]: https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/website/docs/user-guide/features/memory.md
[up-backup]: https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/website/docs/reference/faq.md#exporting-hermes-to-another-machine
[up-backup-code]: https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/hermes_cli/backup.py
[up-sqlite]: https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/hermes_cli/backup_sqlite.py
[up-community]: https://github.com/NousResearch/hermes-agent/issues/134889
