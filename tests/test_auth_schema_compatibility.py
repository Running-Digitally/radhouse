"""The private chat auth contract remains usable without a controller migration."""
from types import SimpleNamespace

import pytest

from radhouse.auth.local import LocalAuthError, _verified_connection
from radhouse.storage.postgres import schema_digest


def connection(version, **overrides):
    row = {"deployment_id": "synthetic-deployment", "schema_version": version,
           "migration_sha256": schema_digest(version) if type(version) is int and 1 <= version <= 10 else "0" * 64,
           "database": "synthetic_database", **overrides}
    return SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchall=lambda: [row]))


@pytest.mark.parametrize("version", [7, 10])
def test_auth_accepts_exact_deployed_or_current_schema(version):
    _verified_connection(connection(version), "synthetic-deployment", "synthetic_database")


@pytest.mark.parametrize("version", [1, 6, 8, 9, 11, True, "7", None])
def test_auth_rejects_unqualified_or_malformed_schema(version):
    with pytest.raises(LocalAuthError, match="database_identity_mismatch"):
        _verified_connection(connection(version), "synthetic-deployment", "synthetic_database")


@pytest.mark.parametrize("version", [7, 10])
@pytest.mark.parametrize("changed", [{"migration_sha256": "0" * 64},
                                      {"deployment_id": "foreign"}, {"database": "foreign"}])
def test_compatible_version_does_not_relax_digest_or_identity(version, changed):
    with pytest.raises(LocalAuthError, match="database_identity_mismatch"):
        _verified_connection(connection(version, **changed), "synthetic-deployment", "synthetic_database")
