"""Transactional PostgreSQL adapters for application and owned fixture stores.

DDL belongs exclusively to the test bootstrap. Each context opens an independent
connection and briefly serializes fixture transactions; no external effect runs
under this lock. Resource claims persist after commit, so independent tasks may
be active concurrently even though their admission transactions serialize.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import ipaddress
from pathlib import Path
import re
from typing import Iterator

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from radhouse.domain.access import Access, Binding, BotProfile, ProjectProfile
from radhouse.storage.conversations import ConversationQueries
from radhouse.domain.releases import Publication, Review
from radhouse.domain.projects import ProjectCoordination
from radhouse.domain.tasks import (
    AgentDispatch, Attempt, Delivery, Event, Operation, Rejected, SavedCommand, Task,
    TaskTitle, initial_task_title,
)


class FixtureBoundaryError(ValueError):
    """A target is outside the disposable, owned local fixture boundary."""


class ApplicationStorageError(ValueError):
    """A configured database is not the expected initialized Radhouse store."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INITIAL_MIGRATION = Path(__file__).parent / "migrations" / "0001_initial.sql"
SCHEMA_VERSION = 7
MIGRATIONS = (_INITIAL_MIGRATION, Path(__file__).parent / "migrations" / "0002_operator_context.sql",
              Path(__file__).parent / "migrations" / "0003_conversations.sql",
              Path(__file__).parent / "migrations" / "0004_task_titles.sql",
              Path(__file__).parent / "migrations" / "0005_project_agents.sql",
              Path(__file__).parent / "migrations" / "0006_project_conversations.sql",
              Path(__file__).parent / "migrations" / "0007_project_coordination.sql")


def schema_digest(version: int = SCHEMA_VERSION) -> str:
    try:
        if version == 1:
            return hashlib.sha256(_INITIAL_MIGRATION.read_bytes()).hexdigest()
        if version not in {2, 3, 4, 5, 6, 7}:
            raise ApplicationStorageError("unsupported_schema_version")
        return hashlib.sha256(f"radhouse-schema-v{version}\0".encode() + b"\0".join(path.read_bytes() for path in MIGRATIONS[:version])).hexdigest()
    except OSError:
        raise ApplicationStorageError("database_migration_missing") from None


def _connection_parameters(dsn: str, run_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{8,48}", run_id):
        raise FixtureBoundaryError("invalid_fixture_run_id")
    try:
        params = conninfo_to_dict(dsn)
    except (psycopg.Error, ValueError) as exc:
        raise FixtureBoundaryError("invalid_fixture_dsn") from exc
    allowed = {"host", "hostaddr", "port", "dbname", "user", "password", "sslmode", "connect_timeout"}
    if set(params) - allowed:
        raise FixtureBoundaryError("unsupported_fixture_dsn_parameter")
    if params.get("dbname") != f"radhouse_vs0_{run_id}":
        raise FixtureBoundaryError("fixture_database_mismatch")
    host = params.get("host", "")
    if host == "localhost":
        host = "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
        supplied_address = ipaddress.ip_address(params.get("hostaddr", host))
    except ValueError as exc:
        raise FixtureBoundaryError("fixture_requires_loopback") from exc
    if not address.is_loopback or not supplied_address.is_loopback:
        raise FixtureBoundaryError("fixture_requires_loopback")
    # Pin the endpoint so neither name resolution nor libpq environment defaults
    # can redirect this connection to a non-loopback host or Unix socket.
    params.update(host=str(address), hostaddr=str(supplied_address),
                  connect_timeout=5, application_name="radhouse-vs0",
                  options="-c search_path=public")
    return params


def _application_connection_parameters(dsn: str, expected_database: str) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", expected_database):
        raise ApplicationStorageError("invalid_expected_database")
    try:
        params = conninfo_to_dict(dsn)
    except (psycopg.Error, ValueError) as exc:
        raise ApplicationStorageError("invalid_database_dsn") from exc
    allowed = {
        "host", "hostaddr", "port", "dbname", "user", "password", "sslmode",
        "sslrootcert", "sslcert", "sslkey", "connect_timeout",
        "channel_binding", "target_session_attrs",
    }
    if set(params) - allowed:
        raise ApplicationStorageError("unsupported_database_dsn_parameter")
    if not params.get("host"):
        raise ApplicationStorageError("database_host_required")
    if params.get("dbname") != expected_database:
        raise ApplicationStorageError("database_name_mismatch")
    params.update(
        connect_timeout=5,
        application_name="radhouse-controller",
        options="-c search_path=public",
    )
    return params


def _json(value) -> Jsonb:
    def normalize(item):
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, (tuple, list, set, frozenset)):
            return [normalize(part) for part in item]
        if isinstance(item, dict):
            return {key: normalize(part) for key, part in item.items()}
        return item
    return Jsonb(normalize(asdict(value)))


