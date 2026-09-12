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
from radhouse.application.ports import AgentWorkPort, ProviderPort, Store, UnitOfWork
from radhouse.application.views import ActionView, TaskCard, WorkHome
from radhouse.domain.access import AuthContext, require_access, require_assurance
from radhouse.domain.releases import Publication, Review, digest, validate_review
from radhouse.domain.tasks import (AgentDispatch, Attempt, Delivery, Event,
    Observation, ProviderDescription, Rejected, RuntimeCapabilities, RuntimeDispatch,
    RuntimeFailure, RuntimeResult, SavedCommand, StartTask, Task)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Service:
    def __init__(self, store: Store, work: AgentWorkPort, provider: ProviderPort,
                 clock: Callable[[], datetime]):
        self.store, self.work, self.provider, self.clock = store, work, provider, clock

    def _now(self) -> datetime:
        value = self.clock()
        if value.utcoffset() is None:
            raise RuntimeFailure("runtime_clock_invalid")
        return value

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

    def coordination_candidates(self, limit: int) -> tuple[str, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid_coordination_limit")
        held = {"human_pause", "grant_withdrawal", "budget_exhausted"}
        with self.store.transaction() as tx:
            tasks = tx.tasks()
        return tuple(
            task.task_id for task in tasks
            if task.phase != "closed"
            and (task.phase == "stopping" or not set(task.blockers) & held)
        )[:limit]

    def advance(self, task_id: str, worker_id: str) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
        if task.phase == "closed":
            return task
        if task.phase == "queued":
            return self.run(task_id, worker_id)
        return self.recover(task_id)

    def work_home(self, actor: AuthContext, *, envelope: Envelope) -> WorkHome:
        with self.store.transaction() as tx:
            access = tx.access(actor.principal_id)
            binding = tx.binding(actor.channel, actor.subject, envelope.conversation_id)
            if binding is None:
                raise Rejected("binding_denied", 403)
            self._binding(tx, actor, envelope, binding.project_id)
            if access is None or not access.active or binding.project_id not in access.projects:
                raise Rejected("access_denied", 403)
            agents = tuple(tx.bots(actor.principal_id))
            tasks = tuple(
                task for task in tx.tasks()
                if task.owner_id == actor.principal_id and task.project_id == binding.project_id
            )

        can_write = access.role in {"admin", "operator"}
        start = ActionView(
            can_write and bool(agents),
            None if can_write and agents else "read_only_role" if not can_write else "no_assigned_agents",
        )

        def action(enabled: bool, reason: str) -> ActionView:
            if not can_write:
                return ActionView(False, "read_only_role")
            return ActionView(enabled, None if enabled else reason)

        cards = []
        for task in tasks:
            paused = "human_pause" in task.blockers
            cancellable = task.phase != "closed" and "cancel_requested" not in task.blockers
            pausable = task.phase in {"active", "recovering"} and not paused and cancellable
            resumable = paused and task.phase not in {"closed", "stopping"}
            reviewable = task.outcome == "completed" and task.result is not None
            if not can_write:
                review = ActionView(False, "read_only_role")
            elif reviewable and (actor.assurance_until is None or actor.assurance_until <= self._now()):
                review = ActionView(False, "fresh_assurance_required")
            else:
                review = action(reviewable, "result_not_ready")
            cards.append(TaskCard(
                task,
                action(cancellable, "task_closed"),
                action(pausable, "task_not_pausable"),
                action(resumable, "task_not_paused"),
                review,
            ))
        return WorkHome(
            actor.principal_id, access.role, binding.project_id, agents, tuple(cards), start,
        )

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
            if before.phase == "closed":
                return before
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
            session_id = task.task_id
            request_digest = fingerprint({"input": task.brief, "session_id": session_id})
            tx.save_dispatch(AgentDispatch(
                attempt.attempt_id, task.task_id, attempt.attempt_id, session_id,
                task.provider_binding, request_digest, "prepared",
            ))
            return self._save(tx, task, updated, "claimed")

    def run(self, task_id: str, worker_id: str = "worker") -> Task:
        claimed = self.claim(task_id, worker_id)
        if claimed.phase != "active":
            return claimed
        return self._drive(task_id, worker_id)

    @staticmethod
    def _runtime_dispatch(dispatch: AgentDispatch) -> RuntimeDispatch:
        if (
            dispatch.run_id is None
            or dispatch.runtime_revision is None
            or dispatch.submitted_at is None
            or dispatch.retention_until is None
        ):
            raise Rejected("task_state_inconsistent")
        return RuntimeDispatch(
            dispatch.run_id, dispatch.session_id, dispatch.provider_binding,
            dispatch.runtime_revision, dispatch.submitted_at, dispatch.retention_until,
        )

    def _needs_attention(self, task_id: str, dispatch_key: str) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            dispatch = tx.dispatch(dispatch_key)
            if dispatch is None:
                raise Rejected("missing_dispatch")
            if dispatch.state in {"submitted", "prepared"}:
                tx.save_dispatch(replace(dispatch, state="unknown"))
            blockers = tuple(sorted(set(task.blockers) | {"operation_unknown"}))
            phase = (
                "stopping"
                if task.phase == "stopping" or "cancel_requested" in blockers
                else "recovering"
            )
            if (task.phase, task.blockers) == (phase, blockers):
                return task
            return self._save(tx, task, task.evolve(
                blockers=blockers, phase=phase), "needs_attention")

    def _runtime_unavailable(self, task_id: str) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            blockers = tuple(sorted(set(task.blockers) | {"runtime_unavailable"}))
            if blockers == task.blockers and task.phase == "recovering":
                return task
            return self._save(tx, task, task.evolve(
                blockers=blockers, phase="recovering"), "runtime_unavailable")

    @staticmethod
    def _validate_capabilities(capabilities: RuntimeCapabilities) -> None:
        if (
            not capabilities.runtime_revision
            or not 1 <= capabilities.idempotency_retention_seconds <= 31 * 24 * 60 * 60
        ):
            raise RuntimeFailure("runtime_idempotency_unavailable")

    def _drive(self, task_id: str, worker_id: str | None) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            if task.attempt_id is None:
                raise Rejected("task_state_inconsistent")
            attempt = tx.attempt(task.attempt_id)
            dispatch = tx.dispatch(task.attempt_id)
            if attempt is None or dispatch is None or dispatch.attempt_id != attempt.attempt_id:
                raise Rejected("task_state_inconsistent")
            if worker_id is not None and attempt.worker_id != worker_id:
                return task
            expected_digest = fingerprint({
                "input": task.brief, "session_id": dispatch.session_id,
            })
            if dispatch.request_digest != expected_digest:
                blockers = tuple(sorted(set(task.blockers) | {"operation_unknown"}))
                phase = "stopping" if task.phase == "stopping" else "recovering"
                return self._save(tx, task, task.evolve(
                    phase=phase, blockers=blockers), "needs_attention")
            dispatch_blockers = set(task.blockers) - {
                "operation_unknown", "runtime_stop", "runtime_unavailable",
            }
            if dispatch_blockers and task.phase != "stopping" and dispatch.state != "accepted":
                return task
            try:
                require_access(tx.access(task.owner_id), task.bot_id, task.project_id, write=True)
            except Rejected:
                blockers = tuple(sorted(set(task.blockers) | {"grant_withdrawal"}))
                if dispatch.state != "accepted":
                    if blockers == task.blockers:
                        return task
                    return self._save(tx, task, task.evolve(blockers=blockers), "waiting")
                if task.phase != "stopping" or blockers != task.blockers:
                    task = self._save(tx, task, task.evolve(
                        phase="stopping", blockers=blockers), "stop_requested")
            stop_blockers = {
                "provider_mismatch", "provider_unavailable", "provider_incompatible",
                "grant_withdrawal", "human_pause", "cancel_requested",
            }
            if (
                dispatch.state == "accepted"
                and set(task.blockers) & stop_blockers
                and task.phase != "stopping"
            ):
                task = self._save(tx, task, task.evolve(phase="stopping"), "stop_requested")

        if dispatch.state == "prepared":
            try:
                capabilities = self.work.capabilities()
                self._validate_capabilities(capabilities)
            except RuntimeFailure:
                return self._runtime_unavailable(task_id)
            submitted_at = self._now()
            retention_until = submitted_at + timedelta(
                seconds=capabilities.idempotency_retention_seconds
            )
            with self.store.transaction() as tx:
                current = self._task(tx, task_id)
                latest = tx.dispatch(dispatch.key)
                if current.phase == "closed":
                    return current
                if latest is None:
                    raise Rejected("missing_dispatch")
                if latest.state == "prepared":
                    dispatch = replace(
                        latest, state="submitted",
                        runtime_revision=capabilities.runtime_revision,
                        submitted_at=submitted_at, retention_until=retention_until,
                    )
                    tx.save_dispatch(dispatch)
                else:
                    dispatch = latest

        if dispatch.state in {"submitted", "unknown"}:
            if dispatch.retention_until is None or self._now() >= dispatch.retention_until:
                return self._needs_attention(task_id, dispatch.key)
            try:
                accepted = self.work.start_or_attach(task, attempt, dispatch.key)
            except RuntimeFailure:
                return self._needs_attention(task_id, dispatch.key)
            response_mismatch = (
                accepted.session_id != dispatch.session_id
                or accepted.provider_binding != dispatch.provider_binding
                or accepted.runtime_revision != dispatch.runtime_revision
            )
            with self.store.transaction() as tx:
                current = self._task(tx, task_id)
                latest = tx.dispatch(dispatch.key)
                if current.phase == "closed":
                    return current
                if latest is None:
                    raise Rejected("missing_dispatch")
                if latest.state == "accepted" and latest.run_id != accepted.run_id:
                    blockers = tuple(sorted(set(current.blockers) | {"operation_unknown"}))
                    return self._save(tx, current, current.evolve(
                        phase="recovering", blockers=blockers), "needs_attention")
                if latest.state != "accepted":
                    dispatch = replace(latest, state="accepted", run_id=accepted.run_id)
                    tx.save_dispatch(dispatch)
                else:
                    dispatch = latest
            if response_mismatch:
                return self._needs_attention(task_id, dispatch.key)

        if dispatch.state == "closed":
            with self.store.transaction() as tx:
                return self._task(tx, task_id)
        if dispatch.state != "accepted":
            return self._needs_attention(task_id, dispatch.key)
        runtime_dispatch = self._runtime_dispatch(dispatch)
        with self.store.transaction() as tx:
            current = self._task(tx, task_id)
        if current.phase == "stopping":
            try:
                if not self.work.stop(runtime_dispatch):
                    return self._needs_attention(task_id, dispatch.key)
            except RuntimeFailure:
                return self._needs_attention(task_id, dispatch.key)
        try:
            result = self.work.result(runtime_dispatch)
        except RuntimeFailure:
            return self._needs_attention(task_id, dispatch.key)
        if result.state == "unknown":
            return self._needs_attention(task_id, dispatch.key)
        if result.state == "running":
            with self.store.transaction() as tx:
                current = self._task(tx, task_id)
                if current.phase == "closed" or current.phase == "stopping":
                    return current
                blockers = tuple(x for x in current.blockers if x not in {
                    "operation_unknown", "runtime_stop", "runtime_unavailable",
                })
                if (current.phase, current.blockers) == ("active", blockers):
                    return current
                return self._save(tx, current, current.evolve(
                    phase="active", blockers=blockers), "runtime_running")
        return self._finish_work(task_id, dispatch.key, result)

    def _finish_work(self, task_id: str, dispatch_key: str, result: RuntimeResult) -> Task:
        content = result.content if result.state == "completed" else None
        if result.state == "completed" and content is None:
            return self._needs_attention(task_id, dispatch_key)
        if content is not None and len(content.encode()) > 65536:
            raise Rejected("result_too_large")
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            dispatch = tx.dispatch(dispatch_key)
            if dispatch is None or dispatch.state != "accepted" or task.attempt_id != dispatch.attempt_id:
                raise Rejected("task_state_inconsistent")
            tx.save_dispatch(replace(dispatch, state="closed"))
            tx.finish_attempt(dispatch.attempt_id)
            blockers = set(task.blockers) - {
                "operation_unknown", "runtime_stop", "runtime_unavailable",
            }
            if result.state == "cancelled" and "human_pause" in blockers and "cancel_requested" not in blockers:
                return self._save(tx, task, task.evolve(
                    phase="queued", attempt_id=None, blockers=tuple(sorted(blockers))), "paused")
            terminal = (
                "cancelled" if "cancel_requested" in blockers
                else "completed" if result.state == "completed"
                else "failed"
            )
            updated = task.evolve(
                phase="closed", outcome=terminal, blockers=tuple(sorted(blockers)),
                result=content, result_digest=digest(content) if content is not None else None,
            )
            return self._save(tx, task, updated, terminal)

    def recover(self, task_id: str) -> Task:
        with self.store.transaction() as tx:
            task = self._task(tx, task_id)
            if task.phase == "closed":
                return task
            if task.attempt_id is None:
                return task
        return self._drive(task_id, None)

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
            dispatch = tx.dispatch(task.attempt_id) if task.attempt_id else None
        if attempt is None:
            stopped, exact_run = True, False
        elif dispatch is None:
            raise Rejected("missing_dispatch")
        elif dispatch.state == "prepared":
            stopped, exact_run = True, False
        elif dispatch.state == "accepted":
            exact_run = True
            try:
                stopped = self.work.stop(self._runtime_dispatch(dispatch))
            except RuntimeFailure:
                stopped = False
        elif dispatch.state == "closed":
            stopped, exact_run = True, True
        else:
            stopped, exact_run = False, False
        with self.store.transaction() as tx:
            current = self._task(tx, task_id)
            if current.phase == "closed":
                return current
            latest = tx.dispatch(current.attempt_id) if current.attempt_id else None
            if not stopped:
                blocker = "runtime_stop" if exact_run else "operation_unknown"
                return self._save(tx, current, current.evolve(phase="stopping",
                    blockers=tuple(sorted(set(current.blockers) | {blocker}))), "needs_attention")
            if exact_run and latest is not None and latest.state == "accepted":
                return current  # Stop accepted; recovery confirms the terminal run state.
            if reason == "cancel_requested":
                if attempt:
                    tx.finish_attempt(attempt.attempt_id)
                if latest is not None:
                    tx.save_dispatch(replace(latest, state="closed"))
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
