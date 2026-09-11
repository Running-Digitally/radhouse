# Make boundaries understandable

Status: V1 decisions for boundaries, starting work, messaging, access scopes,
continuing after a grant and the combined operator journey are accepted.
Updated: 2026-09-10. Implementation and usability qualification remain pending.

People should understand where work happens, who can see it, and what a bot can
access without learning infrastructure terminology. These are separate facts;
one reassuring lock icon cannot communicate all three.

## One small context card

Show this card when starting work and keep a compact version visible in its
conversation, files, and results. Expand details on demand.

| Example field | What an operator sees |
| --- | --- |
| Working in | **Project Cedar** |
| Visible to | **You and 2 project members** — view names |
| Working with | **Mira · Researcher**, **Rowan · Reviewer** |
| Available information | **Cedar project files and the 3 files you selected** — inspect full bot access |
| Internet | **Restricted access** — see what is allowed |
| Review | **Private review off** — security events still monitored |

These are synthetic examples. Derive labels from current effective grants and
audiences on the server. The selected task inputs are not the bot's complete
access: the expanded view must disclose other granted projects and retained
information when applicable. Do not describe a widely exposed bot as limited
to the three files just selected.

Use plain labels: **Only you**, **Project members**, **Shared with…**, and
**Supervised — these people can review…**. Show named recipients and the scope
of any supervised review. Explain the infrastructure administrator's underlying
access separately; “Only you” describes application visibility, not protection
from the machine owner. Use text and accessible icons, never color alone.

## Starting a task — accepted for V1

Use **Send starts ordinary work in the visible context**. Opening an
assigned bot or project supplies the eligible context; the work home offers
permitted choices where one is missing. Before sending task content to a bot
or inference route, show the selected bot, working context and result audience.
Keep these visible above the composer, with the bot's wider access and retained
context available to inspect. Do not broadcast a private request to candidate
bots to discover which one should receive it.

For example, an operator opens their Researcher in private My Work, sees that
context, and sends: “Compare these three reports and prepare a two-page brief.”
If the necessary inputs and existing authority are present, admit the task and
show progress in that conversation. Sending is the deliberate Start action;
there is no additional confirmation screen for the same request.

If a required choice is missing, ask for that choice. If the work needs a new
grant or a wider audience, explain the consequence and use the accepted access
or publication flow before proceeding with the affected step. Current scope is
checked at admission; stale context cannot silently select different recipients,
broader permissions or another provider. Unrelated admitted tasks may continue
while one task waits, within the accepted concurrency and bot-wide hold policies.

| Interaction choice | Tradeoff |
| --- | --- |
| Send starts work in the visible context — accepted | Fast everyday use; ask only for missing information or consequential changes. Known context must be obvious before submission. |
| Review a brief before every new task — not selected | Always show an editable summary and a separate Start action. More opportunity to catch misunderstandings, with an extra step even for clear requests. |

Both choices retain visible context, current authorization and reviewed sharing.
This is about starting an ordinary task; scheduled standing assignments retain
their separate configuration and authority contract. Qualification should test
an unfamiliar operator, a stale or changed audience, missing input, unavailable
access and a request made while the bot already has other work. The interaction
direction is accepted; implementation and usability evidence remain to deliver.

## Messaging a busy bot — accepted for V1

Use natural conversation with a visible task target. In a task conversation,
follow-up instructions normally update that task. Clearly separate work creates
its own task within the visible authorized context. Status questions inspect
existing work. A bot-level conversation with several plausible targets asks a
short clarification instead of silently choosing the latest task.

| Example message | Accepted interaction; runtime behavior still to qualify |
| --- | --- |
| “Focus more on Canada” in the open comparison task | Record a revision to that task and deliver it through the qualified steering path |
| “Separately, review this pull request” | Admit a new task if context, inputs and permissions are sufficient; identify the new task in the acknowledgment |
| “Any progress on the comparison?” | Report current evidence for that task without creating a new assignment |
| “Stop that one” when several tasks are plausible | Ask which task; keep explicit task-scoped Pause and Cancel controls available |

Keep a compact task label beside the composer and label acknowledgments as a
task update or new task. Scope changes retain the accepted admission and sharing
checks. A new task does not inherit an entire old conversation, private inputs
or expanded permissions simply because it was requested in that conversation.
Model interpretation cannot override the server-bound audience, grants or budgets.

