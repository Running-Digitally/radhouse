# Hermes runtime profile

Hermes is Radhouse's first agent runtime. Radhouse owns the authorized task,
current grants, budgets, dispatch and operation identities, and released outcome. Hermes owns
agent execution inside one persistent bot VM. The adapter between them must not
turn runtime messages into authoritative permission or publication decisions.

**Current source pin (reviewed 2026-10-25):** Hermes Agent `v0.21.6`, commit
`818c13be1dc4fd28987e1e881a9408224afd4535`, with the exact composition in
[`source-lock.json`](../../runtime/hermes/source-lock.json), the base overlay
and native integration overlay. The earlier `0.21.1` / `2237be3` candidate is
historical. Source pins are not a new installed-runtime attestation or a general
compatibility promise. Review upstream license/release notes when changing them.

The current chat application uses `HermesRunsClient` directly. Controller/task
routing discussed below describes the retained earlier integration, not a fleet
enabled by `radhouse.chat`. See the [continuity gap check](../research/hermes-continuity-gap-check.md)
for active code and native capabilities to reuse.

The first transport candidate is Hermes's HTTP Runs API. One gateway owns one
Hermes home. Separate sessions may overlap when their resource claims do not
conflict; Radhouse does not impose a blanket one-task-per-bot rule.

The controller's implemented runtime router selects that gateway from the
task's durable bot ID for capability discovery, start/attach, result polling,
and exact-run stop. A missing bot route becomes a bounded unavailable-runtime
state. Provider names, model names, session text, or a returned run ID cannot
select another bot's gateway.

Task admission also compares the requested binding with the selected bot's
durable provider assignment. An operator cannot move a task to another provider
by changing an API request; changing that assignment remains an administrator
configuration operation.

## Bot guest boundary

Run Hermes as a dedicated unprivileged user with no `sudo`, Docker socket/group,
hypervisor credentials, management filesystem, or infrastructure executor
credentials. Keep three concerns separate:

- an operator-owned, immutable runtime tree such as `/opt/hermes/<commit>/`;
- the bot-owned Hermes state below `/var/lib/radhouse-bot/hermes/`; and
- bot workspaces below `/var/lib/radhouse-bot/work/`.

Use an isolated browser profile created for the bot. Never attach a personal
browser profile. Inject only the selected provider credential and a scoped
controller credential at launch; neither credential expands the bot's service
or network grants.

Hermes and Radhouse keep separate Python environments and locks. The paired
v0.21.6 integration uses its separately qualified Python 3.14 environment, as
recorded in the [current application baseline](../../README.md). The historical
candidate's Python 3.12 target must not be used to infer current compatibility.

## Provider following

A bot assigned to a fixed provider binding such as `example-provider-chat` follows the model
currently served behind that binding. An operator can change the provider's backing
model using the provider's own documented commands. On the next admission or capability
refresh, Radhouse records the actual served model and continues with the same
bot identity, workspace, task records, and provider binding.

The change must not select a different provider, spend a new task budget merely
because the backing model changed, or silently route helper calls elsewhere.
Before work proceeds, recheck the context, tool, structured-output, and vision
capabilities required by that task. An unavailable or incompatible model puts
the task into a visible waiting state. Operator-owned model-switch commands and
installation-specific endpoints stay outside the public configuration.

## Recovery and maintenance

Live guidance requires the optional version-1 durable receipt capability at
`features.runs_steering_receipts`: ordinary post-tool checkpoints and zero extra
model calls. The [operator design](../operator-buzz-completion.md#durable-guidance-contract-retained)
owns the exact wire contract and acceptance. An accepted update is queued until
a later natural model response confirms it was included. Short tools-disabled
work finishes normally; a later message becomes contextual follow-up work.
The controller retains exact guidance/run correlation and reconciles outcomes
through GET, including after task completion, without resending the instruction.

Tool-using assignments may also require the version-1 durable
`features.runs_allowed_tools` capability with `mode=exact_subset_of_profile`.
Radhouse binds a nonempty, duplicate-free list to the durable dispatch request;
Hermes may only narrow its configured profile and must preserve the list across
replay and restart. Prompt wording is not the enforcement boundary. Runs without
an exact restriction retain their existing profile, while tools-disabled runs
continue to advertise no tools.

Persist Radhouse task, attempt, dispatch, and operation identities independently
of Hermes session retention. Reattach with the original attempt key after reconnect. A
missing runtime event or expired runtime deduplication record does not authorize
another external effect; reconcile the target's durable receipt first.

The weekly OS restart path gives advance notice, asks active work to checkpoint,
stops new admission, drains for a bounded interval, and stops the gateway. At the
security deadline the restart proceeds even when a bot is unready. After boot,
Radhouse revalidates grants, provider capabilities, and uncertain effects before
resuming work.

## Qualification gate

Before private or useful pilot work, prove all of the following with synthetic
content:

- pinned install/import and listener/caller restrictions;
- durable session/run mapping and idempotent start or attach;
- independent overlapping sessions and conflicting-resource admission;
- cancellation that does not stop a sibling assignment;
- gateway, controller, and guest restart recovery;
- actual model attribution before and after a provider-binding change;
- no fallback when required capabilities disappear;
- no replay when an external effect remains uncertain; and
- consistent recovery of the local Hermes state and bot workspace.

Browser and tool integrations receive their own grants and tests. Passing the
offline [VS0 proof](../vs0-demo.md) does not satisfy this gate.
