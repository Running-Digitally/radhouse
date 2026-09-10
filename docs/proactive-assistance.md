# Proactive assistance

Status: accepted for version 1.0. Combine Guardian Angel and Cognitive Amplifier
behaviors in scoped, human-enabled standing assignments. Prepared briefings are
the default. Optional bot mail is the first concrete intake use case; existing
authorized Radhouse work/status signals can use the same pattern. Implementation,
adapter support, notification defaults, and evaluation still require qualification.
Updated: 2026-09-10. Nothing is deployed.

## Notice what matters and reduce the effort to act

| Behavior | Responsibility | Useful result |
| --- | --- | --- |
| Guardian Angel | Notice relevant changes, approaching deadlines, emerging risks, missing information, and opportunities in authorized sources | Explain why attention may be warranted, with evidence, timing, and uncertainty |
| Cognitive Amplifier | Relate the finding to the person's stated purpose, connect permitted context, compare options, and prepare useful work | A concise briefing, local draft, checklist, or proposed task brief that makes the next decision easier |

These are complementary behaviors an existing bot can perform within its grants.
They do not require two new bots, VMs, or services. A role name conveys no extra
access or protective guarantee. Avoid invented urgency, overconfident predictions,
and warnings that offer no explanation or useful next step.

The product interpretation draws on Raj Reddy's distinction between agents that
amplify human capability and agents that notice consequential events, including
his emphasis on enduring, personal, nonintrusive assistance. The bounded behavior
and authority rules here are Radhouse design choices.
[Reddy's CMU-hosted presentation](https://www.andrew.cmu.edu/user/ko/downloads/RR-AI-CMUQ.pdf).

## A standing assignment with an obvious boundary

A person enables an assignment for an eligible bot. Setup provides a reviewed
starter with understandable defaults and a short preview of:

- Its purpose and the concerns or opportunities the person wants it to notice.
- The exact permitted sources and project context, with coverage gaps visible.
- What analysis and local preparation it may perform, and its resource limits.
- Who receives its findings, through which configured channels, and when.
- How to adjust preferences, pause the assignment, or request additional access.

Existing administrator grants constrain every choice. An operator may configure
an assignment for an assigned bot within those grants; selecting a source is
not a grant to read it. The bot cannot enable or expand its own assignment,
change recipients, raise its budget, or connect another source. Explain the bot's
full persistent access separately from the selected inputs to this assignment.

Represent the standing assignment as reusable policy/context linked to finite,
bounded task occurrences and runs. New mail or supported work events may wake
an enabled assignment; a configured schedule can also check its sources. The
controller admits each occurrence under current scope and limits. Mere receipt
of a message does not authorize its sender to create arbitrary work.

Bot VMs remain running by default. Waking an assignment here means admitting a
bounded task/run, not powering on a manually stopped VM. Such work waits or is
reported blocked according to its policy; an event cannot override a human stop.
This readiness default does not permit unrestricted background inference.

Mail is independently optional. Disabling it does not remove ordinary tasks or
permitted work-status briefings. Other source integrations require their own
qualified contracts; this feature does not connect a personal inbox or calendar.

## Default behavior: review, prepare, and approach the person

1. Review newly available authorized material and relevant permitted context.
2. Judge whether it changes a decision, creates a time constraint, reveals a
   concern, or offers a useful opportunity. Group related items and suppress noise.
3. Distinguish observed facts from interpretation. Link to accessible evidence,
   indicate freshness, and explain uncertainties or missing context.
4. Prepare useful local material within the assignment's preparation budget:
   a summary, comparison, draft reply, checklist, or proposed follow-up task brief.
5. Bring a concise, actionable briefing to the authorized person when warranted.
   If no action is useful, keep quiet or include the finding in the agreed digest.

An illustrative briefing could say:

> The workshop deadline moved to Thursday. This affects the draft you asked me
> to help prepare. I found the revised notice and prepared an outline and a
> clarification reply. The notice does not specify a timezone, so the cutoff
> needs confirmation.

The interface links the evidence and prepared material, and offers relevant
actions such as **Review draft**, **Start proposed task**, **Snooze**, or
**Dismiss**. Show only actions the person may take. A new task starts only after
the person reviews the brief, scope, and audience and the controller admits it.
Opening a draft or acknowledging a finding is not approval to execute it.
Bind approval to that proposal revision and recheck current grants before action;
materially changed scope or audience needs a new review.

Preparing within the standing assignment needs no approval for every message.
New follow-up objectives, broader research outside its scope, changes to grants,
publication to a wider audience, and other unadmitted effects still need human
authority. A prepared reply is a local artifact: version 1 remains receive-only
for bot email, and this feature does not write a draft into an upstream mailbox.
Existing authorized task execution and maintenance retain their own contracts.

## Respect the person's attention

| Level | Default treatment |
| --- | --- |
| Time-sensitive attention | Explain the consequential change, evidence, deadline, and recommended response; interrupt only as allowed by the human's notification/quiet-hours policy |
| Decision ready | Put a prepared recommendation in the person's needs-attention view and next appropriate digest |
| Useful context | Group related information into a digest or retain it with the assignment without interrupting |

Source text claiming urgency is evidence to evaluate, not a command to interrupt.
Do not use an uncalibrated model score as a delivery guarantee. Unclear timing
or uncertain importance should be disclosed. Show stale, delayed, or overdue
findings honestly; a queued background bot cannot promise real-time coverage.

Deduplicate findings across repeated messages and retries. A snoozed or dismissed
item should not repeatedly reappear without a material change or a requested
reminder. Expose simple feedback such as **Useful**, **Less like this**, and
**Watch for this**. Use explicit feedback to improve preferences within the
assignment; a broader watch request requires a visible scope check and any
missing administrator grant. Feedback never promotes trust or permissions.

Humans can pause assignments and control notification limits, digest timing,
quiet hours, and any permitted urgent exceptions. The bot cannot override these
because it believes a message is important. Routine briefing preferences cannot
disable independent security/maintenance evidence or mandated operational alerts.

## Privacy and authority at delivery

Keep findings, drafts, and supporting analysis in their original authorized
workspace. Default delivery is a private Radhouse needs-attention item. An
explicitly configured bot-chat destination may receive content only when its
current audience is authorized for that content. Recheck recipients and grants
at dispatch; a previously valid room or queued notification can become invalid.

Private material moving to a shared room/project still requires review of the
exact content and audience under the publication policy. Neither urgency nor a
standing assignment replaces that review. Notification titles, previews, and
links can disclose information too; use privacy-preserving notices where content
delivery is not appropriate. A link grants no access to its target.

An optional Chief of Staff may consolidate explicitly released summaries and
authorized project status. It does not automatically receive other bots' private
inboxes or findings. The security supervisor retains scoped security evidence,
optional private-review findings, and its separately authorized maintenance
responsibility. Guardian Angel behavior does not add automatic incident response,
quarantine, private-content inspection, or root access to either role.

## Deterministic controls around agent judgment

Reuse the existing controller, queue, grants, and scoped event records. Do not
introduce an unrestricted always-running agent loop or require a new event-bus
service merely to deliver this behavior.

- Authenticate intake through the configured adapter; normalize event identity,
  source revision, and receipt time. Message contents and sender display names
  cannot create authority. Treat links, attachments, and instructions as untrusted.
- Coalesce bursts and bound pending events, inference work, local preparation,
  notification volume, and storage. Follow existing background-resource priority
  and the operator-selected inference route; do not switch providers to catch up.
- Keep occurrence and delivery receipts outside worker-editable state. Recheck
  authorization before source reads, preparation, and notification dispatch.
  Receipt/acknowledgment ambiguity needs reconciliation, not blind repeated sends.
- Checkpoint progress and resume within the same admitted work after maintenance.
  Apply bounded retry/backoff; neither mail loops nor bot-to-bot notices may
  recursively create unbounded work. Respect stop, revocation, and pause controls.
- Show backlog, last successful review, reviewed-through source position, failed
  or throttled work, and delivery status. Where an adapter cannot establish
  coverage, report unknown. Silence is not proof that nothing important exists.
  Distinguish received, analyzed, and delivered material; a partial review or
  context-limit truncation cannot mark the entire source as reviewed.

No mailbox send, delete, forwarding-rule, authentication, or other service-write
authority follows from reading mail. Attachments, remote content, and verification
or recovery messages need explicit handling under the qualified mail contract.
[Account-security mail](mail-and-account-security.md) stays human-controlled by
default, with tested and explicitly approved verification/sign-in integrations
for named bot-owned accounts. Password resets and security-setting changes remain
human-controlled; triage cannot invoke them or obtain their secrets.

## Version 1 qualification

Use synthetic cases to demonstrate useful judgment and enforced boundaries:

- A genuine deadline change produces an evidence-linked, appropriately timed
  briefing and useful local preparation; an unsupported urgency claim is not
  treated as authority. A relevant opportunity can be surfaced without a threat.
- Noise, duplicate deliveries, feedback, quiet hours, and bursty mail do not
  create notification storms or repeated tasks. A material update can reopen an
  item with an explanation. Track useful findings and missed cases, not just volume.
- Spoofed senders, prompt injection, cross-bot cycles, and malformed attachments
  cannot expand scope, spend beyond limits, trigger sending, or change grants.
  Qualify actual tool/network paths for each supported profile combination;
  restrictive instructions alone are insufficient evidence.
- Revoked access, changed room membership, mixed-private-source summaries, and
  stale queued alerts cannot disclose unauthorized material. Chief of Staff and
  supervisor boundaries hold.
- Model outages, missed source events, depleted budgets, maintenance restarts,
  and uncertain delivery remain visible and recover without blind replay.
- A nontechnical operator understands why a briefing appeared, can inspect its
  evidence, review a prepared action, and adjust or stop the assignment.

Exact schemas, supported adapters, numerical budgets, retention, notification
defaults, and evaluation thresholds belong in the implementation design. The
accepted feature is proactive prepared assistance within a visible human-owned
assignment; qualification is required before claiming that it works reliably.
