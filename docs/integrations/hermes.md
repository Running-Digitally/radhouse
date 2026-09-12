# Hermes runtime profile

Hermes is Radhouse's first agent runtime. Radhouse owns the authorized task,
current grants, budgets, operation identities, and released outcome. Hermes owns
agent execution inside one persistent bot VM. The adapter between them must not
turn runtime messages into authoritative permission or publication decisions.

**Qualification candidate:** Hermes Agent `v2026.9.7` / `0.21.1`, source commit
`2237be355906fbe6065ce1815711eee52b2d646e`. This pin makes the first integration
repeatable; it is not a general compatibility promise. Review its upstream
license and release notes when the pin changes.

The first transport candidate is Hermes's HTTP Runs API. One gateway owns one
Hermes home. Separate sessions may overlap when their resource claims do not
conflict; Radhouse does not impose a blanket one-task-per-bot rule.

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

Hermes and the Radhouse controller keep separate Python environments and locks.
The candidate runtime accepts Python `>=3.11,<3.14`; Python 3.12 is the initial
guest target. The controller's Python version does not change that requirement.

## Provider following

A bot assigned to a fixed provider binding such as `nemo-chat` follows the model
currently served behind that binding. An operator can change Nemo's backing
model using Nemo's own documented commands. On the next admission or capability
refresh, Radhouse records the actual served model and continues with the same
bot identity, workspace, task records, and provider binding.

The change must not select a different provider, spend a new task budget merely
because the backing model changed, or silently route helper calls elsewhere.
Before work proceeds, recheck the context, tool, structured-output, and vision
capabilities required by that task. An unavailable or incompatible model puts
the task into a visible waiting state. Operator-owned model-switch commands and
installation-specific endpoints stay outside the public configuration.

## Recovery and maintenance

Persist Radhouse task, attempt, and operation identities independently of Hermes
session retention. Reattach with the original attempt key after reconnect. A
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
