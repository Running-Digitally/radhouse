# Bots, projects, and work

Status: layered work model and starters accepted for version 1.0.
Research reviewed: 2026-09-10.

The accepted direction connects the operator work home to useful work through
persistent bots, project context, finite tasks, opinionated starters, and an
optional Chief of Staff. Detailed interactions, template contents, permissions,
and runtime behavior still require design and qualification. Acceptance of the
model does not add deployed capabilities or prove security properties.

## Accepted direction

Use a simple work home with several entry points into one task brief. Keep
persistent bots, projects, and finite tasks distinct. Offer reusable templates
for bot roles, project setups, and repeatable tasks. Make a Chief of Staff an
optional coordinator with explicitly scoped information, rather than a required
gateway for all work.

## Patterns worth borrowing

These are recurring patterns across the products reviewed, not evidence of a
universal industry standard or an audit of their implementations.

| Source | Observed pattern | Radhouse adaptation |
| --- | --- | --- |
| [Hermes Bot Mode](https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode) | Named bots retain role, model, memory, skills, and conversations; Bot Mode presents underlying profiles as a roster. | Make a bot a recognizable, enduring teammate with a visible capability summary. Evaluate existing runtime features before duplicating them. |
| [Paperclip agents](https://docs.paperclip.ing/guides/org/agents/) and [projects](https://docs.paperclip.ing/guides/projects-workflow/projects/) | Agents, reporting lines, project workspaces, and tasks have separate views; creating a task inside a project carries that project context forward. | Preserve distinct objects and contextual entry points. A corporate hierarchy should be optional, not required onboarding. |
| [Paperclip company bundles](https://github.com/paperclipai/companies) | Reusable bundles package specialist agents and skills for research, engineering, and other domains. | Ship a small set of reviewed starter packs with visible contents and resource requirements; do not automatically instantiate large teams. |
| [Claude Cowork projects](https://support.claude.com/en/articles/14116274-organize-your-tasks-with-projects-in-claude-cowork) | Projects organize tasks with their own instructions, context, and project memory. | Keep durable project knowledge alongside the project so another authorized bot can continue the work. This organization alone does not establish VM isolation. |
| [CrewAI agents](https://docs.crewai.com/en/concepts/agents) and [tasks](https://docs.crewai.com/en/concepts/tasks) | An agent's role and purpose are distinct from a task's description, expected output, and dependencies. | Separate a reusable job description from this assignment's deliverable and completion criteria. This is a modeling pattern, not a proposed second runtime. |
| [Herdr](https://github.com/herdrdev/herdr) | Persistent terminal supervision, a combined roster across machines, and working/blocked/idle signals make ongoing work inspectable. | Make status and requests for human attention easy to find, while retaining technical inspection beneath the everyday work view. |

Two limits are particularly relevant. [Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/)
separate runtime state but do not sandbox filesystem access. Their cloning
and credential-sharing behaviors need deliberate qualification for Radhouse.
[OpenClaw's workspace documentation](https://docs.openclaw.ai/concepts/agent-workspace)
also distinguishes a working directory from an enforced sandbox. Neither a
role label nor a project folder replaces the accepted VM and service boundaries.

## The product objects

| Object | Meaning | Lifetime and ownership |
| --- | --- | --- |
| Bot role template | A reusable job description: responsibilities, working style, skills, expected outputs, and proposed capability requirements. | Versioned reusable configuration; no identity, secrets, private memory, or grants of its own. |
| Bot | A named worker created from a template and configured by an administrator. | Persists beyond tasks and projects, with its own identity, VM, tools, private workspace, memory, provider binding, and explicit grants. |
| Project | A body of work with its own people, eligible bots, shared workspace, instructions, decisions, and audience. | Persists across assignments; may represent an ongoing area or a finite deliverable. Shared content lives here rather than only in a bot's private memory. |
| Task | An outcome to deliver in a chosen context: the brief, assigned bots, inputs, limits, result, and review state. | Finite work that can complete independently of its bots. A project groups related tasks; a task can have bounded subtasks. |
| Run | One execution attempt, checkpoint continuation, or retry for a task. | Technical execution detail, visible when useful for progress or diagnosis rather than an onboarding concept. |

A Researcher template can produce several distinct Researcher bots. A bot can
participate in more than one project when the grants and information-sharing
boundary permit it. A project can use several bots without acquiring their
private histories. Changing a task's outcome does not redefine the bot's
standing purpose.

Keep long-term goals as optional project/task context initially. Requiring a
company, department, goal tree, team, project, bot, and workflow before a person
can start would undermine the accepted simple onboarding.

## The everyday flow

The work home shows current work, assigned bots, and needs-attention items,
alongside **Start a task**. Projects and bots remain accessible directly.

| Starting point | What is already known | Next step |
| --- | --- | --- |
| Home: Start a task | The operator's identity and eligible workspaces/bots. | Describe the outcome; choose or confirm the project, team, and deliverable. |
| Project: Start a task | The current project and its allowed context. | Describe the outcome; use or adjust its eligible suggested team. |
| Bot: Give work | The selected persistent bot. | Describe the outcome and choose a project or private work context it may use. |
| Starter task | The expected deliverable and a suggested sequence of steps. | Fill the few missing inputs and choose or confirm context and eligible bots. |

All entry points converge on one short brief:

```text
Outcome:   Compare three approaches and recommend one
Project:   Research study
Team:      Mira — Researcher; Rowan — Reviewer
Inputs:    Selected project sources
Result:    A comparison brief with evidence and limitations
Audience:  This project's named members
Limits:    Existing access; stated work budget

Start task
```

These are synthetic names. The normal path should prefill known choices and
ask only for missing or consequential information. Existing grants should be
summarized without presenting a full security configuration form for every task.
Requests for additional permissions remain separate, explicit decisions.

The project and audience must be visible before inputs are dispatched to bots.
For work without a chosen project, propose an explicitly private **My Work**
context, not an invisible global scratch area. It should not create a new VM,
add a bot, or copy other private histories. Whether operators may create further
private projects needs alignment with the final project-management permissions.

Suggestions are drafts. Candidate filtering uses the caller's permitted
registry/project metadata; private task text is not broadcast to the roster.
Semantic routing, if used, must have an explicitly selected and permitted
inference route. Manual selection remains available without that dependency.
This must preserve the accepted provider-selection contract.

Within the task, conversation, work status, files, result, and review stay
together. Finishing the task leaves the bots and project available for later
work. A completed task's proposed follow-up remains a proposal until authorized;
selecting a recipe does not enable a recurring schedule.

## Three kinds of starter

Templates should reduce choices while keeping the resulting setup inspectable.
They should not create a large set of running VMs as a side effect of selection.

### Bot roles

| Starter role | Default responsibility | Key boundary |
| --- | --- | --- |
| Researcher | Find evidence, compare explanations, cite sources, and state uncertainty. | Works with granted sources; does not publish private material to a wider audience on its own. |
| Analyst | Interpret supplied datasets, examine assumptions, and produce reproducible findings. | Data access and external services require their own grants. |
| Engineer | Implement and test a bounded repository change and prepare a pull request. | Scoped repository operations; merge and deployment remain human decisions. |
| Reviewer | Examine a specified artifact against stated criteria and explain defects or uncertainty. | Reviews only supplied/granted material; no automatic merge, broader supervision, or private-history access. |
| Chief of Staff | Clarify a person's requests, summarize permitted project progress, identify dependencies, and propose next actions. | Optional coordinator; no infrastructure, grant, cancellation, or priority-change authority. |

Offer a customizable generalist baseline as well. One bot can perform several
compatible duties; the platform need not provision a VM for every label. When
a task promises independent review, use a distinct eligible reviewer. A second
pass by the author should be labeled self-review.

### Project starters

| Starter | Initial structure | Suggested existing roles |
| --- | --- | --- |
| General project | Brief, sources, working files, decisions, results. | Generalist or an appropriate existing specialist. |
| Research study | Research question, source collection, evidence notes, comparison, reviewed brief. | Researcher and Reviewer; Analyst when useful. |
| Software project | Repository reference, acceptance criteria, design notes, changes, validation, review. | Engineer and Reviewer. |

Project templates suggest roles and structure. They do not silently add project
members, copy private bot memory, mount folders, or issue credentials. Prefer
reusing a suitable already-authorized bot; offer an administrator request when
new capacity or a new trust boundary is needed.

### Task starters

Start with a small set: **Research a question**, **Compare options**, **Analyze
these files**, **Review this work**, **Implement a change**, and **Summarize
progress**. Each declares a useful output, required inputs, a suggested role or
team, completion criteria, and any review step. People can edit the brief.

A starter pack can combine a project starter and suggested roles, such as
Researcher + Reviewer for a research setup. The administrator reviews which
bots already exist, which would be created, resource needs, and grant requests.
Installing the pack does not start work or enable schedules.

Ship reviewed built-in starters first. Each needs an identifier/version,
instructions, skill references, capability requests, example inputs/outputs,
and behavioral and permission checks. Template updates must show meaningful
changes; never silently copy live memory, tokens, or expanded permissions.
A general marketplace is not needed to prove version 1.0's starter experience.

## A Chief of Staff across projects

The useful default is a personal coordinator working from an explicitly
selected portfolio: project status, milestones, blockers, decisions needed,
and summaries released for that purpose. Metadata can itself be sensitive and
needs an audience and grant. The coordinator's private overview is not
automatically visible to every contributing project.

On request, it can answer what needs attention, prepare a briefing, draft task
briefs, and recommend an order of work. It may coordinate subtasks only inside
an already admitted assignment using eligible existing project bots. A standing
job title does not authorize ongoing autonomous work; regular briefs use the
accepted human-configured schedules.

Full project files or conversations are additional access, not implied by the
title. In version 1.0, requests for private information follow the accepted
human-reviewed sharing path; private-bot interrogation and automatic answers
remain deferred. The Chief of Staff is distinct from the security supervisor
and from human administrators.

One persistent VM with access to two projects can retain information from both
in files, history, memory, caches, or installed software. Choosing another
project in the UI or changing a prompt does not establish separation. Removing
a grant stops future access; it does not prove erasure of previously read data.

Recommended default: use distinct bot instances for projects that require
separate confidentiality boundaries. Reuse a bot across explicitly approved,
compatible projects only with clear disclosure of its combined information
scope. An optional Chief of Staff can span boundaries through selected released
summaries without receiving all underlying content. Its output still follows
the intended recipient's permissions.

Project knowledge, bot-private memory, and task execution history need distinct
storage and retrieval policies. Project-scoped retrieval improves organization,
but it is not proof that a previously exposed persistent bot has forgotten
another project. Graduating such a bot to broader internet access must account
for retained data, not just the currently selected folder.

## Acceptance examples before implementation is called usable

- An unfamiliar operator can start the same kind of task from Home, a project,
  or a bot without learning different submission systems.
- Completing a task leaves the bot intact and makes the deliverable findable
  in the project by another authorized participant.
- A template can request a capability but cannot grant it, copy secrets, or
  provision an unapproved bot. Required review cannot be skipped silently when
  no eligible reviewer is available.
- A bot with no membership/grant for another project cannot retrieve its files,
  task details, private history, or sensitive existence metadata through search,
  suggestions, direct URLs, or peer delegation.
- Cross-project coordinator output contains only information released to that
  coordinator and permitted for the output audience; test both metadata and
  raw-content denial cases.
- A same-bot, multi-project configuration is never described as a strong
  confidentiality boundary based only on profile names or retrieval filters.
- No role label enables background work, grants, merges, deployment, schedule
  changes, cancellation, or priority changes outside the accepted contracts.

## Related experience and remaining design

The layered model, reviewed role/project/task starters, and optional Chief of
Staff are accepted direction. The original goal-first versus agent-first choice
is superseded by contextual entry into one brief. Detailed project-management
permissions, template contents, cross-project grants, and memory handling still
need qualification.

The [boundary experience](boundary-experience.md) specifies how people understand
context, audience, and access. [Naming preferences](naming-preferences.md) add
changeable numbered, friendly, themed, and custom presets with individual
overrides. The [security supervisor](security-supervisor.md) owns security
oversight and maintenance, including automatic weekly OS updates and planned
guest restarts. Every affected task receives the schedule and prepares saved
work before installation. At the announced deadline, security takes precedence:
stop remaining bot runs after bounded grace, proceed with maintenance, and
recover from durable state without replaying uncertain effects. Names and role
templates do not confer any of those powers.
