# Software delivery agents

Design depth: D2. This slice uses the existing project, task, conversation and
agent contracts. It does not add a workflow engine.

## Product intent

A software project can include three distinct working roles:

1. **Builder** implements and tests a bounded change.
2. **Reviewer** independently examines the exact completed result and separates
   blocking defects from suggestions.
3. **Deployer** checks the reviewed result against one configured private
   release target, verifies the exact PR head and merge tree, and invokes only
   that target's named deployment operation.

In a project Buzz channel, the signed Radhouse coordinator starts ordinary
correlated child tasks and posts concise handoff notes. A project channel may
opt into automatic private release: Builder's exact preview goes to Reviewer,
and an independent `READY` review of the same head causes one Deployer handoff.
The channel's fixed private deployment URL is configured once, including for
its first release. There is no separate merge/deploy prompt on each such release. Channels without
that explicit setting retain the owner deployment-message path.

## Reused contracts

Every handoff creates an ordinary child task with `follows_task_id`. The child
receives the exact completed parent result through `previous_result`. An
automatic Researcher-to-Builder handoff also carries the files the owner
selected for that research/build request; other task files do not cross a
handoff. Project membership and current bot grants are rechecked at admission.
Unrelated task history, bot memory and credentials do not cross the handoff.

Official Buzz project channels remain the primary conversational surface. An
explicit agent mention overrides automatic routing. Otherwise project phase,
reply ancestry and current artifact state select the next agent. The web work
home exposes the same choices as one-click, role-aware handoffs with fixed
bounded briefs:

| From | To | Suggested action |
| --- | --- | --- |
| Builder | Reviewer | Review the exact result; identify blocking defects and state readiness. |
| Reviewer | Builder | Address the blocking findings and report the updated revision and validation. |
| Reviewer | Deployer | For an opted-in private project, release the READY-reviewed exact head. |

Radhouse may use one bounded model turn to interpret an ambiguous project goal
before creating a specialist task. That planner has no tools and emits a strict
route proposal only. The deterministic controller still owns identity,
membership, deduplication, task correlation, accepted revisions, review,
merge and deployment gates. Clear requests do not need the planner.

Project activity stays quiet by default. The owner can ask `status` in Buzz to
see a sanitized current step and age from the existing Hermes run-status poll,
plus any action needed and known delivery links. This does not subscribe to or
consume Hermes's non-replayable event stream and does not create a model call.

Reviewer and Deployer are separate signed bot identities and runtimes. Radhouse
is a signed controller identity with no separate agent runtime. A role
name never grants access. Reviewer receives only the repositories and evidence
selected for review. The default Deployer has no general host or GitHub
authority; a private project may provide a repository-scoped credential and
one unprivileged target-specific release operation.

## GitHub and deployment boundaries

GitHub is the shared revision reference for software work. The accepted default
is mediated repository access with short-lived, repository-scoped credentials;
an administrator may separately choose the documented advanced direct-token
mode. Builder may publish a bot branch and open a pull request. Reviewer may
read the exact revision and publish review findings. Neither role may merge.

Deployer acts only on an immutable reviewed revision and one named target. The
automatic handoff carries the project, repository, PR, preview and reviewed
head, preview digest and existing private target. Deployer rechecks the PR head
before merge, verifies the resulting main commit's tree, and deploys only that
merge revision. If any prerequisite changed or no matching unprivileged release
operation is configured, it reports the concrete gap instead of improvising a
host command. A project without automatic private release still uses its
existing protected owner decision.

## Vertical slices and acceptance

The first slice is deliberately small:

- show every eligible project agent as a handoff target instead of selecting the
  first unrelated agent;
- start role-aware review, revision and deployment-readiness child tasks in one
  click using fixed briefs;
- preserve the exact parent/child task correlation and current access checks;
- add distinct Reviewer and Deployer profiles to the private deployment; and
- prove one Builder result reviewed once, one bounded revision after a blocking
  finding, and one deployment-readiness handoff without an automatic merge or
  deployment.

The next GitHub slice is complete only when a configured repository proves
branch publication, pull-request creation, independent review, revocation and
human-controlled merge. The deployment slice is complete only when one named
target proves approved apply, idempotent retry, status and rollback. Those
external capabilities are not implied by the role-aware handoff UI.

Stop rather than broaden scope when an agent, repository, revision, preview,
review, target or operation cannot be verified exactly.

## Release correlation

Builder, Reviewer and Deployer may append the strict
`RADHOUSE_PROJECT_UPDATE` line documented in the Buzz integration profile.
Radhouse validates its URLs, revisions, digests, allowed fields and role before
updating the project snapshot. Preview review requires
`source_revision == preview_revision`; channels without automatic release can
still request explicit owner acceptance. Reviewer READY requires the reviewed
revision to equal the preview revision. A healthy deployment requires the
deployed revision to equal the reported merge revision and the reviewed source
to remain the current preview. Project cards expose the current phase, preview
and deployment without making the owner open a task to learn basic status.
