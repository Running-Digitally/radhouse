"""Durable, at-most-once human controls for non-idempotent runtime endpoints."""
from dataclasses import replace
import json

from radhouse.domain.access import require_assurance
from radhouse.domain.tasks import Delivery, Event, Operation, Rejected, RuntimeFailure, RuntimeGuidanceReceipt
from radhouse.application.guidance import PROTOCOL, reconcile


def _matches_original_permission(operation, task, entry, permission, observed_digest, fingerprint):
    try:
        saved = json.loads(operation.result or "{}").get("fingerprint")
    except (TypeError, ValueError):
        return False
    if not isinstance(saved, str):
        return False
    base = {
        "kind": "permission", "task": task.task_id, "text": None,
        "request_id": permission.get("request_id"), "choice": "deny",
        "digest": observed_digest,
    }
    permission_digest = entry.get("permission_digest")
    expected_revision = entry.get("expected_revision")
    if permission_digest is not None or expected_revision is not None:
        return (
            permission_digest == observed_digest
            and type(expected_revision) is int
            and fingerprint({**base, "expected": expected_revision}) == saved
        )
    # Legacy receipts did not retain these two fields. Their immutable operation
    # fingerprint still proves the original digest and expected revision.
    return any(
        fingerprint({**base, "expected": revision}) == saved
        for revision in range(task.state_revision + 1)
    )


def reconcile_pending_denial(service, task, dispatch, permission):
    """Retry one lost denial only while the exact request is still pending."""
    from radhouse.application.service import fingerprint

    if permission is None:
        return False
    with service.store.transaction() as tx:
        current = service._task(tx, task.task_id)
        expected = current.permission_request
        candidates = tuple(
            item for item in current.guidance
            if item.get("kind") == "permission"
            and item.get("choice") == "deny"
            and item.get("state") == "unknown"
            and item.get("request_id") == permission.get("request_id")
            and item.get("run_id") == dispatch.run_id
            and not item.get("reconcile_attempted")
        )
        entry = candidates[0] if len(candidates) == 1 else None
        operation = tx.operation(entry["id"]) if entry is not None else None
        observed_digest = fingerprint(permission)
        if (
            entry is None
            or operation is None
            or expected is None
            or expected.get("request_id") != permission.get("request_id")
            or expected.get("run_id") != dispatch.run_id
            or permission.get("run_id") != dispatch.run_id
            or expected.get("digest") != observed_digest
            or not _matches_original_permission(
                operation, current, entry, permission, observed_digest, fingerprint
            )
        ):
            return False
        entries = tuple(
            {**item, "reconcile_attempted": True}
            if item["id"] == entry["id"] else item
            for item in current.guidance
        )
        current = service._save(
            tx, current,
            current.evolve(guidance=entries, task_revision=current.task_revision + 1),
            "permission_reconcile_submitted",
        )

    state = "unknown"
    try:
        accepted = service.work.approve(
            current, dispatch, permission["request_id"], "deny"
        )
        state = "accepted" if accepted else "rejected"
    except RuntimeFailure:
        pass

    with service.store.transaction() as tx:
        latest = service._task(tx, task.task_id)
        entries = tuple(
            {**item, "state": state}
            if item["id"] == entry["id"] else item
            for item in latest.guidance
        )
        operation = tx.operation(entry["id"])
        if operation is None:
            raise RuntimeFailure("permission_reconcile_operation_missing")
        tx.save_operation(replace(
            operation, state="confirmed" if state == "accepted" else state
        ))
        pending = latest.permission_request
        if (
            state == "accepted"
            and pending is not None
            and pending.get("request_id") == permission["request_id"]
        ):
            pending = None
        updated = service._save(
            tx, latest,
            latest.evolve(guidance=entries, permission_request=pending),
            "permission_reconciled_" + state,
        )
        tx.add_event(Event(
            task.task_id, "control_receipt", updated.state_revision,
            {"kind": "permission", "state": state, "run_id": dispatch.run_id,
             "reconciled": True},
        ))
    return state == "accepted"


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
        if kind == "permission":
            receipt.update(permission_digest=digest, expected_revision=expected)
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
