# PostgreSQL storage boundary

The control database is authoritative for principals and grants, task revisions,
attempts, runtime dispatches, resource claims, budgets, channel receipts, events,
reviews, and publications. Bot guests and Buzz never connect to it.

Two store entry points keep development proof separate from retained work:

- `PostgresStore` accepts only a generated, loopback-only VS0 database with its
  exact fixture ownership marker.
- `ApplicationPostgresStore` accepts an explicitly named database and requires
  one matching `radhouse_metadata` row containing the configured deployment ID,
  supported schema version, and packaged migration digest.

Both reject libpq service indirection, arbitrary connection options, missing
hosts, and database-name mismatches before connecting. They set the application
name, schema search path, and finite connection timeout themselves. The
application store accepts TLS file references in the DSN for deployments that
need database transport TLS; endpoint and certificate qualification remains a
deployment preflight responsibility.

The initial schema now lives in the packaged `0001_initial.sql` migration and is
also executed by the disposable fixture. `initialize_database()` accepts an
explicit owner DSN, expected database, deployment ID, and existing runtime role.
It takes a deployment-scoped advisory lock, initializes only an empty database,
and otherwise requires exact supported metadata. Version 4 accepts the exact
version-1 through version-4 checksum, applies the ordered migrations in one transaction,
and preserves existing task and publication rows. It refuses to run as the runtime
identity or grant an overprivileged, inheriting, role-member, or object-owning
runtime identity.

The initializer grants schema use, table DML, and sequence use, then explicitly
removes writes to the deployment metadata and fixture marker. It also removes
database/schema creation and temporary-table permission. It returns a bounded
receipt with the database, deployment identity, schema version, migration digest,
and whether the schema was initialized, upgraded or already current.

The CLI wrapper requires the schema-owner DSN in a private, regular, bounded
single-line file. A missing `--apply` returns `apply_required` without reading
that file or contacting PostgreSQL. The explicit initialization form is:

```sh
radhouse migrate --config /etc/radhouse/base.yaml \
  --overlay /etc/radhouse/private.yaml \
  --owner-dsn-file /run/secrets/radhouse-owner-dsn \
  --runtime-role radhouse_runtime --apply
```

Do not retain the schema-owner DSN beside the application runtime secret after
the admitted migration window. The JSON result contains only the database and
deployment identity, schema version, migration digest, and result code.

Version 2 marks the extended task snapshot contract (selected files, previous
result context, guidance and permission receipts). Old binaries fail their
version check before reading or writing this state. Stop both writers and retain
a verified database backup before upgrading a retained deployment. Restore the
old database with the old binary only before admitting new work; afterwards,
preserve version-2 data for a forward fix unless loss of newer work is explicitly
approved. The runtime application role must not own schema objects or receive
create, role, database, or migration authority. A matching metadata row proves
target identity and compatibility; it does not grant migration permission or
prove backup coverage.

Version 3 adds conversation links, owner attestations, an inbox with frozen task
routing, and a signed-event outbox. Existing task/publication rows survive the
upgrade. The controller's private database backup now also contains an agent's
delegation credential; retain its existing restricted access. After admitting
conversation work, use a forward fix or disable its configured candidate while
preserving schema-3 state. A schema-2 binary cannot serve a schema-3 database.

Version 4 adds a bounded display title and independent title revision to each
task. Existing tasks receive a title from their frozen assignment. Title edits
do not change task state, result digests, reviews or publications. Preserve
schema-4 state after admitting title edits; older binaries cannot serve it.

Version 5 adds explicit project-agent assignments. Existing installations
retain their effective member/grant intersection; new projects name their
eligible agents. This table limits task admission and delegation without
granting a project access to unrelated agents.

Version 6 allows one private Buzz project channel to retain one signed
conversation link per assigned agent. The previous channel-wide uniqueness is
replaced by channel-plus-agent uniqueness. Each agent still owns a separate
outbox and task correlation; relay membership, project assignment and grants
remain independently enforced.
