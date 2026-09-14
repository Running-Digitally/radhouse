# Buzz collaboration profile

Buzz is Radhouse's primary conversational experience when enabled. Researcher
uses a standard signed identity and owner-only private conversation in
unmodified official clients. Radhouse web owns detailed evidence, protected
review, publication and administration.

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
