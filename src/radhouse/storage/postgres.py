"""Transactional PostgreSQL adapter for the explicitly owned local VS0 fixture.

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
import re
from typing import Iterator

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from radhouse.domain.access import Access, Binding, BotProfile
from radhouse.domain.releases import Publication, Review
from radhouse.domain.tasks import (
    AgentDispatch, Attempt, Delivery, Event, Operation, Rejected, SavedCommand, Task,
)


class FixtureBoundaryError(ValueError):
    """A target is outside the disposable, owned local fixture boundary."""


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


class PostgresUnitOfWork:
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
        return Access(**actor, bots=frozenset(row["bot_id"] for row in bots),
                      projects=frozenset(row["project_id"] for row in projects))

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

    def tasks(self) -> list[Task]:
        return [_snapshot(row, Task) for row in self._connection.execute(
            "SELECT snapshot FROM public.tasks ORDER BY task_id"
        ).fetchall()]

    def bots(self, principal_id: str) -> list[BotProfile]:
        return [BotProfile(**row) for row in self._connection.execute(
            "SELECT b.bot_id,b.display_name,b.role_name,b.provider_binding,b.state "
            "FROM public.bots b JOIN public.bot_grants g ON g.bot_id=b.bot_id "
            "WHERE g.principal_id=%s ORDER BY b.display_name,b.bot_id",
            (principal_id,),
        ).fetchall()]

    def insert_task(self, task: Task) -> None:
        self._connection.execute(
            "INSERT INTO public.tasks (task_id, owner_id, bot_id, project_id, task_revision, "
            "state_revision, phase, outcome, budget_remaining, attempt_id, snapshot) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (task.task_id, task.owner_id, task.bot_id, task.project_id, task.task_revision,
             task.state_revision, task.phase, task.outcome, task.budget_remaining, task.attempt_id, _json(task)),
        )
        self._record_revision(task)

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
