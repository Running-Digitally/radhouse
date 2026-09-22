# Buzz collaboration profile

Buzz is Radhouse's primary conversational experience when enabled. An ordinary
agent may use an owner-only private conversation. A software project uses one
private stream channel containing the owner, the signed Radhouse coordinator
identity and its assigned specialist identities. Radhouse web owns detailed
evidence, protected review, publication and administration.

The private relay qualification retains upstream source
`092c6a7277698bd373ccbc1d008fc1507094ae74`. This does not identify the installed
client release. Official desktop `desktop-v0.5.23` is source
`b9392d9d78744df365f9276e1ffe8c1baa5ea903`; it displays the Researcher profile and
private conversation without a patch. The owner confirmed both official mobile
conversations. No generic upstream client gap has been demonstrated.

## Service boundary

The reference stack contains the Buzz relay, PostgreSQL, Redis, MinIO, and a
bounded initialization job. Publish only the admitted relay/TLS path. Database,
cache, object-store, and observer ports stay private or loopback-bound.

The Buzz guest receives no Hermes runtime, model credential, Docker socket,
hypervisor credential, global management token, or Radhouse infrastructure
executor. Use a non-superuser database role and bucket-scoped object credentials;
do not give the relay the object-store root credential. Keep migrations explicit,
drop unnecessary capabilities, enable `no-new-privileges`, and bound processes,
uploads, media, concurrency, and logs.

Retain PostgreSQL, Redis, object data, and application state on explicit paths.
Back them up as a consistent set and prove an isolated restore before admitting
retained conversations or media.

## One task and authority path

```text
signed Buzz event -> verified key and conversation binding
                  -> Radhouse command/use case
                  -> durable task, attempt, and operation
                  -> scoped Radhouse event -> Buzz and work home
```

Buzz signatures establish key possession. Relay membership establishes access
to a Buzz space. Neither grants a Radhouse role, bot, project, content audience,
or service permission. Radhouse maps the verified key and conversation to the
same person and project used by its web interface, and both surfaces use the same
command, delivery, state-revision, and publication identities.

Protected review occurs in Radhouse web. Researcher supplies a 15-minute,
audience-bound signed task locator in an HTTPS URL fragment. Normal sign-in/MFA
and current task/project/binding checks are mandatory; the locator is not a
bearer credential. Review and publication independently bind the exact artifact,
audience, revision and fresh human assurance. Chat reactions and ordinary
messages never approve publication. A successful publication produces one
durable correlated status message in Buzz.

## Project channels

The Radhouse identity is controller code, not another autonomous runtime. It is
the sole ingress owner for an enrolled project channel. It freezes every owner
event before effect, then delegates it to one ordinary Researcher, Builder,
Reviewer or Deployer task path. Specialists continue to sign and publish their
own progress and results, so the visible conversation identifies who did the
work.

Routing uses exact mentions and reply ancestry first. Otherwise it uses the
durable project phase and current task: active text becomes guidance, active
attachments are retained as the next contextual step, preview feedback returns
to Builder, owner preview acceptance starts an exact-revision Reviewer handoff,
and an owner deployment request starts Deployer only after a READY review of
that accepted revision. Status questions read project state and create no task.
Research followed by implementation produces one visible Researcher-to-Builder
handoff. Reviewer `CHANGES_NEEDED` produces one correlated Builder correction;
merge and deployment continue to require an owner message.

Clear single-role requests keep that deterministic path. For an ambiguous or
multi-step request with no explicit agent, Radhouse may run one tools-disabled
planning turn through an assigned Researcher runtime. The result is accepted
only as a strict `research`, `build`, `research_then_build` or `clarify`
proposal. It cannot approve, merge, deploy, grant access or change
infrastructure. Invalid output produces one clarification and no retry; the
original owner request remains the specialist's authoritative brief.

Routine runtime activity is pull-based. A project-channel `status` message
returns the active agent, a fixed local description of the latest pollable
Hermes checkpoint, its age, whether the owner is needed, and the current
PR/preview/deployment references. Activity alone never posts a Buzz message.
Radhouse stores neither chain-of-thought nor tool arguments, outputs, file
paths or provider text in this status view. Completion and action-needed
messages continue through the existing durable signed outbox.

The coordinator snapshot records only correlation and release facts: phase,
active/latest task, repository/branch/PR, source and preview revisions, preview
digest/URL, owner-accepted revision, reviewer verdict/revision, merge revision,
and deployment revision/status/URL. Raw task content and files stay in their
existing bounded stores.

Specialists may end a software-delivery result with one strict report line:

```text
RADHOUSE_PROJECT_UPDATE: {"source_revision":"<git sha>","preview_revision":"<same sha>","preview_digest":"<sha256>","preview_url":"https://…"}
```

Reviewer reports contain `reviewed_revision` and `reviewer_verdict`; Deployer
reports contain `merged_revision`, `deployed_revision`, `deployment_url` and
`deployment_status`. Radhouse ignores malformed, unknown or inconsistent
fields. The human-readable result remains primary. A report cannot grant access
or approve its own revision.

Private stream metadata and the complete owner/coordinator/specialist roster are
verified from relay-signed snapshots at ingress and delivery. The official
client's owner-only managed-agent policy means the owner performs the one-time
roster enrollment. No desktop fork or owner signing key is required.

## Failure and qualification gate

A Buzz outage does not cancel admitted controller work. Persist the original
signed outbox event before delivery and reuse it after lost acknowledgment or
restart. Duplicate, out-of-order, mirrored, stale or replayed events cannot
create a second task, repeat an effect, revive cancelled work or approve changed
content. An older restore cannot revive revoked memberships or key bindings.

First messages start work; active multi-step messages are correlated guidance;
completed work receives a contextual follow-up. Short no-tools responses are
never reopened merely to accept guidance. Retain queued/applied/too-late/unknown
outcomes and verify application in a later natural model turn.

The [implementation packet](../operator-buzz-completion.md) owns the exact
server/web and official-client acceptance, including deduplication, restart,
secure review navigation and publication status. The
[historical desktop patch](../../integrations/buzz-desktop/README.md) is no longer
an active integration path. A separately qualified private Buzz service does
not, by itself, prove the Radhouse conversation flow. Mobile foreground support
does not broaden private web ingress or satisfy the separate native-push gate.
