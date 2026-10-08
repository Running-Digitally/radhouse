"""Small, durable ownership state for the existing shared browser.

Only the trusted native lifecycle binds a browser; this is not a public API or
an agent permission system. The executor reserves before sending, matches native
ACKs and never retries commands automatically. Human retries retain their
original revision and sequence. The latest ACK is retained; older input is
rejected rather than executed again. No input payload or action history is kept.

The existing root maintenance hold remains authoritative. Admission checks that
hold inside the state transaction; maintenance observes committed state after
creating the hold. The integration binds exact native generations and owners.
"""

import json
import math
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Literal
from uuid import uuid4

Mode = Literal["agent", "takeover_pending", "human", "paused", "recovering"]
Outcome = Literal["reserved", "applied", "rejected", "uncertain"]


class ControlRejected(ValueError):
    """A fixed rejection code, containing no caller data."""


def _identifier(value):
    if type(value) is not str or not 1 <= len(value) <= 512:
        raise ControlRejected("invalid_binding")


def _positive(value):
    if type(value) is not int or value < 1:
        raise ControlRejected("invalid_binding")


@dataclass(frozen=True)
class BrowserIdentity:
    conversation_id: str
    session_id: str
    generation: str

    def __post_init__(self):
        for value in asdict(self).values():
            _identifier(value)


@dataclass(frozen=True)
class OwnerBinding:
    principal_id: str
    auth_session_digest: str = field(repr=False)
    binding_revision: int
    tab_id: str

    def __post_init__(self):
        _identifier(self.principal_id)
        _identifier(self.tab_id)
        _positive(self.binding_revision)
        if (type(self.auth_session_digest) is not str
                or not re.fullmatch(r"[a-f0-9]{64}", self.auth_session_digest)):
            raise ControlRejected("invalid_binding")


@dataclass(frozen=True)
class RunBinding:
    run_id: str
    session_id: str
    dispatch_key: str = field(repr=False)

    def __post_init__(self):
        for value in asdict(self).values():
            _identifier(value)


@dataclass(frozen=True)
class HumanLease:
    lease_id: str = field(repr=False)
    owner: OwnerBinding
    request_id: str
    request_revision: int
    expires_at: float
    auth_expires_at: float


@dataclass(frozen=True)
class ActiveCommand:
    command_id: str
    source: Literal["agent", "human"]
    run: RunBinding | None = None
    lease_id: str | None = field(default=None, repr=False)
    sequence: int | None = None


@dataclass(frozen=True)
class InputReceipt:
    lease_id: str = field(repr=False)
    sequence: int
    command_id: str
    outcome: Outcome


@dataclass(frozen=True)
class ControlState:
    identity: BrowserIdentity
    principal_id: str
    mode: Mode
    revision: int
    admitted_run: RunBinding | None
    active_command: ActiveCommand | None = None
    lease: HumanLease | None = None
    takeover_after: str | None = None
    last_sequence: int = 0
    last_input: InputReceipt | None = None
    retired: bool = False
    native_name: str | None = None
    native_pid: int | None = None
    native_started: float | None = None
    current_page: dict | None = None
    previous_page: dict | None = None


@dataclass(frozen=True)
class InputAck:
    identity: BrowserIdentity
    sequence: int
    outcome: Outcome
    execute: bool
    command_id: str
    revision: int


@dataclass(frozen=True)
class FenceObservation:
    """Internal same-channel proof; never deserialize from a web request."""
    identity: BrowserIdentity
    preceding_command_id: str | None
    quiescent: bool


@dataclass(frozen=True)
class RetirementObservation:
    """Internal exact native teardown proof, not inferred from absence."""
    identity: BrowserIdentity
    process_gone: bool
    channel_closed: bool


@dataclass(frozen=True)
class RunTerminalObservation:
    """Internal runtime status proof; never construct from a browser request."""

    run_id: str
    session_id: str
    status: str


@dataclass(frozen=True)
class ActivitySnapshot:
    known: bool
    active_browsers: int
    active_commands: int
    leases: int
    recovering: int

    @property
    def idle(self):
        return self.known and not any((self.active_browsers, self.active_commands,
                                      self.leases, self.recovering))


