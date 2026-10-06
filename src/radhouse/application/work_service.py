"""Channel-independent admission, verification and authorized outcome projections."""
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from radhouse.domain.tasks import Rejected, StartTask, Task
from radhouse.domain.work import (
    ArtifactManifest, VerificationReceipt, WorkBlocker, WorkItem, content_digest,
    parse_result, runtime_contract,
)


_LABELS = {'queued': 'Queued', 'active': 'Working', 'waiting': 'Waiting',
           'paused': 'Paused', 'stopping': 'Stopping', 'completed': 'Done',
           'failed': 'Could not finish', 'cancelled': 'Stopped'}
_MESSAGES = {
    'runtime_unavailable': 'The agent is unavailable. Your work is retained.',
    'provider_unavailable': 'The model service is unavailable. Your work is retained.',
    'provider_incompatible': 'The selected model cannot run this assignment.',
    'provider_mismatch': 'The model connection needs an administrator check.',
    'operation_unknown': 'Radhouse is checking the original run before continuing.',
    'resource_busy': 'Another assignment is using the resource this work needs.',
    'grant_withdrawal': 'Access needed for this work was withdrawn.',
    'budget_exhausted': 'The assignment reached its retry budget.',
    'permission_needed': 'The agent needs your decision to continue.',
    'result_invalid': 'The run ended without a valid result. Your work remains unfinished.',
    'acceptance_unmet': 'The run did not deliver the required text artifact.',
    'dependency_unavailable': 'A dependency prevented completion.',
    'runtime_failed': 'The agent run failed before delivering a verified artifact.',
    'workflow_upgrade_required': 'This work needs a compatible controller version.',
}
_AUTOMATIC = {'runtime_unavailable', 'provider_unavailable', 'operation_unknown', 'resource_busy', 'runtime_stop'}


@dataclass(frozen=True)
class BlockerView:
    code: str
    resolver: str
    message: str


@dataclass(frozen=True)
class WorkView:
    work_id: str
    task_id: str
    title: str
    scope_revision: int
    state_revision: int
    state: str
    state_label: str
    needs_input: bool
    blockers: tuple[BlockerView, ...]
    artifact: ArtifactManifest | None
    created_at: datetime
    updated_at: datetime


def project_work(tx, work: WorkItem, task: Task) -> WorkView:
    needs_input = bool(task.permission_request) and task.phase == 'active'
    blockers = work.blockers
    if needs_input and not any(b.code == 'permission_needed' for b in blockers):
        blockers = (*blockers, WorkBlocker('permission_needed', 'owner'))
    title = tx.task_title(task.task_id)
    artifact = tx.artifact(work.artifact_id) if work.artifact_id else None
    return WorkView(work.work_id, task.task_id, title.title if title else work.brief[:100],
                    work.scope_revision, work.state_revision, work.state,
                    'Needs your input' if needs_input else _LABELS[work.state], needs_input,
                    tuple(BlockerView(b.code, b.resolver, _MESSAGES.get(b.code, 'Work is waiting for a checked condition.')) for b in blockers),
                    artifact[0] if artifact else None, work.created_at, work.updated_at)


def reconcile_task(tx, task: Task, now: datetime) -> None:
    """State/evidence changes commit with the exact task transition, without network IO."""
    work = tx.work_for_task(task.task_id)
    if work is None:
        return
    evidence = {}
    if work.workflow_version != 'artifact-v1':
        state, blockers = 'waiting', (WorkBlocker('workflow_upgrade_required', 'administrator'),)
    elif task.phase == 'closed' and work.verification_id is not None:
        return  # A guidance receipt cannot reinterpret a previously verified terminal run.
    elif task.phase == 'closed':
        state, blockers, evidence = _verify_terminal(tx, work, task, now)
    elif task.phase == 'stopping':
        state, blockers = 'stopping', ()
    elif 'human_pause' in task.blockers:
        state, blockers = 'paused', ()
    elif task.blockers or task.permission_request:
        state = 'waiting'
        blockers = tuple(WorkBlocker(code, 'automatic' if code in _AUTOMATIC else 'administrator')
                         for code in task.blockers)
        if task.permission_request:
            blockers = (*blockers, WorkBlocker('permission_needed', 'owner'))
    else:
        state, blockers = ('queued' if task.phase == 'queued' else 'active'), ()
    if evidence or (work.state, work.blockers) != (state, blockers):
        tx.save_work(work.evolve(now, state=state, blockers=blockers, **evidence), work.state_revision)


