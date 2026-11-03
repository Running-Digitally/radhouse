# Native Hermes and always-on assistance — 2 November 2026

Decision: reuse Hermes scheduling and execution. Radhouse owns the standing
responsibility, source permission, attention policy and authenticated delivery.
An always-on assistant maintains responsibilities across runs; a timer or a
push transport alone does not provide that behavior.

This research supports [proactive assistance](../proactive-assistance.md) and
the [qualification plan](../plans/2026-11-02-native-proactive-assistance.md).
It is engineering research, not evidence of production activation. Private
conversation archives, screenshots and operational configuration are excluded.

## Source authority

The repository pins Hermes v0.21.6, commit
`818c13be1dc4fd28987e1e881a9408224afd4535`. Findings below refer to that source,
not an assumption that today's website matches the deployed runtime.

| Capability | Native behavior at the pin | Radhouse implication |
| --- | --- | --- |
| Heartbeat | A session-bound prompt, interval, pause/resume and persisted state. Missed intervals coalesce; gateway recovery restores eligible session watches. | Reuse the native owner and recovery path. Do not create a second heartbeat poller. Persisted state alone does not prove a run or delivery. |
| Cron | Recurring and one-time jobs, fresh runs, scripts, cheap gates, monitoring, output history and delivery bookkeeping. | Use recurring jobs for standing responsibilities that do not require the interactive session. Keep cadence separate from permission. |
| Quiet completion | Autonomous silence markers suppress delivery. Failure evidence has a separate path. | Healthy silence, failure and missing coverage must remain distinguishable. Never require a status message after every check. |
| Tool scope | Per-job toolsets exist, but enabled MCP servers can be merged into the effective tools. Scheduling and messaging are disabled by default in cron agents. | A toolset name is not an exact Radhouse grant. Explicitly qualify the final tools and source access. |
| Context | Native cron loads memory and SOUL; working-directory context is conditional. Optional continuity and attachment to a session exist. | Fresh cron sessions are not necessarily free of personal context. Do not infer source isolation from a fresh session ID. |
| Jobs HTTP API | Creation forwards a subset of job fields. In particular, it does not forward per-job toolsets or script/no-agent fields at this pin. | Do not send unsupported fields and assume they took effect. Provision paused, read back the effective job, then activate only a qualified scope. |
| Messaging | The send-message helper is deliberately not registered as an ordinary model tool. The HTTP adapter's `send()` returns an unsupported-delivery failure. | Native cron cannot automatically push into the Radhouse HTTP conversation. A Radhouse delivery adapter is required. |
| Webhooks | Native authenticated routes, filters and coalescing are available. | External event text is evidence, not authority to change a mandate or add destinations. A new public webhook is unnecessary for the first pilot. |

