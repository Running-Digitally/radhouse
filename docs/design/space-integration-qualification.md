# SPACE integration: initial implementation and qualification

Updated: 2026-10-22. Status: experimental client with a successful bounded
Firecracker lifecycle test, subject to the clock prerequisite below. No remote
browser or agent tool has been enabled in the working Radhouse pilot.

This starts the [durable-workspace roadmap](../plans/2026-10-21-durable-workspace-roadmap.md)
with a recoverability baseline and a small management client for later DW-4 lab
testing. It does not mark DW-0, DW-1 or DW-4 complete. The target remains the
whole assistant with a retained browser and separate task computers.

## Implemented boundary

[`SpaceClient`](../../src/radhouse/integrations/space.py) is a synchronous,
management-only client using the existing HTTPX dependency. No application
factory, chat route, native tool or browser adapter imports or enables it.

It supports explicit sandbox create, pause, suspend, wake and delete requests,
operation/sandbox observations, and a three-step readiness check. It deliberately
does not yet execute commands, attach streams, transfer files, mount profiles,
fork sandboxes or expose the management credential to Hermes.

| Boundary | Implemented behavior | Remaining qualification |
| --- | --- | --- |
| Transport | Verified HTTPS; HTTP only for literal loopback IPs; no environment proxies or redirects; bounded response/deadline checks; sanitized errors | Real service TLS, installation identity and authorized transport |
| Creation | Full template digest, explicit resource shape, Firecracker runtime and an explicit deny-all egress request | Actual resolved image/shape, effective policy and guest-root enforcement |
| Mutation | Caller-supplied idempotency key; no automatic retry; uncertain outcomes remain explicit | Durable application intent/receipt storage, fencing, revocation and reconciliation |
| Acknowledgement | Valid sandbox/operation identifiers bound to the requested target | Actual asynchronous substrate behavior and interruption |
| Readiness | Exact operation ID/kind/target, successful operation, running sandbox, responding process endpoint | Command execution, browser stream/input responsiveness and failure recovery |
| Deletion | Accepted deletion is an operation receipt; 404/errors are not success | Poll/reconcile completion and verify resources/retained state are retired correctly |

The caller must save the intended owner/run, exact request body and idempotency key
before a mutation. The client itself is not a durable journal or an authorization
service. Its lost-ack test demonstrates transport behavior with a caller-owned
synthetic intent record; it does not establish production exactly-once effects.
Never use the management client directly as a model tool. It is not wired into
the existing human-only Terminal.

This initial endpoint configuration supports the dedicated `/v1` API root. SPACE
also documents a shared-host `/api/v1` root; that deployment shape is not supported
by this client yet. A caller must select a qualified endpoint rather than silently
rewrite paths or fall back to another adapter.

## Source basis