def _decode(raw):
    value = json.loads(raw)
    value["identity"] = BrowserIdentity(**value["identity"])
    if value["admitted_run"] is not None:
        value["admitted_run"] = RunBinding(**value["admitted_run"])
    if value["active_command"] is not None:
        command = value["active_command"]
        if command["run"] is not None:
            command["run"] = RunBinding(**command["run"])
        value["active_command"] = ActiveCommand(**command)
    if value["lease"] is not None:
        lease = value["lease"]
        lease["owner"] = OwnerBinding(**lease["owner"])
        value["lease"] = HumanLease(**lease)
    if value["last_input"] is not None:
        value["last_input"] = InputReceipt(**value["last_input"])
    return ControlState(**value)


class BrowserController:
    def __init__(self, database_path: str | Path, *,
                 maintenance_held: Callable[[], bool],
                 clock: Callable[[], float] = time.time, lease_seconds: float = 60):
        if (not callable(clock) or not callable(maintenance_held)
                or type(lease_seconds) not in (int, float)
                or not math.isfinite(lease_seconds) or lease_seconds <= 0):
            raise ControlRejected("invalid_configuration")
        if str(database_path) == ":memory:":
            raise ControlRejected("durable_store_required")
        self.database_path = Path(database_path).absolute()
        self.clock, self.lease_seconds = clock, lease_seconds
        self.maintenance_held = maintenance_held
        try:
            descriptor = os.open(self.database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            self._private_store()
        else:
            os.close(descriptor)
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS browser_control_state (
                conversation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                generation TEXT NOT NULL, retired INTEGER NOT NULL CHECK(retired IN (0,1)),
                body TEXT NOT NULL)""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS browser_control_native_session
                ON browser_control_state(session_id) WHERE retired=0""")

    @contextmanager
    def _transaction(self):
        self._private_store()
        db = sqlite3.connect(self.database_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _private_store(self):
        info = self.database_path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ControlRejected("control_store_requires_private_regular_file")

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ControlRejected("clock_unavailable")
        return value

    def _admission(self):
        try:
            held = self.maintenance_held()
        except Exception:
            raise ControlRejected("maintenance_unknown") from None
        if type(held) is not bool:
            raise ControlRejected("maintenance_unknown")
        if held:
            raise ControlRejected("maintenance_held")

    @staticmethod
    def _save(db, state):
        db.execute("""INSERT INTO browser_control_state VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET session_id=excluded.session_id,
                generation=excluded.generation, retired=excluded.retired, body=excluded.body""",
            (*asdict(state.identity).values(), int(state.retired),
             json.dumps(asdict(state), separators=(",", ":"))))

    def _load(self, db, identity):
        record = db.execute("SELECT body FROM browser_control_state WHERE conversation_id=?",
                            (identity.conversation_id,)).fetchone()
        if record is None:
            raise ControlRejected("browser_unknown")
        state = _decode(record["body"])
        if state.identity != identity:
            raise ControlRejected("stale_browser")
        return self._expire(db, state)

    def _expire(self, db, state):
        if state.lease is not None and state.lease.expires_at <= self._now():
            mode = "recovering" if (state.active_command is not None
                                    and state.active_command.source == "human") else "paused"
            state = replace(state, mode=mode, revision=state.revision+1, lease=None)
            self._save(db, state)
        return state

    @staticmethod
    def _owner(state, owner):
        if owner.principal_id != state.principal_id:
            raise ControlRejected("owner_mismatch")

    def _lease(self, state, owner, lease_id, revision):
        self._owner(state, owner)
        if (state.retired or state.mode != "human" or state.lease is None
                or state.lease.owner != owner or state.lease.lease_id != lease_id):
            raise ControlRejected("control_lease_unavailable")
        if type(revision) is not int or revision != state.revision:
            raise ControlRejected("stale_control")

    def bind_browser(
        self,
        identity: BrowserIdentity,
        run: RunBinding | None,
        principal_id: str,
        *,
        native_name=None,
        native_pid=None,
        native_started=None,
    ) -> ControlState:
        """Trusted lifecycle only: caller verifies the actual current native identity.

        No web/model registration, historical generation lookup or native launch.
        A replacement requires positive retirement of the previous generation.
        """
        _identifier(principal_id)
        if run is not None and run.session_id != identity.session_id:
            raise ControlRejected("run_mismatch")
        with self._transaction() as db:
            self._admission()
            claim = db.execute(
                "SELECT conversation_id FROM browser_control_state "
                "WHERE session_id=? AND retired=0",
                (identity.session_id,),
            ).fetchone()
            if (
                claim is not None
                and claim["conversation_id"] != identity.conversation_id
            ):
                raise ControlRejected("native_session_already_bound")
            record = db.execute(
                "SELECT body FROM browser_control_state WHERE conversation_id=?",
                (identity.conversation_id,),
            ).fetchone()
            revision, previous_page = 1, None
            if record is not None:
                existing = self._expire(db, _decode(record["body"]))
                if existing.identity == identity:
                    if existing.retired:
                        raise ControlRejected("browser_retired")
                    if (
                        existing.admitted_run != run
                        or existing.principal_id != principal_id
                    ):
                        raise ControlRejected("run_mismatch")
                    return existing
                if not existing.retired:
                    raise ControlRejected("previous_generation_unresolved")
                if existing.principal_id != principal_id:
                    raise ControlRejected("owner_mismatch")
                revision, previous_page = existing.revision + 1, existing.previous_page
            state = ControlState(
                identity,
                principal_id,
                "agent" if run else "paused",
                revision,
                run,
                native_name=native_name,
                native_pid=native_pid,
                native_started=native_started,
                previous_page=previous_page,
            )
            self._save(db, state)
            return state

    def state(self, identity: BrowserIdentity) -> ControlState:
        with self._transaction() as db:
            return self._load(db, identity)

    def current(
        self, conversation_id: str, session_id: str, principal_id: str
    ) -> ControlState | None:
        """Current owner-scoped state; this read cannot launch or replace a browser."""
        with self._transaction() as db:
            row = db.execute(
                "SELECT body FROM browser_control_state WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return None
            state = self._expire(db, _decode(row["body"]))
            if (
                state.identity.session_id != session_id
                or state.principal_id != principal_id
            ):
                raise ControlRejected("owner_mismatch")
            return state

    def record_page(
        self, identity: BrowserIdentity, current: dict, previous: dict | None
    ) -> None:
        """Bounded, already-redacted URL/title only; no revision or action history."""
        for page in (current, previous):
            if page is not None and (
                type(page) is not dict
                or set(page) != {"url", "title"}
                or any(
                    type(value) is not str or len(value) > 2048
                    for value in page.values()
                )
            ):
                raise ControlRejected("invalid_page_context")
        with self._transaction() as db:
            state = self._load(db, identity)
            if state.retired:
                raise ControlRejected("browser_retired")
            self._save(db, replace(state, current_page=current, previous_page=previous))

    def admit_run(
        self,
        identity: BrowserIdentity,
        owner: OwnerBinding,
        run: RunBinding,
        *,
        lease_id: str | None,
        revision: int,
        previous: RunTerminalObservation | None = None,
    ) -> ControlState:
        """Explicit handback admits a fresh run, never the run paused by takeover."""
        if run.session_id != identity.session_id:
            raise ControlRejected("run_mismatch")
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            if state.mode == "human":
                self._lease(state, owner, lease_id, revision)
            elif state.mode == "agent" and lease_id is None:
                self._owner(state, owner)
                if state.retired or state.revision != revision:
                    raise ControlRejected("stale_control")
            else:
                raise ControlRejected("control_lease_unavailable")
            if state.active_command is not None:
                raise ControlRejected("browser_control_busy")
            old = state.admitted_run
            if old is not None and (
                run.run_id == old.run_id
                or run.dispatch_key == old.dispatch_key
                or not isinstance(previous, RunTerminalObservation)
                or previous.run_id != old.run_id
                or previous.session_id != old.session_id
                or previous.status
                not in {"completed", "failed", "cancelled", "interrupted"}
            ):
                raise ControlRejected("previous_run_not_terminal")
            if old is None and previous is not None:
                raise ControlRejected("run_mismatch")
            state = replace(
                state,
                mode="agent",
                revision=state.revision + 1,
                admitted_run=run,
                lease=None,
                takeover_after=None,
            )
            self._save(db, state)
            return state

    def reserve_agent(self, identity: BrowserIdentity, run: RunBinding,
                      command_id: str) -> ActiveCommand:
        """The trusted executor allocates unique IDs and never resubmits a command."""
        _identifier(command_id)
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            if state.retired or state.admitted_run != run:
                raise ControlRejected("run_mismatch")
            if state.mode != "agent" or state.active_command is not None:
                raise ControlRejected("browser_control_blocked")
            command = ActiveCommand(command_id, "agent", run=run)
            self._save(db, replace(state, active_command=command))
            return command

    def complete_agent(self, identity: BrowserIdentity, run: RunBinding,
                       command_id: str, *, outcome: Literal["completed", "uncertain"]) -> ControlState:
        if outcome not in {"completed", "uncertain"}:
            raise ControlRejected("invalid_outcome")
        with self._transaction() as db:
            state = self._load(db, identity)
            command = state.active_command
            if (command is None or command.source != "agent" or command.run != run
                    or command.command_id != command_id or state.admitted_run != run):
                raise ControlRejected("command_mismatch")
            state = replace(state, active_command=None) if outcome == "completed" else replace(
                state, mode="recovering", revision=state.revision+1, lease=None)
            self._save(db, state)
            return state

    def request_takeover(self, identity: BrowserIdentity, owner: OwnerBinding,
                         request_id: str, *, revision: int, auth_expires_at: float) -> ControlState:
        """Retries retain their original revision; closed requests cannot reopen."""
        _identifier(request_id)
        _positive(revision)
        now = self._now()
        if (type(auth_expires_at) not in (int, float) or not math.isfinite(auth_expires_at)
                or auth_expires_at <= now):
            raise ControlRejected("authentication_expired")
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            self._owner(state, owner)
            if state.lease is not None:
                if (state.lease.owner == owner and state.lease.request_id == request_id
                        and state.lease.request_revision == revision):
                    return state
                raise ControlRejected("browser_control_busy")
            if state.revision != revision:
                raise ControlRejected("stale_control")
            if state.retired or state.mode not in {"agent", "paused"}:
                raise ControlRejected("browser_control_blocked")
            lease = HumanLease(uuid4().hex, owner, request_id, revision,
                min(now+self.lease_seconds, auth_expires_at), auth_expires_at)
            state = replace(state, mode="takeover_pending", revision=state.revision+1,
                lease=lease, takeover_after=state.active_command.command_id if state.active_command else None,
                last_sequence=0)
            self._save(db, state)
            return state

    def confirm_takeover(self, identity: BrowserIdentity, revision: int,
                         observation: FenceObservation) -> ControlState:
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            if (state.mode != "takeover_pending" or state.lease is None
                    or state.active_command is not None or state.revision != revision
                    or not isinstance(observation, FenceObservation)
                    or observation.identity != identity or observation.quiescent is not True
                    or observation.preceding_command_id != state.takeover_after):
                raise ControlRejected("quiescence_unproven")
            state = replace(state, mode="human", revision=state.revision+1, takeover_after=None)
            self._save(db, state)
            return state

    @staticmethod
    def _ack(state, receipt, *, execute=False):
        return InputAck(state.identity, receipt.sequence, receipt.outcome, execute,
                        receipt.command_id, state.revision)

    def reserve_input(self, identity: BrowserIdentity, owner: OwnerBinding,
                      lease_id: str, revision: int, sequence: int) -> InputAck:
        """Persist one sequence/receipt before send; never accepts an input payload."""
        _positive(sequence)
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            self._lease(state, owner, lease_id, revision)
            if (state.last_input is not None and state.last_input.lease_id == lease_id
                    and state.last_input.sequence == sequence):
                return self._ack(state, state.last_input)
            if sequence <= state.last_sequence:
                raise ControlRejected("stale_input")
            if sequence != state.last_sequence+1:
                raise ControlRejected("input_sequence_mismatch")
            if state.active_command is not None:
                raise ControlRejected("browser_control_busy")
            receipt = InputReceipt(lease_id, sequence, uuid4().hex, "reserved")
            command = ActiveCommand(receipt.command_id, "human", lease_id=lease_id, sequence=sequence)
            state = replace(state, active_command=command, last_sequence=sequence, last_input=receipt)
            self._save(db, state)
            return self._ack(state, receipt, execute=True)

    def complete_input(self, identity: BrowserIdentity, lease_id: str, sequence: int,
                       command_id: str, *, outcome: Literal["applied", "rejected", "uncertain"]) -> InputAck:
        """Only a proven pre-send failure is rejected; post-send failure is uncertain."""
        _positive(sequence)
        if outcome not in {"applied", "rejected", "uncertain"}:
            raise ControlRejected("invalid_outcome")
        with self._transaction() as db:
            state = self._load(db, identity)
            receipt = state.last_input
            if (receipt is None or receipt.lease_id != lease_id or receipt.sequence != sequence
                    or receipt.command_id != command_id):
                raise ControlRejected("command_mismatch")
            if receipt.outcome in {"applied", "rejected"}:
                if receipt.outcome != outcome:
                    raise ControlRejected("ack_conflict")
                return self._ack(state, receipt)
            command = state.active_command
            if (command is None or command.source != "human" or command.command_id != command_id
                    or command.lease_id != lease_id or command.sequence != sequence):
                raise ControlRejected("command_mismatch")
            receipt = replace(receipt, outcome=outcome)
            state = replace(state, last_input=receipt)
            state = replace(state, mode="recovering", revision=state.revision+1, lease=None) if (
                outcome == "uncertain") else replace(state, active_command=None)
            self._save(db, state)
            return self._ack(state, receipt)

    def heartbeat(
        self,
        identity: BrowserIdentity,
        owner: OwnerBinding,
        lease_id: str,
        revision: int,
        *,
        auth_expires_at: float | None = None,
    ) -> ControlState:
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            self._lease(state, owner, lease_id, revision)
            if auth_expires_at is not None:
                if (
                    type(auth_expires_at) not in (int, float)
                    or not math.isfinite(auth_expires_at)
                    or auth_expires_at <= self._now()
                ):
                    raise ControlRejected("authentication_expired")
                state = replace(
                    state, lease=replace(state.lease, auth_expires_at=auth_expires_at)
                )
            lease = replace(
                state.lease,
                expires_at=min(
                    self._now() + self.lease_seconds, state.lease.auth_expires_at
                ),
            )
            state = replace(state, lease=lease)
            self._save(db, state)
            return state

    def begin_return(self, identity: BrowserIdentity, owner: OwnerBinding,
                     lease_id: str, revision: int) -> ControlState:
        """Revoke into paused; fresh follow-up admission belongs to integration."""
        with self._transaction() as db:
            state = self._load(db, identity)
            self._lease(state, owner, lease_id, revision)
            state = replace(state, mode="paused", revision=state.revision+1, lease=None)
            self._save(db, state)
            return state

    def presence(
        self, identity: BrowserIdentity, owner: OwnerBinding, revision: int
    ) -> ControlState:
        """Authenticated observation keeps a quiescent browser alive; no authority transfer."""
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            self._owner(state, owner)
            if (
                state.retired
                or state.mode not in {"agent", "paused"}
                or state.revision != revision
            ):
                raise ControlRejected("stale_control")
            return state

    def begin_close(
        self,
        identity: BrowserIdentity,
        owner: OwnerBinding,
        revision: int,
        previous: RunTerminalObservation | None = None,
    ) -> ControlState:
        """Explicit owner close of an inactive browser, never an active agent command."""
        with self._transaction() as db:
            self._admission()
            state = self._load(db, identity)
            self._owner(state, owner)
            if (
                state.retired
                or state.mode not in {"agent", "paused"}
                or state.revision != revision
                or state.active_command is not None
            ):
                raise ControlRejected("browser_control_busy")
            old = state.admitted_run
            if old is not None and (
                not isinstance(previous, RunTerminalObservation)
                or previous.run_id != old.run_id
                or previous.session_id != old.session_id
                or previous.status
                not in {"completed", "failed", "cancelled", "interrupted"}
            ):
                raise ControlRejected("previous_run_not_terminal")
            state = replace(
                state, mode="paused", revision=state.revision + 1, lease=None
            )
            self._save(db, state)
            return state

    def live_states(self) -> list[ControlState]:
        with self._transaction() as db:
            return [
                self._expire(db, _decode(row["body"]))
                for row in db.execute(
                    "SELECT body FROM browser_control_state WHERE retired=0"
                ).fetchall()
            ]

    def pause(self, identity: BrowserIdentity, owner: OwnerBinding) -> ControlState:
        """Existing authentication logout/disconnect of the exact controller tab."""
        with self._transaction() as db:
            state = self._load(db, identity)
            self._owner(state, owner)
            if state.lease is None or state.lease.owner != owner:
                raise ControlRejected("control_lease_unavailable")
            state = replace(state, mode="paused", revision=state.revision+1, lease=None)
            self._save(db, state)
            return state

    def recover_startup(self) -> None:
        """Exclusive runtime startup, not every construction of a DB client."""
        with self._transaction() as db:
            for record in db.execute(
                "SELECT body FROM browser_control_state"
            ).fetchall():
                state = _decode(record["body"])
                if state.retired:
                    continue
                if state.active_command is not None:
                    receipt = state.last_input
                    if receipt is not None and receipt.outcome == "reserved":
                        receipt = replace(receipt, outcome="uncertain")
                    self._save(
                        db,
                        replace(
                            state,
                            mode="recovering",
                            revision=state.revision + 1,
                            lease=None,
                            last_input=receipt,
                        ),
                    )
                elif state.mode in {"agent", "human", "takeover_pending"}:
                    self._save(
                        db,
                        replace(
                            state,
                            mode="paused",
                            revision=state.revision + 1,
                            lease=None,
                        ),
                    )

    def retire_browser(
        self, identity: BrowserIdentity, observation: RetirementObservation
    ) -> ControlState:
        """Trusted positive native retirement closes current ownership and input."""
        if (
            not isinstance(observation, RetirementObservation)
            or observation.identity != identity
            or observation.process_gone is not True
            or observation.channel_closed is not True
        ):
            raise ControlRejected("retirement_unproven")
        with self._transaction() as db:
            state = self._load(db, identity)
            if state.retired:
                return state
            receipt = state.last_input
            if receipt is not None and receipt.outcome == "reserved":
                receipt = replace(receipt, outcome="uncertain")
            state = replace(
                state,
                mode="paused",
                revision=state.revision + 1,
                admitted_run=None,
                active_command=None,
                lease=None,
                takeover_after=None,
                last_input=receipt,
                retired=True,
                current_page=None,
                previous_page=state.current_page or state.previous_page,
            )
            self._save(db, state)
            return state

    def activity_snapshot(self, observed_identities: Iterable[BrowserIdentity]) -> ActivitySnapshot:
        """Committed state for existing maintenance; missing native identity is unknown."""
        with self._transaction() as db:
            observed = set(observed_identities)
            if any(not isinstance(identity, BrowserIdentity) for identity in observed):
                raise ControlRejected("invalid_observation")
            states = [self._expire(db, _decode(row["body"]))
                      for row in db.execute("SELECT body FROM browser_control_state").fetchall()]
            known = all((state.identity not in observed if state.retired else state.identity in observed)
                        for state in states)
            live = [state for state in states if not state.retired]
            return ActivitySnapshot(known, len(observed),
                sum(state.active_command is not None for state in live),
                sum(state.lease is not None for state in live),
                sum(state.mode == "recovering" for state in live))
