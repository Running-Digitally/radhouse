# Software delivery agents

Design depth: D2. This slice uses the existing project, task, conversation and
agent contracts. It does not add a workflow engine.

## Product intent

A software project can include three distinct working roles:

1. **Builder** implements and tests a bounded change.
2. **Reviewer** independently examines the exact completed result and separates
   blocking defects from suggestions.
3. **Deployer** checks the reviewed result against one configured release target
   and, after the protected human decision, invokes only that target's named
   deployment operation.

The operator remains in control of each handoff. Radhouse suggests the natural
next step, but it does not automatically repeat work, merge a pull request or
deploy a release.

## Reused contracts

Every handoff creates an ordinary child task with `follows_task_id`. The child
receives the exact completed parent result through `previous_result`. Project
membership and current bot grants are rechecked at admission. Unrelated task
history, files, bot memory and credentials do not cross the handoff.

Official Buzz project conversations remain the primary conversational surface.
An explicit agent mention selects the next agent. The web work home exposes the
same choices with role-aware labels and an editable starter brief:

| From | To | Suggested action |
| --- | --- | --- |
| Builder | Reviewer | Review the exact result; identify blocking defects and state readiness. |
| Reviewer | Builder | Address the blocking findings and report the updated revision and validation. |
| Reviewer or Builder | Deployer | Check release readiness and wait for the protected deployment decision. |

Reviewer and Deployer are separate signed bot identities and runtimes. A role
name never grants access. Reviewer receives only the repositories and evidence
selected for review. Deployer holds no general shell, GitHub credential or host
credential; a private deployment overlay may connect it to a narrowly configured
Operations service.

## GitHub and deployment boundaries

GitHub is the shared revision reference for software work. The accepted default
is mediated repository access with short-lived, repository-scoped credentials;
an administrator may separately choose the documented advanced direct-token
mode. Builder may publish a bot branch and open a pull request. Reviewer may
read the exact revision and publish review findings. Neither role may merge.

Deployer acts only on an immutable reviewed revision and one named target. A
deployment request records the project, root task, repository, revision, target,
operation and current human decision. The Operations boundary validates those
fields, expiry and idempotency before using credentials. If no matching operation
is configured, Deployer reports that concrete gap instead of improvising a host
command.

## Vertical slices and acceptance

The first slice is deliberately small:

- show every eligible project agent as a handoff target instead of selecting the
  first unrelated agent;
- offer role-aware review, revision and deployment-readiness briefs;
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

Stop rather than broaden scope when an agent, repository, revision, review,
target, operation or human decision cannot be verified exactly.
