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
and otherwise requires exact current metadata. It refuses to run as the runtime
identity or grant an overprivileged, inheriting, role-member, or object-owning
runtime identity.

The initializer grants schema use, table DML, and sequence use, then explicitly
removes writes to the deployment metadata and fixture marker. It also removes
database/schema creation and temporary-table permission. It returns a bounded
receipt with the database, deployment identity, schema version, migration digest,
and whether the schema was initialized or already current.

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

Upgrade migrations, a backup gate, and recovery proof remain before retained
deployment. The runtime application role must not own schema objects or receive
create, role, database, or migration authority. A matching metadata row proves
target identity and compatibility; it does not grant migration permission or
prove backup coverage.
