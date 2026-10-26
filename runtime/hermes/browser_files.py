"""Owner-scoped browser files; native control remains the authority for effects."""
import asyncio
import base64
import json
from pathlib import Path
from uuid import uuid4


def initialize(controller):
    with controller._transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS browser_file_launches (
            launch_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL,
            session_id TEXT NOT NULL, generation TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS browser_file_receipts (
            launch_id TEXT NOT NULL, file_id TEXT NOT NULL, private INTEGER NOT NULL,
            producer TEXT NOT NULL, run_id TEXT, PRIMARY KEY(launch_id,file_id))""")


def remember(bridge, owned, remote):
    initialize(bridge._controller)
    state = bridge._controller.state(owned.identity)
    with bridge._controller._transaction() as db:
        db.execute("INSERT OR IGNORE INTO browser_file_launches VALUES(?,?,?,?)",
            (remote.launch_id, state.principal_id, owned.identity.session_id, owned.identity.generation))


def file_module(bridge):
    platform = bridge._streaming
    if platform is None or platform.configuration["network"].get("kind") != "space-browser-v1":
        raise ValueError("browser_files_unavailable")
    return platform.load("radhouse_browser_files", Path(platform.__file__).with_name("browser_files.py"))


async def collect(bridge, session_id, body):
    """Only the authenticated web service calls this recovery/collection surface."""
    if set(body) != {"collector", "launch_id", "file"} or type(body["collector"]) is not str:
        raise ValueError("invalid_file_collector")
    files = file_module(bridge)
    files.validate(body["file"])
    if body["file"]["action"] not in {"list", "read", "ack"}:
        raise ValueError("invalid_file_collector")
    initialize(bridge._controller)
    with bridge._controller._transaction() as db:
        launches = [dict(row) for row in db.execute(
            "SELECT launch_id,generation FROM browser_file_launches WHERE principal_id=? AND session_id=? ORDER BY rowid DESC",
            (body["collector"], session_id))]
    if body["launch_id"] is None:
        if body["file"] != {"action": "list"}:
            raise ValueError("invalid_file_collector")
        return {"launches": launches}
    if not any(row["launch_id"] == body["launch_id"] for row in launches):
        raise ValueError("browser_file_owner_mismatch")
    platform = bridge._streaming
    client = platform.load("radhouse_space_client", Path(platform.__file__).with_name("space_client.py"))
    remote = client.Client(platform.configuration["network"], bridge._root_file)
    remote.launch_id = body["launch_id"]
    result = await remote.call("files", **body["file"])
    # Collector responses never include a private page/chooser observation.
    result.pop("chooser", None)
    if body["file"]["action"] == "list":
        owned = bridge._owned_browsers.get(session_id)
        state = bridge._controller.state(owned.identity) if owned is not None else None
        generation = next(row["generation"] for row in launches if row["launch_id"] == body["launch_id"])
        agent = bool(state is not None and not state.retired and state.identity.generation == generation
                     and state.mode == "agent" and state.admitted_run is not None)
        observing = bool(state is not None and not state.retired and state.identity.generation == generation
                         and state.mode == "human" and state.lease and state.lease.observation_mode == "observe")
        # Guest claims can restrict access, never override host ownership. The
        # first observed provenance is durable outside the browser microVM.
        with bridge._controller._transaction() as db:
            for item in result.get("downloads", []):
                private = not (agent or observing) or bool(item.get("private", True))
                db.execute("INSERT OR IGNORE INTO browser_file_receipts VALUES(?,?,?,?,?)",
                    (body["launch_id"], item["id"], int(private), "assistant" if agent else "user",
                     state.admitted_run.run_id if agent else None))
                if private:
                    db.execute("UPDATE browser_file_receipts SET private=1 WHERE launch_id=? AND file_id=?",
                        (body["launch_id"], item["id"]))
                receipt = db.execute("SELECT private,producer,run_id FROM browser_file_receipts WHERE launch_id=? AND file_id=?",
                    (body["launch_id"], item["id"])).fetchone()
                item.update(dict(receipt))
    return result


async def human(bridge, runtime, owned, owner, expiry, body):
    files = file_module(bridge)
    value = files.validate(body.get("file"))
    if value["action"] in {"read", "ack"}:
        raise ValueError("invalid_human_file_operation")
    if body.get("generation") != owned.identity.generation:
        raise ValueError("stale_browser")
    async def execute():
        state = bridge._controller.heartbeat(owned.identity, owner, body.get("lease_id"),
            body.get("revision"), auth_expires_at=expiry)
        try:
            result = await runtime.remote.call("files", timeout=120 if value["action"] == "commit" else 15, **value)
        except Exception:
            if value["action"] == "commit":
                # An uncertain website effect must not silently hand control on.
                bridge._controller.pause(owned.identity, owner)
            raise
        bridge._controller.heartbeat(owned.identity, owner, state.lease.lease_id,
            state.revision, auth_expires_at=expiry)
        return result
    # Staging never operates the website. Freeze streamed input only for commit.
    if value["action"] == "commit":
        async with runtime.boundary.input_lock:
            result = await execute()
    else:
        result = await execute()
    if value["action"] == "list":
        result.pop("downloads", None)
    return result


def agent_upload(bridge, args, **trusted):
    """Use a granted Library ID and one intercepted chooser, never a path."""
    try:
        context = bridge.current_run_context(task_id=trusted.get("task_id"), session_id=trusted.get("session_id"), documents=True)
        if (type(args) is not dict or set(args) not in (set(), {"file_id", "destination"})
                or bridge._callback is None):
            raise ValueError("invalid_file_arguments")
        with bridge.agent_browser_operation(context) as owned:
            runtime = bridge._streaming.runtime
            file_module(bridge)
            def call(value):
                return asyncio.run_coroutine_threadsafe(runtime.remote.call("files", **value), runtime.loop).result(20)
            chooser = call({"action": "list"}).get("chooser")
            if not args:
                return json.dumps({"chooser": chooser})
            if chooser is None or chooser["destination"] != args["destination"]:
                raise ValueError("file_chooser_changed")
            metadata = bridge._callback.post("content", context, {"file_id": args["file_id"], "offset": 0})
            identity = uuid4().hex
            call({"action": "begin", "id": identity, "chooser": chooser["id"], "destination": args["destination"],
                "name": metadata["name"], "size": metadata["size"], "sha256": metadata["sha256"]})
            offset = 0
            while offset < metadata["size"]:
                chunk = metadata if offset == 0 else bridge._callback.post("content", context, {"file_id": args["file_id"], "offset": offset})
                if (chunk["offset"] != offset or chunk["sha256"] != metadata["sha256"] or chunk["size"] != metadata["size"]):
                    raise ValueError("file_changed")
                raw = base64.b64decode(chunk["data"], validate=True)
                if not 0 < len(raw) <= 32768:
                    raise ValueError("invalid_file_chunk")
                call({"action": "write", "id": identity, "offset": offset, "data": chunk["data"]})
                offset += len(raw)
            # A human takeover makes the existing reserved command obsolete.
            async def commit():
                async with runtime.boundary.input_lock:
                    state = bridge._controller.state(owned.identity)
                    if state.mode != "agent" or state.admitted_run is None or state.admitted_run.run_id != context.run_id:
                        raise ValueError("browser_control_changed")
                    return await runtime.remote.call("files", action="commit", id=identity, timeout=120)
            try:
                result = asyncio.run_coroutine_threadsafe(commit(), runtime.loop).result(130)
            except Exception:
                _, channel = bridge._control_modules()
                raise channel.NativeChannelError("browser_file_outcome_unconfirmed") from None
            return json.dumps(result)
    except Exception:
        return json.dumps({"error": "browser_file_transfer_unavailable"})


def register(ctx, bridge):
    ctx.register_tool(name="browser_upload", toolset="radhouse_documents",
        handler=lambda args, **trusted: agent_upload(bridge, args, **trusted), schema={
            "description": "Upload one authorized Library file to a website. First click the site's file input with browser_click. "
                "Call with no arguments to read the pending chooser's destination, then supply its exact destination and a file_id from document_read's catalog. "
                "No filesystem paths. Only claim upload success after applied=true.",
            "parameters": {"type": "object", "properties": {"file_id": {"type": "string"},
                "destination": {"type": "string"}}, "additionalProperties": False}})