Radhouse baseline: public documentation commit
[`8e852cc`](https://github.com/Running-Digitally/radhouse/commit/8e852ccb20879461bdd78b949d7db1dc71194023).
SPACE source: pinned
[`f2184a1`](https://github.com/perplexityai/SPACE/tree/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93),
not a claim about current upstream. The client was checked against these original
upstream files without copying their implementation into Radhouse:

| Public source | SHA-256 of inspected file |
| --- | --- |
| [M1 OpenAPI baseline](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/api/src/routes/public_docs/compatibility/m1_openapi_baseline.json) | `dfc1bdc46060bf940e94d2b96d77ea2bc29adc20839581a56b6130648150252b` |
| [Network policy types](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/net/common/src/lib.rs) | `aca7968b07729d1091b23309990927fca743bd4a3e1fea568abc7823941697f9` |
| [Process/idempotency types](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/common/core/src/types/process.rs) | `6213f71ccc49b1ce82b1800c5a3c322e5c60a3ba3579d0ee1e5fb8a1651e543b` |
| [First-sandbox example](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/examples/first_sandbox.py) | `e9884066ef792571a8f4b4e7925785ea3122e09b9a183a15e6f2f28079264ea9` |

The request's network-policy field is an incubating upstream contract. A valid
request and matching schema do not prove that operator policy composition or a
restored sandbox enforces the intended restrictions. Pin and test that behavior
on the real host before integration.

## Initial state inventory and recovery baseline

| Current source | Retained state / migration consequence |
| --- | --- |
| [ChatStore](../../src/radhouse/chat/store.py) | SQLite transcript, session/run identity, queue and file/grant metadata; originals in its adjacent `.files` directory. Preserve both and their relationship. |
| [ChatService](../../src/radhouse/chat/service.py) | Admission/retry/reconciliation behavior includes process-local work. App restart tests do not prove replaceable native workers. |
| [Native source lock](../../runtime/hermes/source-lock.json) and [About You](../../runtime/hermes/about_you.py) | Pinned overlays and memory-file readers exist; full native database/configuration/checkpoint inventory and export/restore remain open. |
| [Browser control](../../runtime/hermes/browser_control.py) | Separate SQLite authority/generation records must be reconciled with active browser ownership. |
| [Vault bridge](../../runtime/hermes/vault_bridge.py) | Profile-local `vault/vault.key` and `vault/vault.json.enc` require separate custody and compatible recovery; never mount them in arbitrary shell guests. |
| [Browser worker](../../runtime/selkies/network_worker.py) | Current generation-local profile retirement is not durable browser-state storage. |

The existing synthetic chat suite passes restart continuity, lost-ack recovery,
ordered follow-ups, Library access and frozen dispatch inputs. It reopens Radhouse
state around a synthetic Hermes service; it does not restart the real Hermes
engine, migrate a browser profile or preserve a real in-flight tool process.
Those distinctions prevent an app-restart test being mislabeled as DW-1 completion.

## Reproduce local checks

Use the repository's existing qualified Python environment; no new dependency
is added by this slice:

```sh
python -m pytest -q tests/test_space_adapter.py tests/test_space_host_probe.py
python -m pytest -q tests/test_minimal_chat.py tests/test_chat_followups.py tests/test_chat_library.py tests/test_chat_workspace.py
python3 scripts/space_host_probe.py
```

The host probe is read-only. It checks Linux x86_64, access to required character
devices, KVM API version 12, registered btrfs support and CLI presence. It does
not install packages, load modules, mount filesystems, run privileged containers
or create a VM. It prints no hostname, addresses, environment values or secrets.
Exit 1 means local prerequisites are missing; exit 0 still requires privileged
qualification and always reports `qualified: false`.

The local macOS development host fails the Linux/KVM/btrfs prerequisites, as
expected. Docker CLI presence alone does not make it a SPACE host. A separate
dedicated Linux test VM has now been selected and screened through its existing
unprivileged account. Its subsequent privileged preflight confirmed KVM API 12,
Docker and the underlying storage. The pinned Rust workspace, guest binaries,
runtime images, seed and Kind node image built successfully. The six-node
Kubernetes substrate and SPACE services reached readiness. Host identity,
allocation, access and detailed resource receipts stay in the private operational
record. The bounded guest result follows below.

Recorded local result: **92 new client/host-screen tests passed**, plus **64
existing chat, follow-up, Library and workspace tests passed**. The public-source
privacy gate passed. Coverage measurement was unavailable in the existing test
environment; no coverage percentage is claimed and no dependency was installed
just to obtain one. No live SPACE API or VM was exercised by these tests.

## Real Linux/Firecracker result

The exact management-client source was subsequently exercised against the pinned
SPACE service with Python 3.14.4, HTTPX 0.28.1 and dependency hashes from this
repository's lockfile. The synthetic guest used one vCPU, 512 MiB RAM and a
1,024-MiB disk. Requests and operation receipts were saved before advancing;
mutations were not automatically replayed.

- Create, operation/process readiness, command output over the public data
  plane, pause and wake passed.
- Suspend and snapshot wake passed with the required host clock configuration.
  A synthetic file remained readable after both wake paths. This verifies that
  file's persistence; it does not prove Hermes checkpoint compatibility or
  browser-profile recovery.
- Delete operations succeeded; the public sandbox inventory, sandbox pods and
  Firecracker processes were empty at closeout.
- One HTTPS destination was reachable outside the sandbox but blocked from
  guest root under the client's deny-all request, including a direct-IP request
  that bypassed DNS. This lacked an allow-policy positive control inside a guest
  and does not qualify every protocol, policy change, restore-authority check or
  escape boundary. The first probe correctly rejected a non-root command; the
  seed's documented sudo capability was then invoked explicitly.

Snapshot restore has a material prerequisite. On x86_64, pinned SPACE explicitly
requests `clock_realtime: true`. Firecracker requires a TSC-based clock source on
the host that creates that snapshot. A nested Linux host using `kvm-clock`
produced a snapshot that could not satisfy that request. A bounded test with
`tsc` passed the complete lifecycle, then restored the original host setting.
Do not disable realtime restoration to conceal this incompatibility; qualify
clock behavior on the intended worker, including migration and restart.
See [SPACE's restore request](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/node/runtime/core/src/fc_api.rs)
and [Firecracker's snapshot contract](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/snapshot-support.md).

The installation also exposed development-harness requirements: sufficient
[inotify limits](https://kind.sigs.k8s.io/docs/user/known-issues/#pod-errors-due-to-too-many-open-files),
disk headroom for image copies, and readable static assets for the non-root UI.
The Kind device-permission workaround must not alter the host's original KVM
device inode through a direct bind mount. These are harness findings; privileged
Kind containers are not the production worker security boundary.

The lab is retained stopped, with temporary kernel settings restored. This is
evidence for continuing the integration work, not approval to replace the pilot.
The temporary test journal is not the durable Radhouse computer journal.

## Next executable steps

1. Complete the native state/release contract in DW-0 and the clean checkpoint/
   replacement fixture in DW-1. Include pending native work and effects, not just
   displayed chat and two memory files.
2. Complete runtime resource-fit and recovery qualification on the preflighted
   Linux test environment. The upstream six-node Kind harness and sparse btrfs
   caches need measured sizing; successful builds and Kubernetes readiness do
   not establish sandbox capacity. Keep real accounts and pilot profiles outside
   the lab.
3. Reproduce the bounded lifecycle on the intended maintained substrate with
   accepted clock and resource settings. Preserve authenticated management,
   template digests and durable intent/receipt ordering.
4. Extend the real lifecycle result to lost-connection recovery and current
   authority after restore. Add command-session attachment to the application
   with a separately scoped token and durable output handling; a management
   bearer must never follow an attachment URL.
5. Test browser streaming and profile restoration plus separate shell isolation
   before enabling an adapter for the owner pilot. Preserve the existing runtime
   and data-compatible rollback through the evaluation.

No code in this slice changes the working pilot or satisfies production adoption
gates. In particular, an accepted worker configuration, native checkpoint
implementation, durable computer journal, current-authority restore and remote
browser transport are still outstanding.
