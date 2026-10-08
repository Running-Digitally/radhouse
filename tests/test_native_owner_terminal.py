"""Real disposable PTYs; lazy opening, fencing, cleanup and ephemeral output."""
import asyncio
import base64
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

spec=importlib.util.spec_from_file_location("native_owner_terminal_test",Path(__file__).resolve().parents[1]/"runtime/hermes/owner_terminal.py")
native=importlib.util.module_from_spec(spec);sys.modules[spec.name]=native;spec.loader.exec_module(native)
TAB=str(uuid4())
OWNER={"principal_id":"owner","auth_session_digest":"a"*64,"tab_id":TAB,"conversation_id":"conversation","binding_revision":1}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    # Load the exact pinned upstream bridge, without importing a whole Hermes
    # deployment/profile. Its explicit env branch never calls this env builder.
    raw=os.environ.get("RADHOUSE_TEST_HERMES_SOURCE")
    if not raw:
        pytest.skip("Real PTY qualification needs the pinned Hermes source checkout")
    pytest.importorskip("ptyprocess");pytest.importorskip("psutil")
    bridge_spec=importlib.util.spec_from_file_location("hermes_cli.pty_bridge",Path(raw)/"hermes_cli/pty_bridge.py")
    bridge=importlib.util.module_from_spec(bridge_spec);bridge_spec.loader.exec_module(bridge)
    local=ModuleType("tools.environments.local");local.build_subprocess_env=lambda **_:pytest.fail("Must supply clean env")
    utils=ModuleType("utils");utils.env_float=lambda name,default,*args,**kwargs:default
    monkeypatch.setitem(sys.modules,"hermes_cli.pty_bridge",bridge)
    monkeypatch.setitem(sys.modules,"tools.environments.local",local)
    monkeypatch.setitem(sys.modules,"utils",utils)
    return native.OwnerTerminals(cwd=tmp_path,home=tmp_path,scrub=lambda text:text.replace("synthetic-secret","[REDACTED]"))


def body(**values): return {"owner":dict(OWNER),"auth_expires_at":native.time.time()+300,**values}
def bound(status,**values): return body(**{k:status[k] for k in ("terminal_id","generation","attach_epoch")},**values)


async def read_until(manager,status,needle,cursor=0):
    seen=b""
    for _ in range(30):
        value=await manager.call("output",bound(status,cursor=cursor,wait_ms=1000))
        seen+=base64.b64decode(value["data_b64"]);cursor=value["next_cursor"]
        if needle in seen:return seen,cursor
    raise AssertionError("Expected synthetic PTY output not received")


def test_real_pty_lazy_idempotent_unicode_resize_and_no_history(manager,monkeypatch):
    monkeypatch.setenv("API_KEY","synthetic-secret")
    monkeypatch.setenv("PROMPT_COMMAND","echo SENTINEL_BAD_PROMPT")
    async def run():
        try:
            assert (await manager.call("status",body()))["state"]=="closed"
            assert not manager.sessions
            request=str(uuid4());status=await manager.call("open",body(request_id=request,cols=100,rows=28))
            assert (await manager.call("open",body(request_id=request,cols=100,rows=28)))==status
            command="printf 'MARK_é:%s:%s\\n' \"${API_KEY-unset}\" \"${PROMPT_COMMAND-unset}\"; stty size; set -o | grep history; printf 'DONE_MARK\\n'\n"
            ack=await manager.call("input",bound(status,sequence=1,data_b64=base64.b64encode(command.encode()).decode()))
            assert ack["last_outcome"]=="written"
            output,cursor=await read_until(manager,status,b"\r\nDONE_MARK\r\n")
            assert b"MARK_\xc3\xa9:unset:unset" in output and b"28 100" in output
            assert b"SENTINEL_BAD_PROMPT" not in output
            await manager.call("resize",bound(status,cols=90,rows=25))
            with pytest.raises(native.TerminalRejected):
                await manager.call("input",bound(status,sequence=1,data_b64="YQ=="))
            await manager.call("close",bound(status))
            assert (await manager.call("status",body()))["state"]=="closed"
            assert not (Path(manager.home)/".bash_history").exists()
        finally:await manager.shutdown()
    asyncio.run(run())


def test_explicit_reattach_preserves_shell_fences_old_input_and_strict_identity(manager):
    async def run():
        try:
            first=await manager.call("open",body(request_id=str(uuid4()),cols=80,rows=24))
            second=await manager.call("open",body(request_id=str(uuid4()),cols=80,rows=24))
            assert second["generation"]==first["generation"] and second["attach_epoch"]==first["attach_epoch"]+1
            with pytest.raises(native.TerminalRejected):await manager.call("resize",bound(first,cols=80,rows=24))
            foreign=bound(second,sequence=1,data_b64="YQ==");foreign["owner"]["binding_revision"]=2
            with pytest.raises(native.TerminalRejected):await manager.call("input",foreign)
            status_body=body();status_body["owner"]["conversation_id"]="new-conversation"
            with pytest.raises(native.TerminalRejected):await manager.call("status",status_body)
            changed=await manager.call("open",{**status_body,"request_id":str(uuid4()),"cols":80,"rows":24})
            assert changed["generation"]==first["generation"]
        finally:await manager.shutdown()
    asyncio.run(run())


