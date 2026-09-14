import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from radhouse.storage.migrations import MigrationError, initialize_database
from radhouse.storage.postgres import ApplicationPostgresStore
from radhouse.storage.postgres import ApplicationStorageError, schema_digest


@pytest.mark.postgres
@pytest.mark.parametrize("legacy_version", [1, 2])
def test_legacy_upgrade_preserves_tasks_and_requires_exact_version_digest(store, service, alice, envelope, start, legacy_version):
    task = service.admit(alice, envelope(), start)
    owner = os.environ["RADHOUSE_VS0_OWNER_DSN"]
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    database = f"radhouse_vs0_{run_id}"
    arguments = dict(expected_database=database, deployment_id=f"fixture-{run_id}", runtime_role="radhouse_runtime")
    with psycopg.connect(owner) as connection:
        # Reconstruct the genuine old schema in this exclusively owned fixture.
        for table in ("conversation_outbox", "conversation_messages", "conversation_links"):
            connection.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))
        connection.execute("UPDATE radhouse_metadata SET schema_version=%s,migration_sha256=%s", (legacy_version, schema_digest(legacy_version)))
    runtime = ApplicationPostgresStore(os.environ["RADHOUSE_VS0_DSN"], database, f"fixture-{run_id}")
    with pytest.raises(ApplicationStorageError, match="database_identity_mismatch"):
        with runtime.transaction(): pass
    receipt = initialize_database(owner, **arguments)
    assert receipt.result == "upgraded" and receipt.schema_version == 3
    with runtime.transaction() as tx:
        assert tx.task(task.task_id) == task
    try:
        with psycopg.connect(owner) as connection:
            connection.execute("UPDATE radhouse_metadata SET schema_version=1,migration_sha256=%s", ("0" * 64,))
        with pytest.raises(MigrationError, match="database_identity_mismatch"):
            initialize_database(owner, **arguments)
    finally:
        with psycopg.connect(owner) as connection:
            connection.execute("UPDATE radhouse_metadata SET schema_version=3,migration_sha256=%s", (schema_digest(),))


@pytest.mark.postgres
def test_owner_initializer_is_idempotent_for_the_exact_current_database(store):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    arguments = {
        "expected_database": f"radhouse_vs0_{run_id}",
        "deployment_id": f"fixture-{run_id}",
        "runtime_role": "radhouse_runtime",
    }

    first = initialize_database(os.environ["RADHOUSE_VS0_OWNER_DSN"], **arguments)
    second = initialize_database(os.environ["RADHOUSE_VS0_OWNER_DSN"], **arguments)

    assert first == second
    assert first.result == "current"
    assert first.schema_version == 3
    assert len(first.migration_sha256) == 64


@pytest.mark.postgres
def test_initializer_rejects_runtime_identity_and_wrong_deployment(store):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    database = f"radhouse_vs0_{run_id}"
    with pytest.raises(MigrationError, match="migration_identity_mismatch"):
        initialize_database(
            os.environ["RADHOUSE_VS0_DSN"], expected_database=database,
            deployment_id=f"fixture-{run_id}", runtime_role="radhouse_runtime",
        )
    with pytest.raises(MigrationError, match="database_identity_mismatch"):
        initialize_database(
            os.environ["RADHOUSE_VS0_OWNER_DSN"], expected_database=database,
            deployment_id="different-deployment", runtime_role="radhouse_runtime",
        )


@pytest.mark.postgres
def test_initializer_creates_and_runtime_store_opens_a_fresh_database(store):
    database = f"radhouse_migration_{uuid4().hex[:16]}"
    owner = conninfo_to_dict(os.environ["RADHOUSE_VS0_OWNER_DSN"])
    admin = dict(owner, dbname="postgres")
    target_owner = make_conninfo(**dict(owner, dbname=database))
    runtime = conninfo_to_dict(os.environ["RADHOUSE_VS0_DSN"])
    target_runtime = make_conninfo(**dict(runtime, dbname=database))
    try:
        with psycopg.connect(**admin, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

        receipt = initialize_database(
            target_owner, expected_database=database,
            deployment_id="migration-proof", runtime_role="radhouse_runtime",
        )

        assert receipt.result == "initialized"
        with ApplicationPostgresStore(
            target_runtime, database, "migration-proof",
        ).transaction() as tx:
            assert tx.tasks() == []
    finally:
        with psycopg.connect(**admin, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database),
            ))
