"""Durable, at-most-once human controls for non-idempotent runtime endpoints."""
from dataclasses import replace
import json

from radhouse.domain.access import require_assurance
from radhouse.domain.tasks import Delivery, Event, Operation, Rejected, RuntimeFailure


def control(service, actor, task_id, expected, envelope, *, text=None, request_id=None, choice=None, digest=None):
    from radhouse.application.service import fingerprint

    kind = "guidance" if text is not None else "permission"
    body = {"kind": kind, "task": task_id, "text": text, "request_id": request_id,
            "choice": choice, "digest": digest, "expected": expected}
    identity = fingerprint(body)
    key = "control:" + fingerprint([actor.principal_id, envelope.command_key])
    if text is not None and (not text.strip() or len(text) > 4096):
        raise Rejected("invalid_guidance", 422)
    with service.store.transaction() as tx:
        task = service._task(tx, task_id)
        service._authorize(tx, actor, task, envelope, write=True)
        delivery = tx.delivery(envelope.channel, envelope.event_id)
        if delivery:
            if (delivery.principal_id != actor.principal_id or delivery.task_id != task_id
                    or delivery.fingerprint != identity or delivery.kind != kind):
                raise Rejected("delivery_conflict")
            return task
        old = tx.operation(key)
        if old:
            if old.task_id != task_id or json.loads(old.result or "{}").get("fingerprint") != identity:
                raise Rejected("command_conflict")
            # A crash after this receipt commits is deliberately non-replayable.
            return task
        service._expected(task, expected)
        if len(task.guidance) >= 64:
            raise Rejected("task_control_limit")
        dispatch = tx.dispatch(task.attempt_id) if task.attempt_id else None
        if task.phase != "active" or task.blockers or dispatch is None or dispatch.state != "accepted":
            raise Rejected("task_not_accepting_control")
        if any(item["state"] in {"submitted", "unknown"} for item in task.guidance):
            raise Rejected("control_outcome_unknown")
        if kind == "permission":
            require_assurance(actor, service._now())
            permission = task.permission_request
            if (permission is None or permission["request_id"] != request_id
                    or permission["digest"] != digest or choice not in {"once", "deny"}):
                raise Rejected("permission_changed")
            if any(item["kind"] == "permission" and item["request_id"] == request_id
                   and item["run_id"] == dispatch.run_id for item in task.guidance):
                raise Rejected("permission_already_responded")
            # Approval is not a resource grant. Only an exact operator-configured
            # command in this bot's existing authority can be allowed once.
            if choice == "once" and permission["command"] not in service.approval_commands.get(task.bot_id, ()):
                raise Rejected("resource_grant_required", 403)
        elif task.permission_request is not None:
            raise Rejected("permission_response_required")
        method = getattr(service.work, "steer" if kind == "guidance" else "approve", None)
        if method is None:
            raise Rejected("runtime_control_unavailable")
        receipt = {"id": key, "kind": kind, "text": text, "request_id": request_id,
                   "choice": choice, "run_id": dispatch.run_id, "state": "submitted"}
        operation = Operation(key, task_id, task.attempt_id, "submitted",
                              json.dumps({"fingerprint": identity}))
        tx.save_operation(operation)
        tx.save_delivery(Delivery(envelope.channel, envelope.event_id, actor.principal_id, identity, task_id, kind))
        updated = task.evolve(guidance=(*task.guidance, receipt), task_revision=task.task_revision + 1)
        service._save(tx, task, updated, kind + "_received")
    state = "unknown"
    try:
        runtime = service._runtime_dispatch(dispatch)
        accepted = method(task, runtime, text) if kind == "guidance" else method(task, runtime, request_id, choice)
        state = "accepted" if accepted else "rejected"
    except RuntimeFailure:
        pass
    with service.store.transaction() as tx:
        current = service._task(tx, task_id)
        tx.save_operation(replace(operation, state="confirmed" if state == "accepted" else state))
        entries = tuple({**item, "state": state} if item["id"] == key else item for item in current.guidance)
        # Runtime acceptance confirms receipt, never application of guidance.
        permission = current.permission_request
        if kind == "permission" and state == "accepted" and permission is not None and permission["request_id"] == request_id:
            permission = None
        updated = current.evolve(guidance=entries, permission_request=permission)
        service._save(tx, current, updated, kind + "_" + state)
        tx.add_event(Event(task_id, "control_receipt", updated.state_revision,
                           {"kind": kind, "state": state, "run_id": dispatch.run_id}))
        return updated