def _snapshot(row, kind):
    if row is None:
        return None
    value = dict(row["snapshot"])
    if kind is Task:
        value["blockers"] = tuple(value["blockers"])
        from radhouse.domain.tasks import InputFile
        value["files"] = tuple(InputFile(**item) for item in value.get("files", []))
        value["guidance"] = tuple(value.get("guidance", []))
        value["allowed_tools"] = tuple(value.get("allowed_tools", []))
    if kind in (Review, Publication):
        value["audience"] = tuple(value["audience"])
    if kind is Review:
        value["expires_at"] = datetime.fromisoformat(value["expires_at"])
    if kind is AgentDispatch:
        for field in ("submitted_at", "retention_until"):
            if value[field] is not None:
                value[field] = datetime.fromisoformat(value[field])
    return kind(**value)


class PostgresStore:
    def __init__(self, dsn: str, run_id: str):
        self._params = _connection_parameters(dsn, run_id)
        self.run_id = run_id
        self._lock = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8],
                                    "big", signed=True)

    @contextmanager
    def transaction(self) -> Iterator["PostgresUnitOfWork"]:
        with psycopg.connect(**self._params, row_factory=dict_row) as connection:
            try:
                rows = connection.execute(
                    "SELECT run_id, current_database() AS database FROM public.fixture_ownership WHERE singleton"
                ).fetchall()
            except psycopg.Error as exc:
                raise FixtureBoundaryError("fixture_ownership_missing") from exc
            if (len(rows) != 1 or rows[0]["run_id"] != self.run_id
                    or rows[0]["database"] != f"radhouse_vs0_{self.run_id}"):
                raise FixtureBoundaryError("fixture_ownership_mismatch")
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (self._lock,))
            try:
                yield PostgresUnitOfWork(connection)
            except psycopg.IntegrityError as exc:
                raise Rejected("storage_conflict") from exc


class ApplicationPostgresStore:
    """Store for a pre-migrated database with a pinned deployment identity."""

    schema_version = SCHEMA_VERSION

    def __init__(self, dsn: str, expected_database: str, deployment_id: str):
        if not _IDENTIFIER.fullmatch(deployment_id):
            raise ApplicationStorageError("invalid_deployment_id")
        self._params = _application_connection_parameters(dsn, expected_database)
        self.expected_database = expected_database
        self.deployment_id = deployment_id
        self._lock = int.from_bytes(
            hashlib.sha256(deployment_id.encode()).digest()[:8], "big", signed=True,
        )

    @contextmanager
    def transaction(self) -> Iterator["PostgresUnitOfWork"]:
        with psycopg.connect(**self._params, row_factory=dict_row) as connection:
            try:
                rows = connection.execute(
                    "SELECT deployment_id,schema_version,migration_sha256,current_database() AS database "
                    "FROM public.radhouse_metadata WHERE singleton"
                ).fetchall()
            except psycopg.Error as exc:
                raise ApplicationStorageError("database_schema_missing") from exc
            if (
                len(rows) != 1
                or rows[0]["deployment_id"] != self.deployment_id
                or rows[0]["schema_version"] != self.schema_version
                or rows[0]["migration_sha256"] != schema_digest()
                or rows[0]["database"] != self.expected_database
            ):
                raise ApplicationStorageError("database_identity_mismatch")
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (self._lock,))
            try:
                yield PostgresUnitOfWork(connection)
            except psycopg.IntegrityError as exc:
                raise Rejected("storage_conflict") from exc