Pinned sources:
[heartbeat](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/hermes_cli/heartbeat.py),
[gateway restoration](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/gateway/run_heartbeat_restore.py),
[cron scheduler](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/cron/scheduler.py),
[cron tool](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/tools/cronjob_tools.py),
[HTTP adapter](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/gateway/platforms/api_server.py),
[send helper](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/tools/send_message_tool.py),
[cron guide](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/website/docs/user-guide/features/cron.md),
[webhooks guide](https://github.com/NousResearch/hermes-agent/blob/818c13be1dc4fd28987e1e881a9408224afd4535/website/docs/user-guide/messaging/webhooks.md).

## UX evidence and resulting design

Microsoft's HAX guidelines emphasize communicating capabilities, showing
contextually relevant information, explaining behavior and supporting correction,
dismissal and global controls. For Radhouse, each intervention should show what
changed, its evidence, why it matters now and the smallest useful next action.
Pause and scope controls belong beside the responsibility, not only in a global
settings screen. [Microsoft Research, CHI 2019](https://www.microsoft.com/en-us/research/articles/guidelines-for-human-ai-interaction-eighteen-best-practices-for-human-centered-ai-design/)

A five-day field study with 15 developers and 229 interventions found that timing
and interruption mattered: post-commit engagement differed from interruptions
during editing. This small developer study motivates testing natural stopping
points; it does not establish a universal optimal cadence or notification quota.
[Kuo et al., IUI 2026](https://arxiv.org/abs/2601.10253)

A study of 23 pairs considering proactive voice assistants found a tension
between interruption and control over information use. Radhouse should make
standing permission understandable, and distinguish preparing a private
suggestion from committing to an action. This study does not justify continuous
access to every conversation or device. [Malkin et al., SOUPS 2022](https://www.usenix.org/conference/soups2022/presentation/malkin)

PAIR recommends understandable feedback and controls proportionate to the
consequences. Dismissal might mean bad timing, poor relevance or an incorrect
inference. Record those separately; a notification tap is not permission to
expand monitoring. [Google PAIR](https://pair.withgoogle.com/guidebook-v2/chapter/feedback-controls/)

Platform guidance favors timely, relevant, concise notifications and meaningful
actions. Radhouse should use a generic lock-screen preview, open the exact
authenticated item, group related changes and avoid repeated alerts for an
unchanged situation. User-controlled quiet hours and notification categories
remain independent of agent judgment. [Apple](https://developer.apple.com/design/human-interface-guidelines/notifications),
[Android](https://developer.android.com/design/ui/mobile/guides/home-screen/notifications)

These are design inputs. The pilot must measure usefulness, mistaken commitments,
corrections, repeated alerts, missed coverage and delivery failures. Engagement
alone is not a success metric.

## Community observations, not established guarantees

A community author describes a collect → triage → notify setup. The useful
pattern is a cheap evidence gate before model work. Their access choices are not
a recommended permission boundary for another installation.
[Author's setup](https://www.reddit.com/r/hermesagent/comments/1umc7pu/signal_triage_notify_my_personal_hermes_setup_to/)

The `hermes-proactive` project describes change detection, preparation, progress
work and coverage health as separate responsibilities. That is a useful
vocabulary. Its cadence and message caps are proposed policy, not validated
defaults; prompt rules do not create a security boundary.
[Project source](https://github.com/riozilla/hermes-proactive)

A community heartbeat plugin describes quiet hours and lightweight model checks,
but also broad tool access and unfinished controls in its README. The pinned
Hermes version already has a native heartbeat. Installing another scheduler
would add ownership and recovery questions without resolving Radhouse delivery.
[Plugin source](https://github.com/kaishi00/hermes-community-plugins/tree/main/heartbeat)

Reports of inconsistent cron behavior reinforce the need to distinguish “never
started,” “execution failed” and “delivery failed.” They are diagnostic leads,
not proof of a defect in this pin. Older claims that cron has no memory conflict
with the inspected constructor and should not be repeated as current guidance.
[Cron discussion](https://www.reddit.com/r/hermesagent/comments/1wq9gbw/cron_jobs_hit_or_miss_need_suggestions/),
[wake-up discussion](https://www.reddit.com/r/hermesagent/comments/1u7zayl/can_hermes_wake_up_and_message_me/)

## First responsibility

The selected personal pilot may propose commitments from recent Radhouse
conversation for the owner to confirm. An inferred commitment is a suggestion,
not an accepted obligation or authorization to act. Public repository changes
can supply synthetic integration scenarios without importing personal history.

The first scope excludes Library contents, browser sessions, other chats,
contacts and external actions. Use bounded recent text, cite the relevant
message, respect later corrections, and keep uncertainty visible. Confirmation
must state the resulting follow-up scope; rejection must prevent the same
evidence from immediately generating another suggestion. Follow-up authority
must not be inferred merely from delivery, reading or silence.

The full direction remains a Guardian Angel that notices and a Cognitive
Amplifier that prepares useful work within granted scope. Commitment discovery
is its first testable responsibility, not a replacement definition of the agent.


## Lessons from the first live qualification

Native scheduling, permission to inspect a source, conversational capability
knowledge and notification delivery are separate contracts. Installing a
background job does not teach the conversational agent that it exists. Supply
current capability facts from the application, preserve them across immutable
retries, and distinguish permission from successful coverage and handset receipt.
A successful proposal is also different from a scheduled reminder.

Provider formatting needs qualification with real bounded input. A strict JSON
contract can accept one outer Markdown fence without accepting prose, multiple
objects, extra authority fields or fabricated citations. Synthetic semantic
success did not establish timing on real conversation. Keep a cooperative
model budget inside an independent process deadline and retain explicit failure
status when either cannot produce valid evidence.

Always-on acceptance should record the whole chain: native tick, authorized
claim, real model execution, validated durable proposal, opted-in outbox, provider
acceptance, physical receipt and authenticated navigation. Test notifications
and any one-time quiet-hours exception should remain distinct from the recurring
attention policy. Preserve failed-run evidence, and disclose when qualification
has consumed the normal review budget instead of silently resetting it.
