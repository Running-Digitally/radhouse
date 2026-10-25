"""A retired transport cannot strand or silently replace its native driver."""
from types import SimpleNamespace
import asyncio
import threading
from dataclasses import replace

import pytest

from tests.test_hermes_browser_sessions import session  # pytest fixture
from tests.test_hermes_runtime_bridge import bridge
from tests.test_browser_control import control


def orphan(session, monkeypatch, tmp_path):
    session.bind()
    directory = tmp_path / "agent-browser-h_0123456789"
    directory.mkdir()
    pidfile = directory / "h_0123456789.pid"
    pidfile.write_text("1234")
    monkeypatch.setattr(session.browser, "_socket_safe_tmpdir", lambda: str(tmp_path), raising=False)
    gone, killed = [], []
    monkeypatch.setattr(bridge, "_pid_gone", lambda *args: bool(gone))

    def kill(path, name):
        killed.append((path, name))
        gone.append(True)
        return True

    monkeypatch.setattr(session.lifecycle, "_kill_verified_daemon", kill, raising=False)
    return SimpleNamespace(pidfile=pidfile, gone=gone, killed=killed)


def test_retired_transport_reaps_exact_driver_and_returns_idle(session, monkeypatch, tmp_path):
    f = orphan(session, monkeypatch, tmp_path)
    bridge.retire_browser_transport(session.owned)
    assert f.killed == [(str(f.pidfile.parent), "h_0123456789")]
    assert session.c.state(session.identity).retired
    assert "session" not in bridge._owned_browsers
    assert session.released == ["session"]
    status, payload = session.call("status", session.body())
    assert status == 200
    assert payload["state"] == "idle"
    bridge.retire_browser_transport(session.owned)
    assert len(f.killed) == 1


@pytest.mark.parametrize("pid", ["9999", "invalid", None])
def test_mismatched_driver_file_retains_identity(session, monkeypatch, tmp_path, pid):
    f = orphan(session, monkeypatch, tmp_path)
    if pid is None:
        f.pidfile.unlink()
    else:
        f.pidfile.write_text(pid)
    with pytest.raises(control.ControlRejected, match="browser_retirement_unproven"):
        bridge.retire_browser_transport(session.owned)
    assert not f.killed
    assert bridge._owned_browsers["session"] is session.owned
    assert not session.c.state(session.identity).retired
    assert not session.released


def test_reaper_ack_is_not_process_exit_proof(session, monkeypatch, tmp_path):
    orphan(session, monkeypatch, tmp_path)
    monkeypatch.setattr(session.lifecycle, "_kill_verified_daemon", lambda *args: True)
    with pytest.raises(control.ControlRejected, match="browser_retirement_unproven"):
        bridge.retire_browser_transport(session.owned)
    assert not session.c.state(session.identity).retired
    assert bridge._owned_browsers["session"] is session.owned
    assert not session.released


def test_already_gone_driver_needs_no_pidfile_or_kill(session, monkeypatch, tmp_path):
    f = orphan(session, monkeypatch, tmp_path)
    f.gone.append(True)
    f.pidfile.unlink()
    bridge.retire_browser_transport(session.owned)
    assert not f.killed
    assert session.c.state(session.identity).retired


def test_invalid_native_name_cannot_select_a_process(session, monkeypatch, tmp_path):
    f = orphan(session, monkeypatch, tmp_path)
    state = session.c.state(session.identity)
    monkeypatch.setattr(session.c, 'state', lambda identity: replace(state, native_name='../other'))
    with pytest.raises(control.ControlRejected, match='browser_retirement_unproven'):
        bridge.retire_browser_transport(session.owned)
    assert not f.killed
    assert not session.released


def test_stale_owned_object_cannot_kill_replacement(session, monkeypatch, tmp_path):
    f = orphan(session, monkeypatch, tmp_path)
    replacement = object()
    bridge._owned_browsers["session"] = replacement
    with pytest.raises(control.ControlRejected, match="stale_browser"):
        bridge.retire_browser_transport(session.owned)
    assert not f.killed
    assert bridge._owned_browsers["session"] is replacement


@pytest.mark.parametrize("lock_name", ["browser", "operation"])
def test_retirement_does_not_deadlock_a_concurrent_launch(session, monkeypatch, tmp_path, lock_name):
    f = orphan(session, monkeypatch, tmp_path)
    lock = bridge._browser_lock if lock_name == "browser" else session.owned.operation_lock
    entered, release = threading.Event(), threading.Event()
    def hold():
        with lock:
            entered.set()
            release.wait(timeout=3)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert entered.wait(timeout=2)
        with pytest.raises(control.ControlRejected, match="browser_retirement_busy"):
            bridge.retire_browser_transport(session.owned)
        assert not f.killed
        assert not session.c.state(session.identity).retired
    finally:
        release.set()
        thread.join(timeout=2)
    bridge.retire_browser_transport(session.owned)
    assert session.c.state(session.identity).retired


def test_watcher_retires_native_driver_without_waiting_for_idle_reaper(session, monkeypatch, tmp_path):
    from tests.test_selkies_platform import platform
    from tests.test_selkies_platform_lifecycle import lifecycle
    orphan(session, monkeypatch, tmp_path)
    async def scenario():
        f = lifecycle(monkeypatch)
        f.release.set()
        monkeypatch.setattr(platform, 'configuration', None)
        monkeypatch.setattr(platform, '_chrome', None)
        monkeypatch.setattr(bridge, '_streaming', platform)
        current = await platform.ensure(bridge, session.owned)
        current.watcher = asyncio.create_task(current.watch())
        await asyncio.wait_for(current.watcher, timeout=2)
        await asyncio.wait_for(asyncio.shield(current.shutdown), timeout=2)
        assert platform.runtime is None
        assert session.c.state(session.identity).retired
        assert not bridge._owned_browsers
    asyncio.run(scenario())
    status, payload = session.call("status", session.body())
    assert status == 200
    assert payload["state"] == "idle"


def test_reconnect_reconciles_lost_stop_reply_before_releasing_native_driver(session, monkeypatch, tmp_path):
    from tests.test_selkies_platform import platform
    from tests.test_space_browser_control import remote, p
    f = orphan(session, monkeypatch, tmp_path)
    class Chrome:
        unavailable, retired, proved = True, False, False
        def poll(self):
            return 0 if self.retired else None
        def reconcile_retirement(self):
            if self.proved:
                self.retired = True
            return self.retired
    chrome = Chrome()
    monkeypatch.setattr(platform, '_chrome', chrome)
    monkeypatch.setattr(platform, 'runtime', None)
    monkeypatch.setattr(platform, 'load', lambda *args: SimpleNamespace(StreamingControl=object))
    monkeypatch.setattr(bridge, '_streaming', platform)
    async def scenario():
        current = remote.create(platform, bridge, session.owned)
        platform.runtime = current
        current.chrome = chrome
        current.stopped = True
        async def lost():
            raise p.Uncertain('lost_stop_reply')
        current.retirement = asyncio.create_task(lost())
        await asyncio.gather(current.retirement, return_exceptions=True)
        with pytest.raises(ValueError, match='stream_retirement_unconfirmed'):
            await platform.ensure(bridge, session.owned)
        assert platform.runtime is current
        assert not f.killed
        chrome.proved = True
        with pytest.raises(ValueError, match='stream_retirement_unconfirmed'):
            await platform.ensure(bridge, session.owned)
        assert platform.runtime is None
        assert platform._chrome is None
        assert session.c.state(session.identity).retired
    asyncio.run(scenario())
    status, payload = session.call('status', session.body())
    assert status == 200
    assert payload['state'] == 'idle'
