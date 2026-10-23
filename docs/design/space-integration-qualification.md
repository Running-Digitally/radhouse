# SPACE integration: initial implementation and qualification

Updated: 2026-10-22. Status: experimental client with bounded live Firecracker
lifecycle, headed-browser and streamed-control results, subject to the limits below. No remote
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
operation/sandbox observations, a three-step readiness check, and experimental
HTTP port-session creation/revocation for the browser lab. It deliberately
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

The first lifecycle phase and subsequent browser phase ended with their guests
deleted, lab stopped and temporary kernel settings restored.
These results support continued integration work, not replacement of the pilot.
The temporary test journal is not the durable Radhouse computer journal.

## Live browser transport experiment

The exact experimental Radhouse client created a scoped port session to a synthetic
HTTP/WebSocket service inside a deny-all Firecracker guest. HTTP path/query and a
synthetic browser cookie arrived intact; SPACE stripped its scoped Authorization
header before forwarding. Missing credentials returned 401; management and invalid
credentials returned 400. A real WebSocket upgrade and bidirectional echo passed.

Revocation returned the expected revoked session and subsequent HTTP requests
returned 401. **The already-open WebSocket still carried a test message two seconds
after revocation.** This is a bounded observation, not a claim about an indefinite
connection lifetime. Radhouse must actively close streams and fence browser input
when current authority is withdrawn; revoking a SPACE session alone is insufficient.
Preserve the existing application session checks and browser control lease in any
new relay, and test their actual disconnect/input latency through SPACE.

A separate guest probe passed non-root creation of nested user, PID and network
namespaces on the pinned guest kernel. Both probe guests were deleted. The echo
service qualified the transport boundary; the following experiment exercised the
actual browser package.

## Headed browser and separate shell result

The existing Selkies/browser qualification package ran inside a deny-all
Firecracker guest with two vCPUs, 3,072 MiB RAM and an 8,192-MiB disk. The pinned
native page-only driver was reused by exact SHA-256; it was not replaced by an
unrestricted browser driver. All page content and stored state were synthetic.

| Check | Observed result | Limit |
| --- | --- | --- |
| Chromium sandbox | UID 1000 renderers in nested user, PID and network namespaces, with seccomp filters; no sandbox-disabling launch flags | Runtime checks, not an escape assessment |
| Native browser access | Snapshot through the existing seven-tool boundary passed | Does not qualify an entire Hermes conversation or every tool |
| Selkies transport | Separate SPACE bearer and Selkies subprotocol credential; 90 encoded video frames in a three-second capture; a decoded frame visually inspected | No end-user frontend, latency or quality parity benchmark |
| Shared control | Viewer input blocked; human input changed the fixture; agent access blocked during human control; old human input blocked after handback; agent snapshot resumed | Existing controller exercised inside the guest; application session revocation still needs an integrated relay test |
| Pause/wake | Synthetic cookie, local storage and a file survived; Chromium sandbox checks still passed; video reconnected | Same guest and profile; no cold replacement, durable external profile store or memory-snapshot restore |
| Separate task computer | Concurrent root-shell guest had a distinct identity and filesystem; each guest lacked the other's private test file | Bounded filesystem checks, not cross-guest exploit testing |
| Teardown | Guests deleted; sandbox inventory, pods and Firecracker processes empty; lab stopped and temporary settings restored | Retained lab images remain experimental |

The browser was packaged as an offline filesystem inside the pinned seed guest,
with a private mount namespace and `pivot_root` before dropping to UID 1000.
This avoided plain `chroot`'s restriction on unprivileged user namespaces and
kept Chromium sandboxing enabled. It is a lab packaging method, not a maintained
SPACE browser template. The experiment also exposed Python's script-directory
shadowing of the standard-library `platform` module. The qualification Docker
entrypoint now uses `python -P`; that exact invocation worked inside the guest.
The retained image predates this entrypoint fix and used an explicit launch
override, so a rebuilt image still needs its normal release qualification.

After the lab host reboot, two temporary TSC trials did not expose the KVM
realtime-clock flag required by the snapshot preflight. The second sampled it
11 times over five seconds. Both restored the original clock. **Browser suspend
and memory-snapshot wake were therefore not attempted.** The earlier successful
lifecycle remains evidence for that earlier configuration; this boot has not
requalified it. Pause/wake must not be presented as replacement or snapshot
recovery. Diagnose and qualify the intended worker clock contract before relying
on suspend for an always-on assistant.

Runtime tests retained substantial host headroom and did not disturb baseline
services. Two preparation attempts hit their own container memory limits: a
native rebuild and a JSON payload uploader. The exact retained native binary
removed the rebuild need; upload resumed only after verifying the entire remote
prefix against the frozen source, using smaller chunks. These findings do not
establish a multi-user capacity budget. Payload transfer through SPACE's operator
API also does not implement the Radhouse Library or browser upload/download UX.

## Experimental port-session contract

The client implements one HTTP port-session request and its explicit revocation.
The request carries a saved caller-owned key; there is
no automatic retry. Response validation binds the sandbox, session, port,
protocol, scope, token expiry and exact proxy URL to an independently configured
data-plane origin. The separate scoped token is excluded from object repr and
must remain in memory. The client performs no attachment or forwarding itself.
Revocation confirms the exact session's revoked state; it does not remove port
exposure, and the pinned revoke endpoint does not deduplicate the supplied key.

This follows the pinned [public session contract](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/public/api/src/lib.rs)
and [port-session route](https://github.com/perplexityai/SPACE/blob/f2184a1e2ea49a4d73102dc0bb96e0bad7a2ca93/crates/libs/api/src/routes/public/sessions.rs).
Targeted synthetic tests cover wrong origins, credentials in URLs, scope/identity
mismatch, expiry, lost acknowledgement and revocation. Basic live HTTP/WebSocket
forwarding, Selkies credentials, human/agent fencing and reconnect after pause/wake
passed as described above. Reconnect after memory-snapshot restore and application
integration remain unqualified. No application route or model tool enables this interface.

## Next executable steps

1. Complete the native state/release contract in DW-0 and the clean checkpoint/
   replacement fixture in DW-1. Include pending native work and effects, not just
   displayed chat and two memory files.
2. Turn the working browser package into a pinned, reproducible SPACE template.
   Preserve Chromium sandboxing and the existing narrow native tool boundary.
   Keep real accounts and pilot profiles outside the lab; measure readiness,
   stream/input latency and concurrent capacity against explicit budgets.
3. Reproduce the bounded lifecycle on the intended maintained substrate with
   accepted clock and resource settings. Preserve authenticated management,
   template digests and durable intent/receipt ordering.
4. Extend the real lifecycle result to lost-connection recovery and current
   authority after restore. Add command-session attachment to the application
   with a separately scoped token and durable output handling; a management
   bearer must never follow an attachment URL.
5. Add the disabled application browser adapter with active stream closure and
   current-authority checks. Test durable profile export/restore, Library transfers,
   full frontend behavior and shell separation before owner-pilot enablement.
   Preserve the existing runtime and data-compatible rollback through evaluation.

No code in this slice changes the working pilot or satisfies production adoption
gates. In particular, an accepted worker configuration, native checkpoint
implementation, durable computer journal, current-authority restore and an
application-integrated remote browser remain outstanding.
