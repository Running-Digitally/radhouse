# OpenShell: bounded Radhouse policy and worker compatibility review

Date/access date: **2026-09-30 UTC**. Follow-up to [the OpenShell research](2026-09-30-nvidia-openshell-research.md), specifically its first, roughly 90-minute experiment. This review used existing version-pinned upstream source and local documentation. It performed no install, image build, gateway start, bot deployment, model request, credential setup, password handling or security change.

## Decision

**GO for a narrowly scoped pilot design: a fresh Researcher-shaped worker processing supplied evidence with local files and one explicit model binding. NO-GO for executing that pilot now, replacing any existing worker, or migrating Builder.** Static compatibility is plausible; runtime compatibility and effective-policy enforcement are not qualified. The complete Experiment 1 acceptance gate has not passed: the standalone prover is unavailable, no pilot image exists in this evidence set, and no target host has been inspected.

The useful first question is whether OpenShell can add externally enforced network denial to the existing narrow Researcher workflow while preserving its durable Hermes state and interactive control. Credential confinement and fleet consolidation are later questions. No additional CWB model benchmark, PAIR routing, Kubernetes cluster, nested VM or custom driver is justified by this review.

The smallest later pilot is **one dedicated disposable Linux VM, one OpenShell v0.1.2 gateway using rootless Podman 5.x, and one retained synthetic Hermes worker**. The Podman socket belongs to the trusted gateway on that VM and is never mounted into the workload. The outer VM preserves the separate-kernel boundary from existing bots. This is a selected design, not evidence that such a prepared host is available. [Pinned runtime documentation](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/sandboxes/runtimes.mdx).

## Current-state grounding

Verified repository: `Running-Digitally/radhouse`, local checkout `/path/to/private-workspace`, branch `fix/project-deploy-after-cancelled-review`, HEAD `64c75cd8b6676226a148fb2efd83c30bc531daff`. At review start, only the two original OpenShell research documents were untracked; tracked files were clean. This checkout predates later deployment receipts. No live state was inferred from source.