def test_close_kills_owned_background_job_but_leaves_unrelated_process(manager):
    import psutil
    unrelated=subprocess.Popen(["/bin/sleep","30"])
    async def run():
        try:
            status=await manager.call("open",body(request_id=str(uuid4()),cols=80,rows=24))
            await manager.call("input",bound(status,sequence=1,data_b64=base64.b64encode(b"sleep 30 & echo OWNED_PID:$!\n").decode()))
            output,cursor=await read_until(manager,status,b"\r\nOWNED_PID:")
            import re
            matches=re.findall(rb"OWNED_PID:(\d+)",output)
            while not matches:
                more,cursor=await read_until(manager,status,b"\r\n",cursor);output+=more;matches=re.findall(rb"OWNED_PID:(\d+)",output)
            pid=int(matches[-1]);await manager.call("close",bound(status))
            assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
            assert unrelated.poll() is None
        finally:await manager.shutdown()
    try:asyncio.run(run())
    finally:unrelated.terminate();unrelated.wait()


def test_context_is_scrub_only_and_valid_after_terminal_closed(manager):
    async def run():
        result=await manager.call("context-scrub",body(terminal_id=str(uuid4()),generation=str(uuid4()),
            text="synthetic-secret",source="selection",captured_at="2026-10-08T18:00:00+00:00",truncated=False))
        assert result["text"]=="[REDACTED]" and not manager.sessions
        with pytest.raises(native.TerminalRejected):await manager.call("context-scrub",body(terminal_id=str(uuid4()),generation=str(uuid4()),
            text="é"*8192,source="recent",captured_at="2026-10-08T18:00:00+00:00",truncated=False))
    asyncio.run(run())


def test_private_auth_happens_before_parsing():
    class Request:
        async def json(self):pytest.fail("Unauthenticated body must not be parsed")
    sentinel=object()
    assert asyncio.run(native.handle_owner_terminal(SimpleNamespace(_check_auth=lambda _:sentinel),Request(),operation="open")) is sentinel


def test_quiet_presence_survives_but_abandonment_and_auth_expiry_close(manager):
    now=[1000];manager.clock=lambda:now[0]
    def timed(**values):return {**body(**values),"auth_expires_at":100000}
    async def run():
        try:
            opened=await manager.call("open",timed(request_id=str(uuid4()),cols=80,rows=24))
            now[0]+=599
            assert (await manager.call("status",timed()))["state"]=="open"
            now[0]+=599
            await asyncio.sleep(.3)
            assert (await manager.call("status",timed()))["state"]=="open"
            now[0]+=601
            await asyncio.sleep(.5)
            assert (await manager.call("status",timed()))["state"]=="closed"
            # A fresh cookie with a short expiry still wins over ten-minute grace.
            await manager.call("open",{**timed(request_id=str(uuid4()),cols=80,rows=24),"auth_expires_at":now[0]+1})
            now[0]+=2
            await asyncio.sleep(.5)
            assert list(manager.sessions.values())[0].state=="closed"
        finally:await manager.shutdown()
    asyncio.run(run())


def test_partial_input_ack_is_uncertain_and_cannot_be_replayed(manager):
    async def run():
        try:
            status=await manager.call("open",body(request_id=str(uuid4()),cols=80,rows=24))
            shell=list(manager.sessions.values())[0];write=shell.bridge.write
            async def partial(data,**kwargs):
                await write(data[:1],**kwargs);return False
            shell.bridge.write=partial
            values=bound(status,sequence=1,data_b64="YWJj")
            assert (await manager.call("input",values))["last_outcome"]=="uncertain"
            with pytest.raises(native.TerminalRejected):await manager.call("input",values)
            assert shell.last_sequence==1
        finally:await manager.shutdown()
    asyncio.run(run())


def test_unexpected_read_failure_closes_actual_shell_and_background_job(manager):
    import psutil, re
    async def run():
        try:
            status=await manager.call("open",body(request_id=str(uuid4()),cols=80,rows=24))
            shell=list(manager.sessions.values())[0]
            await manager.call("input",bound(status,sequence=1,data_b64=base64.b64encode(b"sleep 30 & echo OWNED_PID:$!\n").decode()))
            output,_=await read_until(manager,status,b"\r\nOWNED_PID:")
            pid=int(re.findall(rb"OWNED_PID:(\d+)",output)[-1])
            def failed_read(*args):raise OSError("Synthetic private terminal content must not escape")
            shell.bridge.read=failed_read
            for _ in range(30):
                await asyncio.sleep(.1)
                if shell.task.done():break
            assert shell.state=="closed" and shell.task.done()
            assert not psutil.pid_exists(shell.bridge.pid) or psutil.Process(shell.bridge.pid).status()==psutil.STATUS_ZOMBIE
            assert not psutil.pid_exists(pid) or psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
            assert not shell.ring
        finally:await manager.shutdown()
    asyncio.run(run())
