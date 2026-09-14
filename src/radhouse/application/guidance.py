"""Monotonic, read-only reconciliation of identified runtime guidance."""
from dataclasses import replace
from hashlib import sha256

from radhouse.domain.tasks import RuntimeFailure, RuntimeGuidanceReceipt


PROTOCOL = "hermes-guidance-v1"
TERMINAL = {"applied", "too_late", "not_applied", "unknown"}


def pending(task, run_id=None):
    return any(item.get("protocol") == PROTOCOL and not item.get("application_final", False)
               and (run_id is None or item["run_id"] == run_id) for item in task.guidance)


def reconcile(service, task_id, run_id, receipts, *, terminal=False, missing_reason="terminal_receipt_missing", settle_missing=False):
    """Merge only exact known controls; never reopen work or send an instruction."""
    if receipts is None and not terminal:
        with service.store.transaction() as tx:
            return service._task(tx, task_id)
    receipts = receipts or ()
    if (len(receipts) > 64 or any(not isinstance(item, RuntimeGuidanceReceipt) for item in receipts)
            or len({item.control_id for item in receipts}) != len(receipts)):
        raise RuntimeFailure("runtime_malformed_guidance")
    with service.store.transaction() as tx:
        task = service._task(tx, task_id)
        entries = {item["id"]: dict(item) for item in task.guidance}
        observed = set()
        for value in receipts:
            if not isinstance(value, RuntimeGuidanceReceipt):
                raise RuntimeFailure("runtime_malformed_guidance")
            entry = entries.get(value.control_id)
            if (entry is None or entry.get("protocol") != PROTOCOL or entry.get("run_id") != run_id
                    or value.run_id != run_id or entry.get("kind") != "guidance"
                    or value.input_sha256 != sha256(entry["text"].encode()).hexdigest()):
                raise RuntimeFailure("runtime_guidance_identity_mismatch")
            observed.add(value.control_id)
            old_revision = entry.get("receipt_revision", 0)
            fields = {"application_state": value.state, "application_reason": value.reason,
                      "checkpoint_id": value.checkpoint_id, "api_request_id": value.api_request_id,
                      "receipt_revision": value.revision, "application_final": value.state in TERMINAL,
                      "state": "accepted" if value.accepted else "rejected", "receipt_source": "runtime"}
            if value.revision < old_revision:
                continue
            if value.revision == old_revision and entry.get("receipt_source") == "runtime":
                if any(entry.get(key) != part for key, part in fields.items()):
                    raise RuntimeFailure("runtime_guidance_receipt_conflict")
                continue
            if entry.get("application_final") and entry.get("receipt_source") == "runtime":
                raise RuntimeFailure("runtime_guidance_receipt_conflict")
            entry.update(fields)
            operation = tx.operation(value.control_id)
            if operation is None or operation.task_id != task_id:
                raise RuntimeFailure("runtime_guidance_operation_mismatch")
            tx.save_operation(replace(operation, state="confirmed" if value.accepted else "rejected"))
        if terminal:
            for entry in entries.values():
                if (entry.get("protocol") == PROTOCOL and entry.get("run_id") == run_id
                        and not entry.get("application_final")):
                    # Missing/unfinished evidence is uncertainty, never proof that
                    # the update was not used. No POST is retried to resolve it.
                    # A terminal GET can race a still in-flight POST. Keep GET
                    # reconciliation eligible until its dispatch lease expires.
                    entry.update(application_state="unknown", application_final=settle_missing,
                                 receipt_source="controller",
                                 application_reason=("runtime_terminal_without_outcome"
                                     if entry["id"] in observed else missing_reason))
        guidance = tuple(entries[item["id"]] for item in task.guidance)
        if guidance == task.guidance:
            return task
        return service._save(tx, task, task.evolve(guidance=guidance), "guidance_outcome")


def outcome_text(receipt):
    state = receipt.get("application_state")
    if state == "accepted":
        return "Your update is queued for this run’s next tool checkpoint."
    if state == "applied":
        return "Your update was used in a completed model response. Review the result to check how it was followed."
    if state == "too_late":
        return "This run is no longer accepting guidance. The update was not used; you can include it in a follow-up."
    if state == "not_applied":
        return "This run ended without using your update at a later checkpoint. The update was not resent; you can include it in a follow-up."
    if state == "unknown":
        return "The runtime could not confirm whether your update was used. It will not be resent automatically."
    if receipt.get("state") == "accepted":
        return "Your update was received by the runtime; it has not confirmed applying it."
    return "Your update is recorded, but runtime delivery is unconfirmed. I have not restarted the task."


def outcome_message_id(task_id, receipt):
    from radhouse.application.service import fingerprint
    return "guidance:" + fingerprint([task_id, receipt["id"], receipt["application_state"]])
