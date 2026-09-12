# Buzz collaboration profile

Buzz is Radhouse's optional conversational operator surface. When installed, an
operator should be able to start, follow, steer, pause, cancel, review, and share
the same durable task from Buzz or the Radhouse work home. Infrastructure and
recovery administration remain in Radhouse.

**Qualification candidate:** upstream `block/buzz` source commit
`092c6a7277698bd373ccbc1d008fc1507094ae74`. This is a prerelease source pin for
reproducible evaluation, not a stable or security-qualified release. Radhouse
should consume upstream artifacts with their original licenses and notices
rather than silently vendoring them as Radhouse code.

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

Protected review must be native in Buzz but commit through the Radhouse decision
transaction. A chat reaction, external approval link, or signed bot message is
insufficient. The decision must show the exact artifact digest and audience and
satisfy the [identity profile](authentik.md)'s current human-assurance and key
binding checks.

## Failure and qualification gate

A Buzz outage does not cancel admitted controller work. Radhouse records pending
delivery and resynchronizes authorized state after reconnect. Duplicate,
out-of-order, mirrored, stale, or replayed events cannot create a second task,
repeat an effect, revive cancelled work, or approve changed content. An older
restore cannot revive revoked memberships or key bindings.

Before the live pilot, prove pinned startup, migrations, listener and caller
restrictions, database and media isolation, key/person binding, both-direction
task continuation, native protected review, event replay and gap recovery,
revocation, resource ceilings, update/rollback, consistent backup, and isolated
restore. The current private preparation supplies a candidate composition and
offline checks only; it has not yet supplied guest-level or end-to-end proof.
