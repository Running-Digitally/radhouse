"""Owner-run initialization for one explicitly targeted Radhouse database."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from radhouse.storage.postgres import (
    ApplicationStorageError, _application_connection_parameters, schema_digest,
)


_ROLE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SCHEMA_VERSION = 1
_MIGRATION = Path(__file__).parent / "migrations" / "0001_initial.sql"


class MigrationError(ValueError):
    """A bounded refusal or migration failure without database diagnostics."""


@dataclass(frozen=True)
class MigrationReceipt:
    database: str
    deployment_id: str
    schema_version: int
    migration_sha256: str
    result: str


def _runtime_role_is_bounded(connection, runtime_role: str) -> None:
    role = connection.execute(
        "SELECT oid,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls "
        "FROM pg_roles WHERE rolname=%s", (runtime_role,),
    ).fetchone()
    if role is None:
        raise MigrationError("runtime_role_missing")
    if (
        role["rolsuper"] or role["rolinherit"] or role["rolcreaterole"]
        or role["rolcreatedb"] or role["rolreplication"] or role["rolbypassrls"]
    ):
        raise MigrationError("runtime_role_overprivileged")
    membership = connection.execute(
        "SELECT 1 FROM pg_auth_members WHERE member=%s LIMIT 1", (role["oid"],),
    ).fetchone()
    if membership is not None:
        raise MigrationError("runtime_role_has_membership")
    ownership = connection.execute(
        "SELECT 1 FROM pg_namespace WHERE nspname='public' AND nspowner=%s "
        "UNION ALL SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relowner=%s LIMIT 1", (role["oid"], role["oid"]),
    ).fetchone()
    if ownership is not None:
        raise MigrationError("runtime_role_owns_schema_object")


def _grant_runtime(connection, runtime_role: str, database: str) -> None:
    _runtime_role_is_bounded(connection, runtime_role)
    role = sql.Identifier(runtime_role)
    database_name = sql.Identifier(database)
    connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    connection.execute(sql.SQL("REVOKE CREATE,TEMPORARY ON DATABASE {} FROM {}").format(
        database_name, role,
    ))
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    connection.execute(sql.SQL(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}"
    ).format(role))
    connection.execute(sql.SQL(
        "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
    ).format(role))
    connection.execute(sql.SQL(
        "REVOKE INSERT,UPDATE,DELETE ON public.radhouse_metadata FROM {}"
    ).format(role))
    if connection.execute("SELECT to_regclass('public.fixture_ownership') AS name").fetchone()["name"]:
        connection.execute(sql.SQL(
            "REVOKE INSERT,UPDATE,DELETE ON public.fixture_ownership FROM {}"
        ).format(role))


def initialize_database(
    owner_dsn: str, *, expected_database: str, deployment_id: str, runtime_role: str,
) -> MigrationReceipt:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", deployment_id):
        raise MigrationError("invalid_deployment_id")
    if not _ROLE.fullmatch(runtime_role):
        raise MigrationError("invalid_runtime_role")
    try:
        params = _application_connection_parameters(owner_dsn, expected_database)
    except ApplicationStorageError as error:
        raise MigrationError(str(error)) from None
    params["application_name"] = "radhouse-migration"
    try:
        source = _MIGRATION.read_bytes()
        migration_digest = schema_digest()
    except ApplicationStorageError as error:
        raise MigrationError(str(error)) from None
    lock = int.from_bytes(
        hashlib.sha256(deployment_id.encode()).digest()[:8], "big", signed=True,
    )
    try:
        with psycopg.connect(**params, row_factory=dict_row) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
            identity = connection.execute(
                "SELECT current_database() AS database,current_user AS owner"
            ).fetchone()
            if identity["database"] != expected_database or identity["owner"] == runtime_role:
                raise MigrationError("migration_identity_mismatch")
            metadata_exists = connection.execute(
                "SELECT to_regclass('public.radhouse_metadata') AS name"
            ).fetchone()["name"] is not None
            result = "current"
            if metadata_exists:
                rows = connection.execute(
                    "SELECT deployment_id,schema_version,migration_sha256 "
                    "FROM public.radhouse_metadata WHERE singleton"
                ).fetchall()
                if len(rows) != 1 or rows[0] != {
                    "deployment_id": deployment_id, "schema_version": _SCHEMA_VERSION,
                    "migration_sha256": migration_digest,
                }:
                    raise MigrationError("database_identity_mismatch")
            else:
                existing = connection.execute(
                    "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f') LIMIT 1"
                ).fetchone()
                if existing is not None:
                    raise MigrationError("database_not_empty")
                connection.execute(source.decode("utf-8"))
                connection.execute(
                    "INSERT INTO public.radhouse_metadata"
                    "(singleton,deployment_id,schema_version,migration_sha256) "
                    "VALUES (true,%s,%s,%s)",
                    (deployment_id, _SCHEMA_VERSION, migration_digest),
                )
                result = "initialized"
            _grant_runtime(connection, runtime_role, expected_database)
    except MigrationError:
        raise
    except (OSError, UnicodeError, psycopg.Error):
        raise MigrationError("migration_failed") from None
    return MigrationReceipt(
        expected_database, deployment_id, _SCHEMA_VERSION, migration_digest, result,
    )
