# SPACE and durable agent workspaces

Date: 2026-10-21. Status: technical research supporting a proposed architecture.

SPACE is a candidate execution backend for Radhouse. The enduring requirement
is that an assistant retains its conversation, files and pending work while its
compute can be replaced. SPACE supplies useful isolation and lifecycle machinery;
Radhouse must supply state ownership, current authority, browser privacy and
honest recovery. No SPACE adoption or host qualification is established here.

The source baseline is Radhouse
[`f44df3e8172e834a913b8418c6b21db00d92e1c9`](https://github.com/Running-Digitally/radhouse/tree/f44df3e8172e834a913b8418c6b21db00d92e1c9)
and SPACE
[`f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93`](https://github.com/perplexityai/SPACE/tree/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93).
These are inspected revisions, not claims about the latest upstream or installed
software. The [proposal](../design/durable-assistant-workspaces.md) applies the
findings; the [roadmap](../plans/2026-10-21-durable-workspace-roadmap.md) owns the
qualification sequence.

## What SPACE provides

SPACE manages isolated Linux sandboxes, process execution and asynchronous
lifecycle operations. Its application interface is HTTP; callers do not need
to embed its Rust implementation. Templates define starting environments;
sandboxes retain their own writable state. Command streams and sandbox lifetime
are distinct. The repository is Apache-2.0 licensed; image and bundled dependency
licenses still require their own review. See the pinned
[overview](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/README.md)
and [license](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/LICENSE).

| Mechanism | Meaning for an application |
| --- | --- |
| Create and execute | Await operation completion and endpoint readiness; acceptance alone does not establish a usable computer. |
| Pause | Memory remains resident. This is not durable protection against worker loss. |
| Suspend and wake | Save and restore memory, runtime state and filesystem through the supported lifecycle. |
| Fork | Creates another execution branch on supporting substrates; application authority and effects need separate reconciliation. |
| Network gateway and credential injection | Enforce supported policy outside the guest; the application still defines permitted actions and data disclosure. |

The [architecture](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/docs/architecture.md)
and [guest I/O contract](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/docs/space/design/guest-io.md)
distinguish acknowledged writes from lifecycle persistence. A successful guest
write is not sufficient evidence that a file survives a crash or host failure.
Commit Library files and application receipts independently of VM retirement.

## Security evidence and its interpretation

Perplexity's [Escaping SPACE Part I](https://www.perplexity.ai/en-GB/hub/blog/escaping-space-part-i)
reports no VM-to-host escape in 108 runs. Before remediation, network bypass
succeeded in 11 of 54 partial-network runs and none of 54 no-network runs.
Reported mechanisms involved forged DNS attribution and shared-IP routing;
follow-up evaluation reported no verified bypass of the remediated mechanisms.
These are publisher results for a bounded experiment, not a proof of isolation
or an independent Radhouse security test. VM containment and network policy are
different boundaries.

The pinned [network policy types](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/net/common/src/lib.rs)
and [operator egress profiles](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/docs/egress-profiles.md)
make configuration material to the security claim. TLS interception is not
universally enabled, exemptions bypass inspection, and restored/forked policy
cannot be assumed to incorporate subsequently changed operator profiles.
Qualification must inspect and exercise the effective configuration after
creation and restore. A permitted destination can still accept an unauthorized
upload or account action. Keeping a token outside a guest limits token exposure;
it does not make every authenticated request acceptable.

Guest root can read the data and browser state placed inside that guest. Keep
arbitrary shell execution separate from the interactive browser's profile and
credentials. Do not give shell helpers access to browser debugging, storage keys,
the control database or unrestricted management endpoints. A restored snapshot
must not revive a revoked grant or replay an uncertain external mutation.

## Deployment and compatibility constraints

The pinned [installation guide](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/docs/installation.md)
uses Linux x86_64 with KVM, tun and loop devices, btrfs and privileged Docker.
An existing VM needs actual nested-virtualization and device qualification.
A Mac development environment does not demonstrate Firecracker host readiness.
The guide's Kind setup is a development path, not a production configuration.

Kubernetes is not mandatory for every SPACE deployment. At the inspected
revision, the [direct adapter](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/api/src/controllers/substrate/direct.rs)
has limitations around durable fork restoration, and the
[substrate capabilities](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/api/src/controllers/substrate/mod.rs)
do not establish direct-mode node draining. The
[AWS reference](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/infra/space/aws/reference/README.md)
covers infrastructure rather than a complete application rollout. Choose a
deployment path against required capabilities, not a diagram's implied parity.

The [versioning contract](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/docs/versioning.md)
requires compatibility across retained state and host/guest versions. The
[E2B wrapper](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/docs/ecw.md)
has a specified tested client surface, unsupported create options and different
pause/resume naming. Avoid relying on generated schema types as proof that an
interactive API is supported. Pin and qualify the actual interface selected.

## Lessons from always-on agents

Lee Robinson's [Stanford CS146S lecture on always-on agents](https://www.youtube.com/watch?v=L1OBRtfPS34)
is useful design context. The following are original engineering interpretations
for Radhouse, not an assertion that the lecture's system or roadmap is deployed
here:

- Retained knowledge, an agent loop and its computer can have different lifetimes.
  An always-available assistant does not require a continuously active worker.
- Work needs durable triggers, progress and recovery beyond an open chat connection.
  A workflow engine does not automatically make external effects exactly once.
- Helpers need bounded context, resources and a way to return results; shared
  memory requires coordination.
- Working context can be compacted while originals and evidence remain retained.
  A summary or provider prompt cache is not a native runtime checkpoint.
- Deciding when to notify a person is part of the product. A background result
  should not require a fabricated chat reply to count as completed work.
- Evaluate useful completion, recovery, permission boundaries and interruption
  quality together with model and harness versions.

The lecture's resumable user computer and SPACE's task sandboxes are different
allocation choices. Radhouse can use a persistent browser session alongside
disposable shell computers. No eight-service extraction is necessary to establish
these responsibilities. See also [Temporal's activity semantics](https://docs.temporal.io/activities)
for why retries and effect-specific idempotency remain application concerns.

## Current Radhouse source and missing contracts

| Current evidence | Consequence for the target |
| --- | --- |
| [ChatStore](../../src/radhouse/chat/store.py) retains messages, original files, file grants and receipts; Hermes retains native context. | Inventory both stores and commit compatible recovery points. Visible chat alone cannot recreate the assistant. |
| [ChatService](../../src/radhouse/chat/service.py) uses a process-local lock and in-flight work. | Multiple workers require durable admission, exclusive session leases and stale-writer rejection. |
| [About You](../../runtime/hermes/about_you.py) reads saved memory files. | This is not a complete native state export/import API. |
| [Library](../../src/radhouse/chat/static/library.js) lists uploaded and assistant-shared files; [file sharing](../../runtime/hermes/bridge.py) publishes UTF-8 output. | General browser uploads and completed-download intake need new restricted contracts. |
| [Browser worker](../../runtime/selkies/network_worker.py) creates a generation-local profile and removes it at retirement. | Persistent browser profiles and VM restore are new capabilities. |
| [Selkies platform](../../runtime/selkies/platform.py) uses Xvfb, CPU encoding and WebSocket streaming. | A browser guest is plausible without a GPU, but latency, resources and kernel sandbox support need actual qualification. |
| [Worker protocol](../../runtime/selkies/network_protocol.py) authenticates local Unix peers; display and native transport assume a host-local topology. | A remote computer needs a new authenticated transport and equivalent lifecycle/privacy enforcement. |
| [Saved logins](../../runtime/hermes/vault_bridge.py) use exact-origin filling with secret values kept out of model results. | Preserve the vault boundary; browser persistence must not create a second uncontrolled password store. |

The final [S5 acceptance entry](../plans/2026-10-15-boundary-stabilization.md#observed-owner-pilot-acceptance-after-diagnostic-selection)
records owner-pilot acceptance with retained lifecycle follow-ups. It does not
qualify remote browser workers, co-tenancy or a new host. Reopen the investigation
on recurrence and before expanding those boundaries.

## Browser migration and files

Use one Library and the same completed-download behavior for human and agent
actions. Provenance should not force people to learn separate storage classes.
Retention, file processing and permission to disclose are distinct internal
contracts. Private takeover must continue to exclude private content from agent
context. [OWASP's upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
supports layered validation, isolated processing and safe storage/serving; a
human click or a malware scan does not establish that document instructions are
authorized.

Chromium's [user-data directory](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/user_data_dir.md)
contains profile and installation state. Preserve a consistent compatible profile
rather than inventing a cookie-only backup. Treat caches as replaceable and
completed downloads as independently durable. The current launcher's `basic`
password-store selection needs explicit treatment before profile retention;
[Chromium documents its storage behavior](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/linux/password_storage.md).
This setting does not prove that browser-saved passwords currently exist.

Optional browser onboarding can import supported bookmarks and preferences.
Copying a laptop profile cannot guarantee portable login sessions:
[OS/application-bound encryption](https://security.googleblog.com/2024/07/improving-security-of-chrome-cookies-on.html)
and [device-bound sessions](https://blog.google/security/protecting-cookies-with-device-bound-session-credentials/)
can prevent reuse elsewhere. Sign-in and MFA may be required. Do not weaken those
protections or automatically activate imported extensions to simulate a full
clone. This is a later convenience capability, not an onboarding prerequisite.

## Qualification conclusion

First prove continuity of the whole assistant and its files using the existing
runtime. Evaluate SPACE separately on a qualified Linux host with synthetic
data. Measure cold/warm readiness, browser responsiveness, checkpoint/restore,
resource use, effective network policy, revocation and orphan recovery.

There are no Radhouse-specific SPACE performance results or host-suitability
measurements in this review. The next decision is whether a qualified adapter
improves the required isolation and lifecycle behavior at acceptable operating
complexity. A narrowly demonstrated file computation is insufficient evidence
for whole-assistant or interactive-browser continuity.
