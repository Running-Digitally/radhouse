# PostgreSQL storage boundary

The control database is authoritative for principals and grants, task revisions,
attempts, runtime dispatches, resource claims, budgets, channel receipts, events,
reviews, and publications. Bot guests and Buzz never connect to it.

Two store entry points keep development proof separate from retained work:

- `PostgresStore` accepts only a generated, loopback-only VS0 database with its
  exact fixture ownership marker.
- `ApplicationPostgresStore` accepts an explicitly named database and requires
  one matching `radhouse_metadata` row containing the configured deployment ID
  and supported schema version.

Both reject libpq service indirection, arbitrary connection options, missing
hosts, and database-name mismatches before connecting. They set the application
name, schema search path, and finite connection timeout themselves. The
application store accepts TLS file references in the DSN for deployments that
need database transport TLS; endpoint and certificate qualification remains a
deployment preflight responsibility.

The current schema is still a fresh-database fixture. A versioned, owner-run
migration command, runtime-role grants, upgrade/backup checks, and recovery proof
must be implemented before retained deployment. The runtime application role
must not own schema objects or receive create, role, database, or migration
authority. A matching metadata row proves target identity and compatibility; it
does not grant migration permission or prove backup coverage.