Upstream baseline: OpenShell **v0.1.2**, tag commit `6648bd0c290efbc41ba131ee9831ee45cd431f94`, released September 28. This review reuses the September 30 immutable source snapshot and its [provenance](2026-09-30-nvidia-openshell-source-provenance.json). It does not substitute current `main` or claim a newly observed release. [Release](https://github.com/NVIDIA/OpenShell/releases/tag/v0.1.2).

Local worker evidence came from the adjacent private documentation checkout: [runtime recipe](../../private-installation-record), [base renderer](../../private-installation-record), [Researcher renderer](../../private-installation-record), [delivery profiles](../../private-installation-record), [Builder renderer](../../private-installation-record), and [ADR-0073](../../private-installation-record). They are dated configuration/acceptance records, not a new deployed-profile inventory. Private addresses, credentials, payloads and raw transcripts are omitted.

## Concrete worker fit

| Worker | Concrete documented needs | Static verdict and first-pilot implication |
|---|---|---|
| Researcher | Pinned Hermes; terminal/file/memory/todo/session-search profile; one configured active run; fixed `example-provider-chat` binding; no fallback. The qualified useful slice includes one read-only local file tool loop. Browser, messaging, skills installation, MCP and delegation are outside that slice. | **Best candidate**, limited to supplied synthetic evidence and the already qualified kind of file task. No mandatory namespace/mount operation is apparent in this slice. This does not qualify arbitrary shell tools or general web research. |
| Reviewer | Git/gh repository reads, bounded tests, comment-only review, loopback browser QA and native vision; manual approvals and command allowlist. The inspected renderer does not require Docker. | **Defer full role.** Chromium sandbox/process behavior, project test dependencies and authenticated GitHub/PR comments need separate qualification. A supplied-diff reading slice could fit later, but would not establish full Reviewer compatibility. |
| Builder | Accepted autonomous unprivileged development, rootless Docker/Compose, package tools, local databases, preview work and browser QA inside its VM; ordinary commands should not require approval. | **NO-GO for direct first migration.** Mandatory OpenShell workload syscall restrictions conflict with an in-workload rootless daemon. An exposed external Docker socket creates another execution authority path. A growing command allowlist would undo the accepted experience. |
| Deployer | Exact approved revision and named service/release effects in its own guest; a separate scoped delivery identity. | **Outside first pilot.** Containment of local evidence is not admission of deployment authority. Its existing host service/effect contract would need an explicit design and review. |

Builder's `DOCKER_HOST` references a rootless guest socket. OpenShell's workload filter denies `unshare`, `setns`, `mount`, `umount2`, `pivot_root`, `chroot` and newer mount operations. Thus nested rootless Docker is a **source-backed incompatibility inference**, not an integration attempted and failed. Rootless Podman on the trusted gateway host is a different placement; those workload restrictions do not themselves prohibit the gateway's compute driver. [Filter source](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-isolation-interface/src/linux/child_seccomp.rs), [runtime placement](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/about/architecture.mdx).

The Researcher base renderer alone is insufficient for reproduction. Its retained recipe specifies Hermes `2237be355906fbe6065ce1815711eee52b2d646e` plus **six ordered source layers**, ending with prefix isolation source `31d97af4010d94530b9c7534bdcb63f42bc83b2f`. Preserve the later profile's two ordinary turns, four physical primary provider attempts and `fresh_cache_salt: true`; do not regenerate only the initial base configuration. Its exact interpreter is standalone **CPython 3.12.14**, with **SQLite 3.53.1**, and the pinned composition has 80 wheels. A generic Ubuntu `python3.12` image is not equivalent. The installation script is guest-identity guarded and must not simply be run against a new image or VM. [Composition lock](../../private-installation-record), [installer source](../../private-installation-record).

The local `runs-allowed-tools-v1` README still says live acceptance is pending. This review does not add that overlay to the six-layer pin or assume its optional capability is present. Keep the documented profile; use synthetic tasks to observe its existing file loop. A tools-disabled canary can precede that task. [Overlay status](../../private-installation-record).

## Effective policy: what must be counted

The following is an admission inventory, not a claim that an authored YAML file is the complete runtime boundary.

| Composition input | Selected design | Evidence/required check |
|---|---|---|
| Global policy | Absent on this single-purpose pilot gateway. | Global policy **replaces** sandbox policy and suppresses provider rules; it is not an intersecting owner ceiling. Record absence before creation and after restart. |
| Saved versus image policy | Explicit reviewed `--policy`; record any image policy and relevant policy environment input. | Saved policy outranks image/default policy. Freeze the selected base/effective policy digests. |
| Attached providers | None in the first pilot. | Providers add network authority to the effective policy. No hosted credential profile or implicit GitHub grant is needed for supplied evidence. |
| Network filesystem enrichment | Explicitly account for `/usr`, `/lib`, `/etc`, `/app`, `/var/log`, `/proc`, `/dev/urandom` read access, and `/tmp`, `/dev/null` writes. | Networking adds available baseline paths at startup and saves enrichment. `/etc` means the image's files, so the image must contain no imported host secrets. |
| Runtime-only grant | Read-only `/run/openshell-supervisor-ca`; no GPU. | CA access is absent from exported policy views. GPU would add device and `/proc` writes; exclude it. |
| Persistent storage | Driver-owned private `/sandbox`; synthetic home/work beneath it. | No host binds, management sockets, supplemental image mount, external volume or custom driver JSON. Resource admission remains enabled. |
| Process and syscall controls | Explicit UID/GID 1000 at creation; hard Landlock requirement; immutable interpreter/source tree. | Non-root plus mandatory baseline and denied syscalls are distinct from filesystem/net rules. Confirm the real executable path and image ownership. |
| Proposal handling | Gateway-wide `proposal_approval_mode=manual`; `agent_policy_proposals_enabled=false`. | Advisor-off still permits OpenShell to draft proposals. Manual mode prevents those drafts from adding authority. No approvals during this trial. |
| Model calls | One exact existing endpoint/port/IP; REST enforcement; only the required API methods/paths. | Neither a provider attachment nor the network policy selects a model. Native client configuration owns `example-provider-chat`, timeouts and no fallback. |
| Management API and task authority | Gateway/Podman authority stays on trusted host; Hermes API is reached only through an operator-owned local forward. | OpenShell sandbox identity is not Radhouse bot identity, Buzz membership, task authorization or publication approval. No real Buzz/controller connection in the first pilot. |

Sources: [policy selection](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/policies/overview.mdx), [baseline paths](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/policies/default-policy.mdx), [schema](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/policies/schema.mdx), [advisor](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/policies/advisor.mdx), [resource admission](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/gateways/configuration.mdx).

Two limits matter. First, a grant to the real Python executable also authorizes descendant tools to reach the same endpoint. It is not an agent-module-specific restriction. Second, REST method/path rules cannot restrict the request's JSON `model` field. Keep the client binding explicit, inspect actual request/served-model attribution and detect configuration drift; do not claim OS enforcement of a particular model identifier. The existing stable alias can follow an operator-switched backing model, with capability revalidation. [Binary matching](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/policies/network-rules.mdx), [native inference ownership](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/inference.mdx), [Radhouse provider contract](integrations/hermes.md).

### Review-only policy shape

This sanitized example uses RFC 5737 documentation address `192.0.2.10`. It is **not runnable as the real pilot policy**. Replace it only with a newly admitted, exact copy of the privately documented model endpoint; never infer that the existing bot's network grant automatically authorizes a new VM. Port 8000 and the runtime prefix come from the inspected source. The real Python path below is the installer's expected standalone path, still requiring image symlink/executable verification.

```yaml
version: 1
filesystem_policy:
  include_workdir: false
  read_only:
    - /bin
    - /usr
    - /lib
    - /etc
    - /app
    - /var/log
    - /proc
    - /dev/urandom
    - /opt/hermes/2237be355906fbe6065ce1815711eee52b2d646e
    - /run/openshell-supervisor-ca
  read_write:
    - /sandbox
    - /tmp
    - /dev/null
landlock:
  compatibility: hard_requirement
process:
  run_as_user: "1000"
  run_as_group: "1000"
network_policies:
  fixed_model:
    endpoints:
      - host: 192.0.2.10
        port: 8000
        allowed_ips: [192.0.2.10/32]
        protocol: rest
        enforcement: enforce
        rules:
          - allow: {method: GET, path: /v1/models}
          - allow: {method: POST, path: /v1/chat/completions}
    binaries:
      - path: /opt/hermes/2237be355906fbe6065ce1815711eee52b2d646e/python/python/bin/python3.12
```

The owner maximum is a separate reviewed file allowing only these destinations, methods, exact executable paths, identities and path access classes. Initially it may have the same grants as this effective candidate; it must remain independently frozen when testing variants. Use the same explicit filesystem paths in both files, including the runtime-only CA path. `include_workdir: false` plus explicit `/sandbox` avoids a comparison dependent on unknown working-directory expansion. Do not give the boundary `/` or broad binary globs just to make the solver pass.

**Solver status: NOT RUN.** `command -v openshell-prover` returned no path. No prover was acquired. For a later approved, already available prover, run:

```sh
openshell-prover check candidate-effective.yaml \
  --boundary owner-boundary.yaml --output json
```

Require `within_boundary` and coverage of filesystem, network L4, REST, process and Landlock. Exported effective policy must include any actual provider contributions and saved enrichment; supplement the inventory for runtime-only grants. A solver pass does not prove image layout, kernel enforcement, request-body model identity, storage isolation, or task authorization. [Prover scope](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/policies/prover.mdx).

| Deliberate variant | Static assessment / required later solver result |
|---|---|
| Add a public host/port with the same Python binary | Exceeds owner maximum; require a counterexample and rejection. |
| Add a second private model/service IP and its `/32` | Exceeds the exact endpoint maximum; require a counterexample and rejection. Documentation-address fixtures must not contact any service. |
| Change the listed immutable Hermes runtime path from read-only to read-write | Exceeds the filesystem maximum at the same exact path; require rejection. |
| Permit `DELETE /v1/models` or expand the model POST rule to `/v1/**` | Exceeds allowed REST methods/paths; require rejection. |
| Add a new writable path, such as `/home/operator` | Reject in the manual inventory. The documented prover can return `unsupported` for different path sets; that is a failure, not permission. |
| Set REST enforcement to audit, weaken Landlock, or use GraphQL/MCP | Reject. Audit/unsupported protocol checks cannot count as a passed REST proof; Landlock weakening violates the maximum. |

No negative candidate was executed, and no solver result is represented as observed.

## Persistence and control contract

For the fresh synthetic worker, propose `HOME=/sandbox/bot`, `HERMES_HOME=/sandbox/bot/hermes`, and terminal `cwd=/sandbox/bot/work`. Podman uses `/sandbox` as its workspace; placing all durable bot bytes there avoids an additional external volume and keeps the policy explicit. This is a **path relocation for a new synthetic identity**, not copying or moving the existing Researcher home.

Persist config/SOUL, memory, `state.db`, the run-idempotency database, transcripts, todo/session state and task files in that admitted tree. Inventory actual filenames from the exact composed source/image before starting. Keep the source/venv under the immutable `/opt/hermes/...` prefix. Temporary files under `/tmp` are expendable. Browser state, project databases and external effects are absent from this pilot.

The canonical main command should be the pinned foreground Hermes gateway launcher, using its venv interpreter with `-B -I`; systemd remains an outer-host concern. One gateway process owns one Hermes home. Its API remains sandbox-local loopback at 8642, reached through a loopback-bound OpenShell forward. No gateway-admin token, Podman socket, human auth profile or actual Radhouse controller key enters the workload. A later trial needs a newly generated synthetic Hermes API control token; none was created here.

OpenShell's `sandbox_stop_start_preserves_workspace` test verifies a workspace sentinel and a second canonical-process launch. It does not verify this Hermes relocation, WAL consistency or installed package/native-library compatibility. Stop/start keeps storage and resource associations but launches a **new process generation**. Retain stable synthetic bot/sandbox identity while recording generation changes; reconcile interrupted runs without resubmission. Snapshot SQLite only after a confirmed graceful stop, with WAL/SHM and the rest of the state inventory treated consistently. A retained volume is not a qualified backup/restore. [Lifecycle documentation](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/sandboxes/overview.mdx), [shipped lifecycle test](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/sandbox_lifecycle.rs), [local qualification](../../private-installation-record).

Radhouse's bot routing, attempt/run mapping, durable guidance, uncertain-effect receipts and Buzz mediation remain outside OpenShell. An OpenShell restart is not authority to retry a Hermes task. The first pilot deliberately uses only synthetic files and manual local control, so it can test this seam without publishing artifacts or changing the delivery path. [Hermes adapter](../src/radhouse/integrations/hermes.py), [runtime contract](integrations/hermes.md).

## Smallest later pilot and stopping rules

All steps below are a proposed future procedure, **not actions performed or authorized by this review**. Keep the entire runtime trial to one three-hour session; stop during preparation if it needs a security exception or unbounded packaging work.

1. Record an already admitted disposable outer VM's exact identity, resource headroom and Linux runtime probes: Landlock ABI 3+, seccomp/task-memory facilities, cgroups v2, and supported Podman/socket behavior. Kernel version alone is insufficient. Use an explicit Podman driver, loopback-only management, telemetry off, manual proposals, advisor off, no global policy/provider/GPU/driver JSON. Missing facilities are a stop, not a reason to weaken controls. [Support matrix](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/about/support-matrix.mdx), [telemetry control](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/observability/telemetry.mdx).
2. Prepare one immutable Linux x86-64 image from the exact six-layer Hermes and interpreter/dependency catalogue; record image digest, executable/link inventory and launch/config digests. Preserve the Researcher binding/budgets while explicitly relocating only the fresh synthetic home/work paths. Reject missing native dependencies rather than installing tools inside the workload or substituting a generic agent image. No original guest-identity guard is bypassed.
3. Check the complete effective candidate and deliberate variants against the independently reviewed maximum. With an approved prover available, only its documented pass qualifies the modeled portion. Verify applicable filesystem paths in the image; `hard_requirement` can still skip individual absent paths. Missing expected runtime/state paths are a stop.
4. Create one retained synthetic worker with the reviewed image/policy and foreground Hermes gateway; no `--no-keep`. Establish a local forward with a fresh synthetic control token. Verify authenticated capabilities, durable run store and fixed provider/model attribution. No actual Buzz channel, private repository or production controller routing is attached.
5. Supply two small synthetic text files with one deliberate contradiction. Ask for a cited comparison using the existing local file loop. Send one correction at a natural checkpoint if the selected runtime advertises the durable guidance capability; otherwise use an ordinary contextual follow-up and record that distinction. Keep one active run and the current two-turn/four-request profile. Do not expand budgets to rescue the task.
6. Record harmless denial probes: unadmitted destination, forbidden model API path/method, immutable runtime write and nonexistent other-bot path. Never address real management services or send credentials/private content. Confirm denials and unchanged effective policy; leave all proposed expansions pending or reject them.
7. Write a synthetic memory/session/file marker, stop the worker, verify access is unavailable, start it, and check all declared state plus SQLite integrity and generation change. Poll/reconcile the old run; do not automatically replay it. Verify the same fixed binding and policy after restart.

**Pass for this one-worker feasibility screen:** useful supplied-evidence task completes with accurate file references and correction/follow-up; every denied probe remains denied; declared state survives without corruption; no duplicate task execution; model/binary/policy attribution matches; no scope expansion. Provisional UX gate: at most 20% added end-to-end time against one matched direct-Hermes control task, with no unexplained steering/control delay above five seconds. Record model wait separately. This is a screen, not another model benchmark.

**Stop:** any false allow, credential import/leak, unexpected writable state outside `/sandbox`/declared temporary paths, nondurable store, missing composed source, need for privileged mode/socket/host bind/custom driver, a new service grant beyond the one selected model binding, or exhaustion of the three-hour session. A failed task does not justify automatic fallback or permission expansion.

Only after this screen passes should a second **separate outer VM** be admitted for the original two-worker concurrency test: A stop/restart and cancellation must leave B usable. Two Podman sandboxes in one VM would test process concurrency but would not qualify separate-kernel bot isolation. No fleet throughput or production adapter conclusion follows from the one-worker result.

## Exact next permissions and password-free work

**No new permission or password was needed for this review and these documentation artifacts.** The current authorized source/documentation work is complete. No bot setup or privileged action is pending in this session.

A runtime trial would require a separate, explicit authorization covering these concrete items:

| Future action | Exact authority needed | Password-free condition |
|---|---|---|
| Use a trial host | One named disposable VM, quotas/disk limits and its isolation/network placement; new synthetic bot identity. Do not repurpose the existing Researcher/Builder guests. | An already prepared, operator-admitted VM is available through an existing approved access path. No such availability was verified here. |
| Prepare/run OpenShell and image | Acquisition/install/start of pinned OpenShell v0.1.2, supported rootless Podman, immutable image build/import, and one retained sandbox; scoped local storage and loopback forward. Include a standalone prover only if acquisition is separately admitted. | All required unprivileged tooling and kernel/subordinate-ID/socket setup are already present. If administrator setup is needed, pause for the operator; do not retrieve, prompt through tools for, or enter a password. |
| Permit model traffic | One exact previously selected model endpoint, port and `/32`, admitted **for the new trial VM/worker**, with no other LAN/public egress or fallback. Exact real values stay in the private change record. | Existing authorized non-secret model access works without new credentials. If authentication is required, stop; credential setup is a separate later approval. |
| Protect trial control | Generate one disposable synthetic Hermes control token for local trial requests, kept outside logs/repo; do not reuse production keys. | It needs no elevated host privilege or human secret. It is nevertheless outside today's no-credential-setup scope. |

If no prepared host exists, the appropriate next move is a **read-only host/resource preflight under separately authorized access**, not a deployment attempt. Documentation preparation cannot promise a password-free install. Existing operator approval for CWB or a different bot does not admit this new worker, mount, endpoint or image.

## Evidence and residual uncertainty

The [review evidence ledger](2026-09-30-nvidia-openshell-policy-review-evidence.json) records accessed source hashes, the static decision, unavailable prover, and unchanged repository baseline. Official links above are immutable v0.1.2 sources accessed from the saved September 30 snapshot. No private address or credential appears in the policy example.

High confidence: concrete Researcher/Builder profile differences; mandatory workload syscall conflict; policy replacement/addition/enrichment semantics; native model ownership; process-generation restart; the absence of a local prover. Unqualified: exact deployed profile freshness, image composition/native imports, actual filesystem layout, the trial host's kernel/runtime/availability, Hermes path relocation, real API request compatibility and runtime denial/persistence behavior. Full Reviewer/browser compatibility is not evaluated. These are admission gates, not invitations to spend days tuning around a failed fit.

The next decision is therefore specific: **admit one prepared disposable host and the scoped synthetic runtime trial, or park direct integration and retain the effective-policy review method in the existing VM system.** Builder migration, credential confinement and two-worker scaling remain later decisions.