Distinguish an instruction being received from its being applied at an execution
checkpoint. An update must not secretly restart a task, reset its budget, repeat
an external effect or change priority without a human instruction. Changes that
conflict with pending or completed effects need reconciliation before the affected
work continues. In-progress external actions may complete after an interruption
request; report that state honestly. A task-level stop must not cancel unrelated
work. Explicit bot-wide actions and the accepted grant-withdrawal/maintenance
policies retain their wider scope.

| Interaction choice | Tradeoff |
| --- | --- |
| Natural conversation with visible task context — accepted | Interpret clear instructions in their displayed task; clarify ambiguous targets or materially different intent |
| Explicit Update task / New task choice — not selected | Require the operator to select an instruction mode before submitting work, giving more direct routing control with an extra interaction |

Both retain bounded multitasking, human priority/cancellation, current permission
checks and the accepted recovery policy. Qualify steering, concurrent results,
ambiguous targets, stale task selection, canceled tasks and instruction delivery
across reconnects. Preserve finished/canceled execution history; clearly requested
new work can become a separately identified task, while an ambiguous follow-up
needs clarification. A message cannot silently resume a canceled run. This
interaction direction is accepted; implementation remains to qualify.

## Requesting additional access — both scopes accepted for V1

A blocked task should explain the missing operation in plain language and offer
to narrow the task or prepare an access request. The operator reviews the request
before submitting it to an authorized administrator. Include the bot, task,
requested resource/operations, a minimal reason, duration and intended use.
Do not attach the private conversation or disclose undiscoverable resource names.
The request's own audience and content must be visible before submission.

Offer **both task-bound access with an expiry and reusable bot access for a
limited period**. Choose according to the request's purpose and context; there
is no universal default between these scopes. The operator can propose a scope,
and the authorized administrator makes the explicit grant decision with resource,
operations and duration visible. A bot's recommendation cannot select or expand
its own permission. Available choices must reflect the access path's enforcement
capabilities.

For example, one repository analysis may warrant a task-bound read grant. A
Researcher assigned repeated work on that repository may need the same reads
across eligible tasks for an approved period. Both are supported V1 choices.

| Accepted request scope | Tradeoff |
| --- | --- |
| This task, with an expiry | Ends at task completion/cancellation or approved expiry, whichever comes first; subsequent tasks do not inherit the grant |
| This bot, for a limited period | Reuse the approved operations/resources across eligible tasks until expiry; fewer repeated requests but broader continuing access |

This choice concerns new access requested by a blocked task. Existing standing
grants remain subject to their own accepted policy. A request is not a grant,
and service-grant approval does not substitute for a content owner's required
release decision. New access also does not remove a human pause, cancellation
or grant-withdrawal hold. Current task admission and recovery checks still apply.

Only show a task-bound guarantee where the qualified access path can enforce it.
A direct upstream token or shared authenticated browser session may be usable
outside the requesting task. Preserve the advanced mode's different guarantees;
do not present an unenforceable task-only label. Restrict or queue unsupported
paths, or require an explicitly reviewed alternative with its limits disclosed.
Expiry blocks future access and cannot erase previously read files or memories.
Task-bound service calls do not isolate tasks sharing the bot's retained context.

Exact lifetimes, renewal, termination/expiry races and pending-effect handling
remain program-design work. The accepted bot-wide hold after human grant
withdrawal is unchanged. Verify expiry, wrong-task use, scope changes and lack
of authority at both request and execution time. Both scopes are accepted;
concrete enforcement and usability remain to qualify.

## Continuing after access is granted — accepted for V1

Automatically continue the original task when its missing access
becomes effective and all remaining checks pass. The operator already requested
that work; receiving the needed grant need not require another Start/Resume
action. Show the grant result and the actual continuation state in the task.

Recheck that the task still awaits this access, the approved resource/operations
cover the pending step, the task's current scope/audience and budgets permit it,
and the runtime/provider and any pending effects allow safe continuation. A
broader reusable grant does not expand the original task's instructions. A grant
decision is not evidence that its enforcement is active; wait for that evidence.

An explicit human pause, cancellation, grant-withdrawal hold, manually stopped
bot or another unresolved approval still prevents continuation. The new grant
cannot authorize a different outcome, bypass reviewed publication or revive
terminal work. If the task or its requested operation changed while waiting,
reconcile the change instead of blindly applying the earlier request.

| Continuation choice | Tradeoff |
| --- | --- |
| Continue automatically when ready — accepted | Resume the still-requested work once effective access and current checks allow it; report progress or the remaining blocker |
| Operator chooses Resume — not selected | Notify the operator that access is ready, then wait for an explicit Resume even when other checks pass |

