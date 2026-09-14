import os

import pytest

from radhouse.storage.postgres import ApplicationPostgresStore, ApplicationStorageError


def test_application_store_rejects_wrong_database_before_connect(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a mismatched configured database must not be contacted")

    monkeypatch.setattr("radhouse.storage.postgres.psycopg.connect", forbidden)
    with pytest.raises(ApplicationStorageError, match="database_name_mismatch"):
        ApplicationPostgresStore(
            "host=database.example.invalid dbname=other user=radhouse",
            "radhouse", "example-home",
        )


@pytest.mark.parametrize("dsn", [
    "dbname=radhouse user=radhouse",
    "host=database.example.invalid dbname=radhouse user=radhouse options='-c role=owner'",
    "host=database.example.invalid dbname=radhouse user=radhouse service=other",
])
def test_application_store_requires_explicit_host_and_rejects_dsn_redirects(dsn, monkeypatch):
    monkeypatch.setattr(
        "radhouse.storage.postgres.psycopg.connect",
        lambda *args, **kwargs: pytest.fail("invalid DSN must not be contacted"),
    )
    with pytest.raises(ApplicationStorageError):
        ApplicationPostgresStore(dsn, "radhouse", "example-home")


@pytest.mark.postgres
def test_application_store_accepts_only_initialized_matching_identity(store):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    database = f"radhouse_vs0_{run_id}"
    dsn = os.environ["RADHOUSE_VS0_DSN"]

    store = ApplicationPostgresStore(dsn, database, f"fixture-{run_id}")
    with store.transaction() as tx:
        assert tx.access("alice").role == "operator"

    wrong = ApplicationPostgresStore(dsn, database, "another-deployment")
    with pytest.raises(ApplicationStorageError, match="database_identity_mismatch"):
        with wrong.transaction():
            pass