def _verify_terminal(tx, work: WorkItem, task: Task, now: datetime):
    result = parse_result(task.result, work) if task.result is not None else None
    artifact = None
    if result and result.artifact and task.attempt_id:
        content = result.artifact.content
        artifact = ArtifactManifest(str(uuid4()), work.work_id, work.scope_revision,
            task.task_id, task.attempt_id, result.artifact.name, result.artifact.media_type,
            content_digest(content), len(content.encode()), now)
        tx.insert_artifact(artifact, content)
    if task.outcome == 'cancelled':
        state, check, code = 'cancelled', 'incomplete', None
    elif task.outcome == 'failed':
        state, check, code = 'failed', 'failed', 'runtime_failed'
    elif result is None:
        state, check, code = 'waiting', 'incomplete', 'result_invalid'
    elif result.outcome == 'succeeded' and artifact:
        state, check, code = 'completed', 'passed', None
    elif result.outcome == 'failed':
        state, check, code = 'failed', 'failed', result.reason_code
    else:
        # A runtime's cancellation claim is not confirmation that the controller
        # requested a stop. Incomplete/blocked runs retain artifacts and never rerun blindly.
        state, check, code = 'waiting', 'incomplete', result.reason_code or 'acceptance_unmet'
    receipt = VerificationReceipt(str(uuid4()), work.work_id, work.scope_revision,
        task.task_id, task.result_digest or content_digest(task.result or ''), artifact.artifact_id if artifact else None,
        'artifact-present-v1', check, code, now)
    tx.insert_verification(receipt)
    return state, (() if code is None else (WorkBlocker(code, 'administrator'),)), {
        'artifact_id': receipt.artifact_id, 'verification_id': receipt.verification_id,
    }


class WorkService:
    def __init__(self, service):
        self.service = service

    def submit(self, actor, envelope, start: StartTask) -> WorkView:
        # This endpoint accepts text-artifact work only. Delivery/release predicates
        # are separate versioned workflows; callers cannot substitute an acceptance rule.
        if not self.service.durable_work_enabled:
            raise Rejected("work_admission_disabled", 409)
        from radhouse.application.service import fingerprint
        work_id = 'work-' + fingerprint([actor.principal_id, envelope.command_key])[:32]
        with self.service.store.transaction() as tx:
            task = self.service._admit(tx, actor, envelope, start, output_contract=runtime_contract(work_id))
            work = tx.work_item(work_id)
            if work is None:
                # A source event cannot map a new work key onto a previously linked task.
                if tx.work_for_task(task.task_id) is not None:
                    raise Rejected('delivery_conflict')
                now = self.service._now()
                work = WorkItem(work_id, actor.principal_id, start.project_id, start.bot_id,
                                start.brief, task.task_id, now, now)
                tx.insert_work(work)
            elif work.task_id != task.task_id:
                raise Rejected('command_conflict')
            return project_work(tx, work, task)

    def get(self, actor, work_id, *, envelope) -> WorkView:
        with self.service.store.transaction() as tx:
            work = tx.work_item(work_id)
            if work is None:
                raise Rejected('work_not_found', 404)
            task = self.service._task(tx, work.task_id)
            self.service._authorize(tx, actor, task, envelope)
            return project_work(tx, work, task)

    def artifact(self, actor, work_id, artifact_id, *, envelope):
        with self.service.store.transaction() as tx:
            work = tx.work_item(work_id)
            if work is None:
                raise Rejected('work_not_found', 404)
            task = self.service._task(tx, work.task_id)
            self.service._authorize(tx, actor, task, envelope)
            stored = tx.artifact(artifact_id)
            if stored is None or stored[0].work_id != work_id:
                raise Rejected('artifact_not_found', 404)
            if stored[0].sha256 != content_digest(stored[1]):
                raise Rejected('artifact_integrity_failure')
            return stored