Both choices preserve the accepted recovery, cancellation, permission and
publication boundaries. Test delayed grants, stale requests, partial approvals,
expiry, duplicate approval events, task changes and explicit holds. This
interaction direction is accepted; implementation remains to qualify.

## One complete operator journey — accepted for V1

This walkthrough connects the accepted decisions. It introduces no new access,
publication or automation policy.

1. **Start in a visible context.** An operator opens an assigned Researcher in
   private My Work, selects permitted source material and sends a clear brief.
   The task starts within current authority; context and audience stay visible.
2. **Resolve missing access.** The bot explains a blocked operation and prepares
   a minimal request. The operator reviews it. An authorized administrator chooses
   task-bound or time-limited reusable access. Once effective, the original task
   continues if the remaining checks pass; explicit holds remain in force.
3. **Steer and follow work.** A message such as “Focus more on Canada” updates the
   displayed task. Clearly separate work gets a distinct task; ambiguous targets
   get clarification. The interface distinguishes received guidance from applied
   guidance and shows progress or the real reason for waiting.
4. **Review the result privately.** The operator finds the cited report alongside
   the task. Completion does not expand its audience. Other admitted work may
   continue, and the bot retains its identity and workspace.
5. **Share a selected result deliberately.** The operator chooses the report or
   selected attachments and an eligible project/audience. The release view shows
   the exact content version and named recipients, including recipient-visible
   metadata and references. Apply existing content-release authority checks.
   Publish the approved artifact through the trusted sharing path; keep private
   conversations, other files, memory and credentials outside that release.

For example, sharing the comparison with Project Cedar shares the reviewed
report, not the private My Work conversation. Sharing does not create a new
service grant. An administrator's infrastructure role is not automatic authority
to publish another person's private material. If the content or audience changes
after review, obtain the required new release decision; do not silently replace
the shared version. Revoking later access cannot recall delivered copies.

The combined journey is accepted at the design level. Proceed to the concrete
implementation design and then review the first implementation slice. Acceptance
does not establish that the experience is intuitive in use: the unfamiliar-user
pilot and boundary checks below remain required. Exact interfaces, state
transitions and supported runtime behavior still need review and qualification.

## Explain boundaries at the moment they matter

- **Starting work:** show context and audience before sending the brief to an
  inference route or bot. Keep recurring actions short when neither changed.
- **Adding a file:** show its destination and audience. Bringing private material
  into shared work needs the required content-and-audience review.
- **Sharing a result:** preview the exact version and named audience. Changed
  content or recipients invalidate the earlier approval. Do not share private
  history as an attachment to the result.
- **Moving work between projects:** treat any new audience as a publication
  decision. Offer to share an approved copy; dragging a card must not silently
  transfer its conversation, files, or a bot's permissions.
- **Requesting access:** say what is missing, why the task needs it, and who can
  decide. The operator can narrow the task or send an access request without
  needing to interpret a token scope or firewall rule. Do not reveal the names
  of resources the operator has no right to discover.
- **Reusing a bot across projects:** explain that it can retain what it has
  learned. For separate confidentiality boundaries, recommend a new bot from
  the same role template. A project switch does not erase memory or create
  isolation. Revocation blocks future access but cannot promise forgetting.

Task admission and publication must recheck the current audience, grants, and
content revision. A stale browser tab or a renamed project cannot bypass them.
Task labels, alerts, search suggestions, and filenames follow the same audience
rules as content. Private task summaries must not leak into global dashboards.

## Keep everyday use calm

Ask for decisions when access, audience, or consequential authority changes.
Use inline explanations for ordinary blocked actions. Reserve interrupting
warnings for an actual boundary change or material incident. Put fleet-wide
security findings and update plans in the administrator's view; operators see
their affected work and maintenance availability, and viewers remain read-only.

## Evidence before calling the experience intuitive

With unfamiliar non-technical participants, verify that they can start work,
identify its audience, explain the bot's wider access, share a selected result,
and request missing access without coaching. They should distinguish private
content review from security-event monitoring and understand the retained-data
warning when reusing a bot. Test keyboard/screen-reader use and text labels.

Pair usability checks with server-side denial tests for stale approvals,
unauthorized names/search, cross-project moves, and grant changes. A clear screen
is useful only when the underlying boundary holds.

See the [work model](work-model.md), [security supervisor](security-supervisor.md),
and [naming preferences](naming-preferences.md) for the related contracts.
