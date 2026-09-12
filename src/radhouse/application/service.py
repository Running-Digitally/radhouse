"""One authority and durable task path for every operator channel.

Transactions end before adapter calls. An uncertain dispatch is reconciled by
its original key; absence of evidence never creates another effect attempt.
"""
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from collections.abc import Callable, Sequence
import hashlib
import json
from uuid import uuid4

from radhouse.channels.mapping import verify_envelope
from radhouse.channels.commands import Envelope
from radhouse.application.ports import OperationsPort, ProviderPort, RuntimePort, Store, UnitOfWork
from radhouse.domain.access import AuthContext, require_access, require_assurance
from radhouse.domain.releases import Publication, Review, digest, validate_review
from radhouse.domain.tasks import (Attempt, Delivery, Event, LostReply, Operation,
    EffectResult, Observation, ProviderDescription, Rejected, SavedCommand, StartTask, Task)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Service:
    def __init__(self, store: Store, runtime: RuntimePort, provider: ProviderPort,
                 operations: OperationsPort, clock: Callable[[], datetime]):
        self.store, self.runtime, self.provider = store, runtime, provider
        self.operations, self.clock = operations, clock

    @staticmethod
    def _task(tx: UnitOfWork, task_id: str) -> Task:
        task = tx.task(task_id)
        if task is None:
            raise Rejected("task_not_found", 404)
        return task

    def _authorize(self, tx: UnitOfWork, actor: AuthContext, task: Task,
                   envelope: Envelope, *, write: bool = False) -> None:
        require_access(tx.access(actor.principal_id), task.bot_id, task.project_id, write=write)
        # Project membership alone does not release a private task's history.
        if task.owner_id != actor.principal_id:
            raise Rejected("private_task", 403)
        self._binding(tx, actor, envelope, task.project_id)

    @staticmethod
    def _binding(tx: UnitOfWork, actor: AuthContext, envelope: Envelope, project_id: str) -> None:
        binding = tx.binding(actor.channel, actor.subject, envelope.conversation_id)
        verify_envelope(actor, envelope, binding, project_id)

    @staticmethod
    def _save(tx: UnitOfWork, old: Task, new: Task, kind: str) -> Task:
        tx.save_task(new, old.state_revision)
        tx.add_event(Event(new.task_id, kind, new.state_revision))
        return new

    @staticmethod
    def _expected(task: Task, expected: int) -> None:
        if task.state_revision != expected:
            raise Rejected("stale_state")

    def admit(self, actor: AuthContext, envelope: Envelope, start: StartTask) -> Task:
        if not start.brief.strip() or len(start.brief) > 4096 or not 1 <= start.budget <= 100:
            raise Rejected("invalid_task", 422)
        body = asdict(start)
        identity = fingerprint(body)
        event_identity = fingerprint({"kind": "start", "key": envelope.command_key, "body": body})
        with self.store.transaction() as tx:
            require_access(tx.access(actor.principal_id), start.bot_id, start.project_id, write=True)
            self._binding(tx, actor, envelope, start.project_id)
            delivery = tx.delivery(envelope.channel, envelope.event_id)
            if delivery:
                if delivery.principal_id != actor.principal_id or delivery.fingerprint != event_identity:
                    raise Rejected("delivery_conflict")
                task = self._task(tx, delivery.task_id)
                self._authorize(tx, actor, task, envelope, write=True)
                return task
            old = tx.command(actor.principal_id, envelope.command_key)
            if old:
                if old.fingerprint != identity:
                    raise Rejected("command_conflict")
                task = self._task(tx, old.task_id)
                self._authorize(tx, actor, task, envelope, write=True)
            else:
                task = Task(str(uuid4()), actor.principal_id, start.bot_id, start.project_id,
                            start.brief, start.provider_binding, start.resource_key, start.budget)
                tx.insert_task(task)
                tx.save_command(SavedCommand(actor.principal_id, envelope.command_key, identity, task.task_id))
                tx.add_event(Event(task.task_id, "admitted", task.state_revision))
            tx.save_delivery(Delivery(envelope.channel, envelope.event_id, actor.principal_id,
                                      event_identity, task.task_id, "start"))
            return task

    def get(self, actor: AuthContext, task_id: str, *, envelope: Envelope) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            self._authorize(tx, actor, task, envelope)
            return task

    @staticmethod
    def _provider_state(task: Task, description: ProviderDescription) -> tuple[tuple[str, ...], str | None]:
        blockers = set(task.blockers) - {"provider_unavailable", "provider_incompatible", "provider_mismatch"}
        if description.binding != task.provider_binding:
            blockers.add("provider_mismatch")
        elif not description.available:
            blockers.add("provider_unavailable")
        elif not description.compatible:
            blockers.add("provider_incompatible")
        model = description.model_id if description.available and description.binding == task.provider_binding else task.model_id
        return tuple(sorted(blockers)), model

    def refresh_provider(self, task_id: str) -> Task:
        with self.store.transaction() as tx:
            before = self._task(tx, task_id)
        description = self.provider.describe(before.provider_binding)
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            blockers, model = self._provider_state(task, description)
            if (blockers, model) == (task.blockers, task.model_id):
                return task
            return self._save(tx, task, task.evolve(blockers=blockers, model_id=model), "provider_observed")

    def claim(self, task_id: str, worker_id: str) -> Task:
        self.refresh_provider(task_id)
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase != "queued":
                return task
            blockers = set(task.blockers) - {"resource_busy"}
            try:
                require_access(tx.access(task.owner_id), task.bot_id, task.project_id, write=True)
            except Rejected:
                blockers.add("grant_withdrawal")
            if task.budget_remaining <= 0:
                blockers.add("budget_exhausted")
            if blockers:
                if tuple(sorted(blockers)) == task.blockers:
                    return task
                return self._save(tx, task, task.evolve(blockers=tuple(sorted(blockers))), "waiting")
            attempt = Attempt(str(uuid4()), task.task_id, task.generation + 1, worker_id)
            if not tx.claim(task, attempt):
                return self._save(tx, task, task.blocked("resource_busy"), "waiting")
            updated = task.evolve(phase="active", attempt_id=attempt.attempt_id,
                                  generation=attempt.generation, budget_remaining=task.budget_remaining - 1,
                                  blockers=(), observation_sequence=0)
            tx.save_operation(Operation(task.task_id + ":report", task.task_id, attempt.attempt_id, "prepared"))
            return self._save(tx, task, updated, "claimed")

    def run(self, task_id: str, worker_id: str = "worker") -> Task:
        claimed = self.claim(task_id, worker_id)
        if claimed.phase != "active":
            return claimed
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            attempt = tx.attempt(task.attempt_id)
            operation = tx.operation(task.task_id + ":report")
            if task.phase != "active" or task.blockers or attempt.worker_id != worker_id or operation.state != "prepared":
                return task
            try:
                require_access(tx.access(task.owner_id), task.bot_id, task.project_id, write=True)
            except Rejected:
                return self._save(tx, task, task.blocked("grant_withdrawal"), "waiting")
            tx.save_operation(replace(operation, state="submitted"))
        try:
            self.runtime.start_or_attach(task, attempt, attempt.attempt_id)
            result = self.operations.execute(task, operation.key)
        except (LostReply, TimeoutError, ConnectionError):
            with self.store.transaction() as tx:
                current = self._task(tx, task_id)
                op = tx.operation(operation.key)
                if op.state != "confirmed":
                    tx.save_operation(replace(op, state="unknown"))
                if current.phase == "closed":
                    return current
                return self._save(tx, current, current.evolve(
                    blockers=tuple(sorted(set(current.blockers) | {"operation_unknown"})),
                    phase="stopping" if "cancel_requested" in current.blockers else "recovering"), "needs_attention")
        return self._finish_effect(task_id, result)

    def _finish_effect(self, task_id: str, result: EffectResult) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            operation = tx.operation(task.task_id + ":report")
            if operation is None:
                raise Rejected("missing_operation")
            if result.state == "confirmed" and result.result is not None:
                if len(result.result.encode()) > 65536:
                    raise Rejected("result_too_large")
                tx.save_operation(replace(operation, state="confirmed", result=result.result))
            elif result.state == "rejected":
                tx.save_operation(replace(operation, state="rejected"))
            else:
                if task.phase == "closed":
                    return task
                tx.save_operation(replace(operation, state="unknown"))
                return self._save(tx, task, task.evolve(
                    phase="stopping" if "cancel_requested" in task.blockers else "recovering",
                    blockers=tuple(sorted(set(task.blockers) | {"operation_unknown"}))), "needs_attention")
            attempt = tx.attempt(task.attempt_id)
        stopped = self.runtime.stop(attempt)
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            op = tx.operation(task.task_id + ":report")
            blockers = set(task.blockers) - {"operation_unknown", "runtime_stop"}
            if not stopped:
                blockers.add("runtime_stop")
                return self._save(tx, task, task.evolve(phase="stopping", blockers=tuple(sorted(blockers))), "stopping")
            tx.finish_attempt(task.attempt_id)
            cancelled = "cancel_requested" in blockers
            terminal = "cancelled" if cancelled else "completed" if op.state == "confirmed" else "failed"
            updated = task.evolve(phase="closed", outcome=terminal, blockers=tuple(sorted(blockers)),
                                  result=op.result, result_digest=digest(op.result) if op.result is not None else None)
            return self._save(tx, task, updated, terminal)

    def recover(self, task_id: str) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            operation = tx.operation(task.task_id + ":report")
            if operation is None or operation.state == "prepared":
                return task  # No proof authorizes another external dispatch.
        return self._finish_effect(task_id, self.operations.lookup(operation.key))

    def _hold(self, actor: AuthContext, task_id: str, expected_state_revision: int,
              envelope: Envelope, reason: str) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            self._authorize(tx, actor, task, envelope, write=True)
            self._expected(task, expected_state_revision)
            if task.phase == "closed":
                return task
            blockers = tuple(sorted(set(task.blockers) | {reason}))
            task = self._save(tx, task, task.evolve(blockers=blockers,
                              phase="stopping" if task.attempt_id else task.phase), "stop_requested")
            attempt = tx.attempt(task.attempt_id) if task.attempt_id else None
            operation = tx.operation(task.task_id + ":report")
        stopped = self.runtime.stop(attempt) if attempt else True
        with self.store.transaction() as tx:
            current = self._task(tx, task_id)
            if current.phase == "closed":
                return current
            op = tx.operation(task.task_id + ":report")
            if not stopped or (op and op.state in {"submitted", "unknown"}):
                blocker = "runtime_stop" if not stopped else "operation_unknown"
                return self._save(tx, current, current.evolve(phase="stopping",
                    blockers=tuple(sorted(set(current.blockers) | {blocker}))), "needs_attention")
            if reason == "cancel_requested":
                if attempt:
                    tx.finish_attempt(attempt.attempt_id)
                return self._save(tx, current, current.evolve(phase="closed", outcome="cancelled"), "cancelled")
            # A prepared attempt retains its resource reservation while paused.
            # Resume uses the same owner, budget reservation and operation key.
            return self._save(tx, current, current.evolve(phase="active" if attempt else "queued"), "paused")

    def cancel(self, actor: AuthContext, task_id: str, expected_state_revision: int, *, envelope: Envelope) -> Task:
        return self._hold(actor, task_id, expected_state_revision, envelope, "cancel_requested")

    def pause(self, actor: AuthContext, task_id: str, expected_state_revision: int, *, envelope: Envelope) -> Task:
        return self._hold(actor, task_id, expected_state_revision, envelope, "human_pause")

    def resume(self, actor: AuthContext, task_id: str, expected_state_revision: int, *, envelope: Envelope) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            self._authorize(tx, actor, task, envelope, write=True)
            self._expected(task, expected_state_revision)
            if task.phase in {"closed", "stopping"} or "cancel_requested" in task.blockers:
                raise Rejected("cannot_resume")
            blockers = tuple(x for x in task.blockers if x not in {"human_pause", "grant_withdrawal"})
            return self._save(tx, task, task.evolve(blockers=blockers), "human_resumed")

    def observe(self, observation: Observation) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, observation.task_id)
            if task.phase == "closed" or (observation.attempt_id, observation.generation) != (task.attempt_id, task.generation):
                return task
            if observation.sequence <= task.observation_sequence:
                return task
            # Runtime events cannot assert an effect, publication or final task outcome.
            return self._save(tx, task, task.evolve(observation_sequence=observation.sequence), "runtime_observed")

    @staticmethod
    def _audience(tx: UnitOfWork, task: Task, audience: Sequence[str]) -> tuple[str, ...]:
        audience = tuple(sorted(set(audience)))
        if not audience or len(audience) > 32:
            raise Rejected("invalid_audience", 422)
        for member in audience:
            require_access(tx.access(member), task.bot_id, task.project_id, write=False)
        return audience

    def prepare_review(self, actor: AuthContext, task_id: str, expected_state_revision: int,
                       audience: Sequence[str], ttl_seconds: int = 300, *, envelope: Envelope) -> Review:
        if not 1 <= ttl_seconds <= 300:
            raise Rejected("invalid_review_lifetime", 422)
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            self._authorize(tx, actor, task, envelope, write=True)
            self._expected(task, expected_state_revision)
            require_assurance(actor, self.clock())
            if task.outcome != "completed" or task.result is None:
                raise Rejected("result_not_ready")
            review = Review(str(uuid4()), task.task_id, actor.principal_id, task.result_digest,
                            self._audience(tx, task, audience), task.task_revision, task.state_revision,
                            self.clock() + timedelta(seconds=ttl_seconds))
            tx.save_review(review)
            return review

    def publish(self, actor: AuthContext, envelope: Envelope, review_id: str,
                expected_revision: int, content: str, audience: Sequence[str]) -> Publication:
        with self.store.transaction() as tx:
            review = tx.review(review_id)
            if review is None:
                raise Rejected("review_not_found", 404)
            task = self._task(tx, review.task_id)
            self._authorize(tx, actor, task, envelope, write=True)
            require_assurance(actor, self.clock())
            if review.reviewer_id != actor.principal_id:
                raise Rejected("wrong_reviewer", 403)
            audience = self._audience(tx, task, audience)
            identity = fingerprint({"kind": "publish", "review_id": review_id, "revision": expected_revision,
                                    "digest": digest(content), "audience": audience, "key": envelope.command_key})
            command = tx.command(actor.principal_id, envelope.command_key)
            if command and (command.fingerprint != identity or command.task_id != task.task_id):
                raise Rejected("command_conflict")
            delivery = tx.delivery(envelope.channel, envelope.event_id)
            existing = tx.publication(task.task_id)
            if delivery:
                if delivery.principal_id != actor.principal_id or delivery.fingerprint != identity or existing is None:
                    raise Rejected("delivery_conflict")
                return existing
            if existing:
                if existing.review_id != review_id or existing.digest != digest(content) or existing.audience != audience or expected_revision != review.revision - 1:
                    raise Rejected("publication_conflict")
            else:
                validate_review(review, content, audience, expected_revision, self.clock())
                if (review.task_revision, review.state_revision, review.digest) != (task.task_revision, task.state_revision, task.result_digest):
                    raise Rejected("review_task_changed")
                existing = Publication(str(uuid4()), task.task_id, review_id, review.digest,
                                       audience, content, envelope.channel)
                tx.publish(existing)
                tx.save_review(replace(review, state="approved", revision=review.revision + 1))
                tx.add_event(Event(task.task_id, "published", task.state_revision))
            if command is None:
                tx.save_command(SavedCommand(actor.principal_id, envelope.command_key, identity, task.task_id))
            tx.save_delivery(Delivery(envelope.channel, envelope.event_id, actor.principal_id,
                                      identity, task.task_id, "publish"))
            return existing

    def get_publication(self, actor: AuthContext, task_id: str, *, envelope: Envelope) -> Publication:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            self._binding(tx, actor, envelope, task.project_id)
            publication = tx.publication(task_id)
            require_access(tx.access(actor.principal_id), task.bot_id, task.project_id, write=False)
            if publication is None or actor.principal_id not in publication.audience:
                raise Rejected("publication_denied", 403)
            return publication

    def events(self, actor: AuthContext, task_id: str, after: int = 0, *, envelope: Envelope) -> dict:
        if after < 0:
            raise Rejected("invalid_cursor", 422)
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            self._authorize(tx, actor, task, envelope)
            events = tx.events(task_id, after)
            cursor = events[-1].cursor if events else after
            return {"task": task, "events": events, "cursor": cursor,
                    "resync_required": bool(events and after and events[0].cursor > after + 1)}
