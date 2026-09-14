"""Durable, at-most-once human controls for non-idempotent runtime endpoints."""
from dataclasses import replace
import json

from radhouse.domain.access import require_assurance
from radhouse.domain.tasks import Delivery, Event, Operation, Rejected, RuntimeFailure, RuntimeGuidanceReceipt
from radhouse.application.guidance import PROTOCOL, reconcile


def control(service, actor, task_id, expected, envelope, *, text=None, request_id=None, choice=None, digest=None):
    from radhouse.application.service import fingerprint

    kind = "guidance" if text is not None else "permission"
    body = {"kind": kind, "task": task_id, "text": text, "request_id": request_id,
            "choice": choice, "digest": digest, "expected": expected}
    identity = fingerprint(body)
    key = "control:" + fingerprint([actor.principal_id, envelope.command_key])
    if text is not None and (not text.strip() or len(text) > 4096):
        raise Rejected("invalid_guidance", 422)
    if kind == "guidance":
        # Authorize before a capability read, then recheck all state below after
        # that network call. Existing commands never acquire a replay transport.
        with service.store.transaction() as tx:
            task = service._task(tx, task_id)
            service._authorize(tx, actor, task, envelope, write=True)
            existing = tx.operation(key) is not None or tx.delivery(envelope.channel, envelope.event_id) is not None
            if not existing:
                service._expected(task, expected)
                if task.phase != "active" or task.blockers:
                    raise Rejected("task_not_accepting_control")
        if not existing and not service.work.capabilities(task).guidance_receipts:
            raise Rejected("runtime_guidance_receipts_unavailable")
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
        if kind == "guidance":
            receipt.update(protocol=PROTOCOL, attempt_id=task.attempt_id, application_state=None, application_reason=None,
                           source_channel=envelope.channel, source_event_id=envelope.event_id,
                           application_final=False, receipt_revision=0,
                           checkpoint_id=None, api_request_id=None, receipt_source=None)
        operation = Operation(key, task_id, task.attempt_id, "submitted",
                              json.dumps({"fingerprint": identity}))
        tx.save_operation(operation)
        tx.save_delivery(Delivery(envelope.channel, envelope.event_id, actor.principal_id, identity, task_id, kind))
        updated = task.evolve(guidance=(*task.guidance, receipt), task_revision=task.task_revision + 1)
        service._save(tx, task, updated, kind + "_received")
    state = "unknown"
    runtime_receipt = None
    try:
        runtime = service._runtime_dispatch(dispatch)
        if kind == "guidance":
            runtime_receipt = method(task, runtime, text, control_id=key)
            if not isinstance(runtime_receipt, RuntimeGuidanceReceipt):
                raise RuntimeFailure("runtime_malformed_guidance")
            accepted = runtime_receipt.accepted
        else:
            accepted = method(task, runtime, request_id, choice)
        state = "accepted" if accepted else "rejected"
    except RuntimeFailure:
        runtime_receipt = None
        pass
    with service.store.transaction() as tx:
        current = service._task(tx, task_id)
        entry = next(item for item in current.guidance if item["id"] == key)
        if not entry.get("receipt_revision"):
            tx.save_operation(replace(operation, state="confirmed" if state == "accepted" else state))
        # A concurrent GET may already have confirmed a newer receipt while the
        # POST was in flight; never regress its delivery or application state.
        entries = tuple({**item, "state": state} if item["id"] == key and not item.get("receipt_revision")
                        else item for item in current.guidance)
        # Runtime acceptance confirms receipt, never application of guidance.
        permission = current.permission_request
        if kind == "permission" and state == "accepted" and permission is not None and permission["request_id"] == request_id:
            permission = None
        updated = current.evolve(guidance=entries, permission_request=permission)
        service._save(tx, current, updated, kind + "_" + state)
        tx.add_event(Event(task_id, "control_receipt", updated.state_revision,
                           {"kind": kind, "state": state, "run_id": dispatch.run_id}))
    if runtime_receipt is not None:
        return reconcile(service, task_id, dispatch.run_id, (runtime_receipt,))
    return updated