class PostgresUnitOfWork(ConversationQueries):
    def __init__(self, connection):
        self._connection = connection

    def access(self, principal_id: str) -> Access | None:
        actor = self._connection.execute(
            "SELECT principal_id, role, active FROM public.actors WHERE principal_id=%s",
            (principal_id,),
        ).fetchone()
        if actor is None:
            return None
        bots = self._connection.execute(
            "SELECT bot_id FROM public.bot_grants WHERE principal_id=%s", (principal_id,),
        ).fetchall()
        projects = self._connection.execute(
            "SELECT project_id FROM public.project_members WHERE principal_id=%s", (principal_id,),
        ).fetchall()
        project_bots = self._connection.execute(
            "SELECT pb.project_id,pb.bot_id FROM public.project_bots pb "
            "JOIN public.project_members pm ON pm.project_id=pb.project_id "
            "JOIN public.bot_grants bg ON bg.bot_id=pb.bot_id "
            "WHERE pm.principal_id=%s AND bg.principal_id=%s",
            (principal_id, principal_id),
        ).fetchall()
        return Access(**actor, bots=frozenset(row["bot_id"] for row in bots),
                      projects=frozenset(row["project_id"] for row in projects),
                      project_bots=frozenset((row["project_id"], row["bot_id"])
                                             for row in project_bots))

    def binding(self, channel: str, subject: str, conversation_id: str) -> Binding | None:
        row = self._connection.execute(
            "SELECT channel, subject, conversation_id, principal_id, project_id, revision, active "
            "FROM public.channel_bindings WHERE channel=%s AND subject=%s AND conversation_id=%s",
            (channel, subject, conversation_id),
        ).fetchone()
        return Binding(**row) if row else None

    def task(self, task_id: str) -> Task | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.tasks WHERE task_id=%s", (task_id,),
        ).fetchone(), Task)

    def task_title(self, task_id: str) -> TaskTitle | None:
        row = self._connection.execute(
            "SELECT task_id,display_title AS title,title_source AS source,title_revision AS revision "
            "FROM public.tasks WHERE task_id=%s", (task_id,),
        ).fetchone()
        return TaskTitle(**row) if row else None

    def bindings(self, channel: str, subject: str, principal_id: str) -> list[Binding]:
        return [Binding(**row) for row in self._connection.execute(
            "SELECT channel,subject,conversation_id,principal_id,project_id,revision,active "
            "FROM public.channel_bindings WHERE channel=%s AND subject=%s "
            "AND principal_id=%s AND active ORDER BY conversation_id LIMIT 100",
            (channel, subject, principal_id),
        ).fetchall()]

    def audience(self, bot_id: str, project_id: str) -> tuple[str, ...]:
        return tuple(row["principal_id"] for row in self._connection.execute(
            "SELECT a.principal_id FROM public.actors a "
            "JOIN public.bot_grants b USING(principal_id) "
            "JOIN public.project_members p USING(principal_id) "
            "JOIN public.project_bots pb ON pb.project_id=p.project_id AND pb.bot_id=b.bot_id "
            "WHERE a.active AND b.bot_id=%s AND p.project_id=%s "
            "ORDER BY a.principal_id LIMIT 100", (bot_id, project_id),
        ).fetchall())

    def tasks(self) -> list[Task]:
        return [_snapshot(row, Task) for row in self._connection.execute(
            "SELECT snapshot FROM public.tasks ORDER BY task_id"
        ).fetchall()]

    def task_admission_order(self, task_ids: tuple[str, ...]) -> dict[str, int]:
        if not task_ids:
            return {}
        rows = self._connection.execute(
            "SELECT task_id, MIN(cursor) AS admitted_cursor FROM public.events "
            "WHERE task_id = ANY(%s) AND kind='admitted' GROUP BY task_id",
            (list(task_ids),),
        ).fetchall()
        return {row["task_id"]: row["admitted_cursor"] for row in rows}

    def bots(self, principal_id: str, project_id: str | None = None) -> list[BotProfile]:
        return [BotProfile(**row) for row in self._connection.execute(
            "SELECT b.bot_id,b.display_name,b.role_name,b.provider_binding,b.state "
            "FROM public.bots b JOIN public.bot_grants g ON g.bot_id=b.bot_id "
            "LEFT JOIN public.project_bots pb ON pb.bot_id=b.bot_id AND pb.project_id=%s "
            "WHERE g.principal_id=%s AND (%s::text IS NULL OR pb.project_id IS NOT NULL) "
            "ORDER BY b.display_name,b.bot_id",
            (project_id, principal_id, project_id),
        ).fetchall()]

    def project_bot_ids(self, project_id: str) -> tuple[str, ...]:
        return tuple(row["bot_id"] for row in self._connection.execute(
            "SELECT bot_id FROM public.project_bots WHERE project_id=%s ORDER BY bot_id",
            (project_id,),
        ).fetchall())

    def project(self, project_id: str) -> ProjectProfile | None:
        row = self._connection.execute(
            "SELECT project_id,owner_id,display_name,state FROM public.projects "
            "WHERE project_id=%s", (project_id,),
        ).fetchone()
        return ProjectProfile(**row) if row else None

    def project_coordination(self, project_id: str) -> ProjectCoordination | None:
        row = self._connection.execute(
            "SELECT snapshot FROM public.project_coordination WHERE project_id=%s",
            (project_id,),
        ).fetchone()
        return _snapshot(row, ProjectCoordination) if row else None

    def save_project_coordination(
        self, state: ProjectCoordination, expected_revision: int | None
    ) -> None:
        state.validate()
        if expected_revision is None:
            if state.revision != 1:
                raise Rejected("project_coordination_revision_conflict")
            try:
                self._connection.execute(
                    "INSERT INTO public.project_coordination"
                    "(project_id,revision,phase,active_task_id,snapshot) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (state.project_id, state.revision, state.phase,
                     state.active_task_id, _json(state)),
                )
            except psycopg.errors.UniqueViolation:
                raise Rejected("project_coordination_revision_conflict") from None
            return
        if state.revision != expected_revision + 1:
            raise Rejected("project_coordination_revision_conflict")
        cursor = self._connection.execute(
            "UPDATE public.project_coordination SET revision=%s,phase=%s,"
            "active_task_id=%s,snapshot=%s WHERE project_id=%s AND revision=%s",
            (state.revision, state.phase, state.active_task_id, _json(state),
             state.project_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise Rejected("project_coordination_revision_conflict")

    def create_project(self, project: ProjectProfile, principal_id: str,
                       bot_ids: tuple[str, ...], binding: Binding) -> None:
        self._connection.execute(
            "INSERT INTO public.projects(project_id,owner_id,display_name,state) "
            "VALUES (%s,%s,%s,%s)",
            (project.project_id, project.owner_id, project.display_name, project.state),
        )
        self._connection.execute(
            "INSERT INTO public.project_members(principal_id,project_id) VALUES (%s,%s)",
            (principal_id, project.project_id),
        )
        for bot_id in bot_ids:
            self._connection.execute(
                "INSERT INTO public.project_bots(project_id,bot_id) VALUES (%s,%s)",
                (project.project_id, bot_id),
            )
        self._connection.execute(
            "INSERT INTO public.channel_bindings"
            "(channel,subject,conversation_id,principal_id,project_id,revision,active) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (binding.channel, binding.subject, binding.conversation_id,
             binding.principal_id, binding.project_id, binding.revision, binding.active),
        )
        state = ProjectCoordination(project.project_id).validate()
        self.save_project_coordination(state, None)

    def insert_task(self, task: Task) -> None:
        title = initial_task_title(task.brief)
        self._connection.execute(
            "INSERT INTO public.tasks (task_id, owner_id, bot_id, project_id, task_revision, "
            "state_revision, phase, outcome, budget_remaining, attempt_id, snapshot, "
            "display_title, title_source, title_revision) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'brief',1)",
            (task.task_id, task.owner_id, task.bot_id, task.project_id, task.task_revision,
             task.state_revision, task.phase, task.outcome, task.budget_remaining, task.attempt_id,
             _json(task), title),
        )
        self._record_revision(task)

    def save_task_title(self, title: TaskTitle, expected_revision: int) -> None:
        if title.revision != expected_revision + 1:
            raise Rejected("task_title_revision_conflict")
        cursor = self._connection.execute(
            "UPDATE public.tasks SET display_title=%s,title_source=%s,title_revision=%s "
            "WHERE task_id=%s AND title_revision=%s",
            (title.title, title.source, title.revision, title.task_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise Rejected("task_title_revision_conflict")

    def save_task(self, task: Task, expected_state_revision: int) -> None:
        if task.state_revision != expected_state_revision + 1:
            raise Rejected("revision_conflict")
        cursor = self._connection.execute(
            "UPDATE public.tasks SET task_revision=%s, state_revision=%s, phase=%s, outcome=%s, "
            "budget_remaining=%s, attempt_id=%s, snapshot=%s WHERE task_id=%s AND state_revision=%s "
            "AND owner_id=%s AND bot_id=%s AND project_id=%s",
            (task.task_revision, task.state_revision, task.phase, task.outcome, task.budget_remaining,
             task.attempt_id, _json(task), task.task_id, expected_state_revision,
             task.owner_id, task.bot_id, task.project_id),
        )
        if cursor.rowcount != 1:
            raise Rejected("revision_conflict")
        self._record_revision(task)

    def _record_revision(self, task: Task) -> None:
        self._connection.execute(
            "INSERT INTO public.task_revisions(task_id, revision, snapshot) VALUES (%s,%s,%s) "
            "ON CONFLICT (task_id, revision) DO NOTHING", (task.task_id, task.task_revision, _json(task)),
        )

    def command(self, principal_id: str, command_key: str) -> SavedCommand | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.commands WHERE principal_id=%s AND command_key=%s",
            (principal_id, command_key),
        ).fetchone(), SavedCommand)

    def save_command(self, command: SavedCommand) -> None:
        self._connection.execute(
            "INSERT INTO public.commands(principal_id, command_key, task_id, snapshot) VALUES (%s,%s,%s,%s)",
            (command.principal_id, command.command_key, command.task_id, _json(command)),
        )

    def delivery(self, channel: str, event_id: str) -> Delivery | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.deliveries WHERE channel=%s AND event_id=%s", (channel, event_id),
        ).fetchone(), Delivery)

    def save_delivery(self, delivery: Delivery) -> None:
        self._connection.execute(
            "INSERT INTO public.deliveries(channel, event_id, task_id, principal_id, snapshot) VALUES (%s,%s,%s,%s,%s)",
            (delivery.channel, delivery.event_id, delivery.task_id, delivery.principal_id, _json(delivery)),
        )

    def claim(self, task: Task, attempt: Attempt) -> bool:
        current = self.task(task.task_id)
        if (current is None or current.state_revision != task.state_revision
                or current.budget_remaining <= 0):
            return False
        if attempt.task_id != task.task_id:
            raise Rejected("attempt_task_mismatch")
        if self._connection.execute(
            "SELECT 1 FROM public.attempts WHERE task_id=%s AND is_current", (task.task_id,),
        ).fetchone():
            return False
        if task.resource_key is not None and self._connection.execute(
            "SELECT 1 FROM public.claims WHERE bot_id=%s AND resource_key=%s AND active",
            (task.bot_id, task.resource_key),
        ).fetchone():
            return False
        try:
            # Savepoint ensures a constraint race has no partial reservation.
            with self._connection.transaction():
                self._connection.execute(
                    "INSERT INTO public.attempts(attempt_id, task_id, generation, worker_id, state, is_current, snapshot) "
                    "VALUES (%s,%s,%s,%s,%s,true,%s)",
                    (attempt.attempt_id, attempt.task_id, attempt.generation, attempt.worker_id, attempt.state, _json(attempt)),
                )
                if task.resource_key is not None:
                    self._connection.execute(
                        "INSERT INTO public.claims(attempt_id, task_id, bot_id, resource_key, active) VALUES (%s,%s,%s,%s,true)",
                        (attempt.attempt_id, task.task_id, task.bot_id, task.resource_key),
                    )
                self._connection.execute(
                    "INSERT INTO public.budget_reservations(attempt_id, task_id, amount) VALUES (%s,%s,1)",
                    (attempt.attempt_id, task.task_id),
                )
        except psycopg.errors.UniqueViolation:
            return False
        return True

    def attempt(self, attempt_id: str) -> Attempt | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.attempts WHERE attempt_id=%s", (attempt_id,),
        ).fetchone(), Attempt)

    def finish_attempt(self, attempt_id: str) -> None:
        attempt = self.attempt(attempt_id)
        if attempt is None:
            raise Rejected("attempt_not_found", 404)
        finished = replace(attempt, state="finished")
        self._connection.execute(
            "UPDATE public.attempts SET is_current=false,state=%s,snapshot=%s WHERE attempt_id=%s",
            (finished.state, _json(finished), attempt_id),
        )
        self._connection.execute("UPDATE public.claims SET active=false WHERE attempt_id=%s", (attempt_id,))

    def operation(self, key: str) -> Operation | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.operations WHERE operation_key=%s", (key,),
        ).fetchone(), Operation)

    def save_operation(self, operation: Operation) -> None:
        cursor = self._connection.execute(
            "INSERT INTO public.operations(operation_key,task_id,attempt_id,state,snapshot) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT(operation_key) DO UPDATE SET state=EXCLUDED.state,snapshot=EXCLUDED.snapshot "
            "WHERE operations.task_id=EXCLUDED.task_id AND operations.attempt_id=EXCLUDED.attempt_id",
            (operation.key, operation.task_id, operation.attempt_id, operation.state, _json(operation)),
        )
        if cursor.rowcount != 1:
            raise Rejected("operation_conflict")

    def dispatch(self, key: str) -> AgentDispatch | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.agent_dispatches WHERE dispatch_key=%s", (key,),
        ).fetchone(), AgentDispatch)

    def save_dispatch(self, dispatch: AgentDispatch) -> None:
        cursor = self._connection.execute(
            "INSERT INTO public.agent_dispatches(dispatch_key,task_id,attempt_id,state,run_id,snapshot) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(dispatch_key) DO UPDATE SET "
            "state=EXCLUDED.state,run_id=EXCLUDED.run_id,snapshot=EXCLUDED.snapshot "
            "WHERE agent_dispatches.task_id=EXCLUDED.task_id "
            "AND agent_dispatches.attempt_id=EXCLUDED.attempt_id",
            (dispatch.key, dispatch.task_id, dispatch.attempt_id, dispatch.state,
             dispatch.run_id, _json(dispatch)),
        )
        if cursor.rowcount != 1:
            raise Rejected("dispatch_conflict")

    def add_event(self, event: Event) -> None:
        self._connection.execute(
            "INSERT INTO public.events(task_id,kind,state_revision,snapshot) VALUES (%s,%s,%s,%s)",
            (event.task_id, event.kind, event.state_revision, _json(event)),
        )

    def events(self, task_id: str, after: int) -> list[Event]:
        return [replace(_snapshot(row, Event), cursor=row["cursor"]) for row in self._connection.execute(
            "SELECT cursor,snapshot FROM public.events WHERE task_id=%s AND cursor>%s ORDER BY cursor",
            (task_id, after),
        ).fetchall()]

    def latest_event(self, task_id: str, kind: str) -> Event | None:
        row = self._connection.execute(
            "SELECT cursor,snapshot FROM public.events WHERE task_id=%s AND kind=%s "
            "ORDER BY cursor DESC LIMIT 1",
            (task_id, kind),
        ).fetchone()
        return replace(_snapshot(row, Event), cursor=row["cursor"]) if row else None

    def review(self, review_id: str) -> Review | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.reviews WHERE review_id=%s", (review_id,),
        ).fetchone(), Review)

    def save_review(self, review: Review) -> None:
        cursor = self._connection.execute(
            "INSERT INTO public.reviews(review_id,task_id,reviewer_id,revision,state,snapshot) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(review_id) DO UPDATE SET revision=EXCLUDED.revision,state=EXCLUDED.state,snapshot=EXCLUDED.snapshot "
            "WHERE reviews.task_id=EXCLUDED.task_id AND reviews.reviewer_id=EXCLUDED.reviewer_id",
            (review.review_id, review.task_id, review.reviewer_id, review.revision, review.state, _json(review)),
        )
        if cursor.rowcount != 1:
            raise Rejected("review_conflict")

    def publication(self, task_id: str) -> Publication | None:
        return _snapshot(self._connection.execute(
            "SELECT snapshot FROM public.publications WHERE task_id=%s", (task_id,),
        ).fetchone(), Publication)

    def publish(self, publication: Publication) -> None:
        self._connection.execute(
            "INSERT INTO public.publications(publication_id,task_id,review_id,digest,snapshot) VALUES (%s,%s,%s,%s,%s)",
            (publication.publication_id, publication.task_id, publication.review_id, publication.digest, _json(publication)),
        )
