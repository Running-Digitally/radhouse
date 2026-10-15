"""Exercise the new input path against the actual durable browser controller."""
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_browser_control import control

spec = importlib.util.spec_from_file_location("selkies_qualification_control",
    Path(__file__).parents[1] / "runtime/selkies/control.py")
stream = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stream
spec.loader.exec_module(stream)


def fixture(tmp_path):
    clock = [1000.0]
    c = control.BrowserController(tmp_path / "browser.db", maintenance_held=lambda: False,
        clock=lambda: clock[0], lease_seconds=10)
    identity = control.BrowserIdentity("conversation", "session", "generation")
    run = control.RunBinding("old-run", "session", "old-key")
    c.bind_browser(identity, run, "owner")
    events, tables = [], []

    async def publish(table):
        tables.append(table)

    async def fence(state):
        events.append("native-fence")
        return control.FenceObservation(identity, state.takeover_after, True)

    async def observe():
        events.append("fresh-observation")
        return {"snapshot": "fresh page"}

    async def resume(owner, revision, observation):
        c.admit_run(identity, owner, control.RunBinding("fresh-run", "session", "fresh-key"),
            lease_id=None, revision=revision,
            previous=control.RunTerminalObservation(run.run_id, run.session_id, "completed"),
            handover=control.HumanReturnObservation(identity, owner, revision, True))
        events.append("agent-admitted")

    async def clear_clipboard():
        events.append("clear-clipboard")
        return True

    async def sensitive_clear():
        return True

    boundary = stream.StreamingControl(c, identity, fence=fence, observe=observe,
        publish=publish, resume=resume, current=lambda: identity.generation,
        clear_clipboard=clear_clipboard, sensitive_clear=sensitive_clear)
    desktop = boundary.add_viewer(control.OwnerBinding("owner", "a"*64, 1, "desktop"), can_take=True)
    phone = boundary.add_viewer(control.OwnerBinding("owner", "b"*64, 1, "phone"))
    connections = {}

    async def dispatch(message, display_id="primary", conn_id=None):
        events.append("input:" + message)

    async def release():
        events.append("release-buttons")
        handler.button_mask = 0

    async def reset():
        events.append("release-keys")
        handler.pressed_keys.clear()
        handler.translated_keys.clear()

    async def clipboard(value):
        events.append("clear-clipboard")
        return True

    handler = SimpleNamespace(is_wayland=False, on_message=dispatch, button_mask=0,
        pressed_keys={}, translated_keys={}, release_mouse_buttons=release,
        reset_keyboard=reset, write_clipboard=clipboard,
        _reset_multipart_clipboard=lambda: events.append("clear-transfer"),
        xdisplay=SimpleNamespace(sync=lambda: events.append("x-sync"), query_keymap=lambda: [0]*32,
            screen=lambda: SimpleNamespace(root=SimpleNamespace(query_pointer=lambda: SimpleNamespace(mask=0)))))
    boundary.attach(handler, lambda cid: connections.get(cid))
    return SimpleNamespace(c=c, clock=clock, identity=identity, run=run, events=events,
        tables=tables, boundary=boundary, desktop=desktop, phone=phone,
        connections=connections, handler=handler)


async def take(f, viewer=None):
    return await f.boundary.take(viewer or f.desktop, request_id="request",
        revision=f.boundary.state().revision, auth_expires_at=2000)


def test_phone_cannot_take_or_inject_and_desktop_positive_control(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        f.connections[1] = f.phone.token
        with pytest.raises(stream.StreamRejected, match="viewing_only"):
            await take(f, f.phone)
        await f.handler.on_message("kd,97", conn_id=1)
        await take(f)
        f.connections[2] = f.boundary.input_token
        await f.handler.on_message("kd,97", conn_id=1)
        await f.handler.on_message("kd,97", display_id=None, conn_id=2)
        await f.handler.on_message("cmd,touch /tmp/forbidden", conn_id=2)
        await f.handler.on_message("r,900x900", conn_id=2)
        assert f.events.count("input:kd,97") == 1
        assert not any("forbidden" in e or "900x900" in e for e in f.events)
    asyncio.run(scenario())


def test_takeover_blocks_agent_before_inflight_completion_and_fence(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        f.c.reserve_agent(f.identity, f.run, "active-command")
        pending = await take(f)
        assert pending.mode == "takeover_pending" and f.boundary.input_token is None
        with pytest.raises(control.ControlRejected):
            f.c.reserve_agent(f.identity, f.run, "later-command")
        f.c.complete_agent(f.identity, f.run, "active-command", outcome="completed")
        state = await f.boundary.settle_takeover()
        assert state.mode == "human" and f.events == ["native-fence"]
    asyncio.run(scenario())


def test_handback_waits_for_input_releases_and_observation_before_agent(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        state = await take(f)
        stale_token = f.boundary.input_token
        f.connections[1] = stale_token
        entered, finish = asyncio.Event(), asyncio.Event()

        async def held(message, display_id="primary", conn_id=None):
            entered.set()
            await finish.wait()
            f.handler.pressed_keys[97] = 1
            f.handler.button_mask = 1
            f.events.append("accepted-input-complete")

        f.boundary._dispatch = held
        input_task = asyncio.create_task(f.handler.on_message("kd,97", conn_id=1))
        await entered.wait()
        return_task = asyncio.create_task(f.boundary.handback(f.desktop,
            lease_id=state.lease.lease_id, revision=state.revision))
        await asyncio.sleep(0)
        assert f.boundary.state().mode == "human"
        with pytest.raises(control.ControlRejected):
            f.c.reserve_agent(f.identity, f.run, "too-early")
        finish.set()
        await input_task
        await return_task
        await f.handler.on_message("kd,97", conn_id=1)
        assert f.events == ["native-fence", "accepted-input-complete", "release-buttons",
            "release-keys", "x-sync", "clear-transfer", "clear-clipboard", "x-sync",
            "fresh-observation", "agent-admitted"]
        assert f.boundary.state().admitted_run.run_id == "fresh-run"
    asyncio.run(scenario())


def test_sensitive_precondition_keeps_control_so_owner_can_finish_signin(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        state = await take(f)
        token = f.boundary.input_token
        async def sensitive(): return False
        f.boundary.sensitive_clear = sensitive
        with pytest.raises(stream.StreamRejected, match="sensitive_fields_present"):
            await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        assert f.boundary.state().mode == "human" and f.boundary.authorized(token)
        assert "agent-admitted" not in f.events
    asyncio.run(scenario())


def test_expiry_denies_connected_input_and_never_resumes_agent(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        await take(f)
        f.connections[1] = f.boundary.input_token
        f.clock[0] += 11
        await f.handler.on_message("kd,97", conn_id=1)
        state = await f.boundary.reconcile()
        assert state.mode == "paused" and f.boundary.input_token is None
        assert "agent-admitted" not in f.events
        assert not any(e.startswith("input:") for e in f.events)
    asyncio.run(scenario())


def test_two_tabs_compete_and_old_token_does_not_regain_authority(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        other = f.boundary.add_viewer(control.OwnerBinding("owner", "c"*64, 1, "other"), can_take=True)
        state = await take(f)
        with pytest.raises(control.ControlRejected):
            await take(f, other)
        old_token = f.boundary.input_token
        await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        await take(f, other)
        assert f.boundary.input_token != old_token
        assert not f.boundary.authorized(old_token)
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["release", "clipboard", "sync", "observe", "publish"])
def test_unconfirmed_handback_stays_paused_without_agent_admission(tmp_path, failure):
    async def scenario():
        f = fixture(tmp_path)
        state = await take(f)

        async def fail(*args):
            raise RuntimeError("synthetic-failure")

        if failure == "release": f.handler.release_mouse_buttons = fail
        if failure == "clipboard": f.boundary.clear_clipboard = fail
        if failure == "sync": f.handler.xdisplay.sync = lambda: (_ for _ in ()).throw(RuntimeError())
        if failure == "observe": f.boundary.observe = fail
        if failure == "publish": f.boundary.publish = fail
        with pytest.raises(stream.StreamRejected, match="handback_unconfirmed"):
            await f.boundary.handback(f.desktop, lease_id=state.lease.lease_id, revision=state.revision)
        assert f.boundary.state().mode == "paused" and f.boundary.input_token is None
        assert "agent-admitted" not in f.events
    asyncio.run(scenario())


def test_paused_agent_admission_requires_matching_trusted_return_proof(tmp_path):
    f = fixture(tmp_path)
    state = asyncio.run(take(f))
    paused = f.c.begin_return(f.identity, f.desktop.owner, state.lease.lease_id, state.revision)
    for proof in (None, control.HumanReturnObservation(f.identity, f.phone.owner, paused.revision, True),
                  control.HumanReturnObservation(f.identity, f.desktop.owner, paused.revision-1, True),
                  control.HumanReturnObservation(f.identity, f.desktop.owner, paused.revision, False)):
        with pytest.raises(control.ControlRejected):
            f.c.admit_run(f.identity, f.desktop.owner,
                control.RunBinding("fresh", "session", "fresh-key"), lease_id=None,
                revision=paused.revision, handover=proof,
                previous=control.RunTerminalObservation("old-run", "session", "completed"))


def test_replaced_generation_cannot_receive_input_or_a_new_grant(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        await take(f)
        f.connections[1] = f.boundary.input_token
        f.boundary.current = lambda: "replacement-generation"
        await f.handler.on_message("kd,97", conn_id=1)
        await f.boundary.reconcile()
        with pytest.raises(stream.StreamRejected, match="stale_browser"):
            await take(f)
        assert f.boundary.state().mode == "paused"
        assert not any(e.startswith("input:") for e in f.events)
    asyncio.run(scenario())


def test_internal_punctuation_commit_is_reentrant_but_unbound_input_is_denied(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        await take(f)
        f.connections[1] = f.boundary.input_token

        async def punctuation(message, display_id="primary", conn_id=None):
            if message.startswith("kd,"):
                await f.handler.on_message("co,end,_")
            else:
                f.events.append(message)

        f.boundary._dispatch = punctuation
        await asyncio.wait_for(f.handler.on_message("kd,95", conn_id=1), timeout=1)
        await f.handler.on_message("co,end,forbidden", conn_id=None)
        assert "co,end,_" in f.events and "co,end,forbidden" not in f.events
    asyncio.run(scenario())


def test_background_atomic_repeat_cannot_inject_after_expiry_or_during_fence(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        f.handler.keyboard = SimpleNamespace(press=lambda key: f.events.append("physical-press"),
            release=lambda key: f.events.append("physical-release"))
        await take(f)
        f.boundary._bind_keyboard()
        f.handler.keyboard.press(95)
        async with f.boundary.input_lock:
            f.handler.keyboard.press(95)
        f.clock[0] += 11
        f.handler.keyboard.press(95)
        assert f.events.count("physical-press") == 1
    asyncio.run(scenario())


def test_expired_grant_is_drained_before_new_holder(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        await take(f)
        old = f.boundary.input_token
        f.handler.pressed_keys[97] = 1
        f.handler.button_mask = 1
        f.clock[0] += 11
        second = f.boundary.add_viewer(control.OwnerBinding("owner", "c"*64, 1, "second"), can_take=True)
        await f.boundary.take(second, request_id="new", revision=f.boundary.state().revision, auth_expires_at=2000)
        assert not f.handler.pressed_keys and f.handler.button_mask == 0
        assert f.events.index("release-keys") < len(f.events)-1
        assert f.boundary.input_token != old
    asyncio.run(scenario())


def test_disconnect_after_lease_expiry_still_drains(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        await take(f)
        token = f.boundary.input_token
        f.handler.pressed_keys[97] = 1
        f.clock[0] += 11
        await f.boundary.disconnect(token)
        assert f.boundary.input_token is None and not f.handler.pressed_keys
        assert f.boundary.state().mode == "paused"
    asyncio.run(scenario())


def test_session_churn_reclaims_idle_viewers_without_role_escalation(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        f.boundary._viewer_clock = lambda: f.clock[0]
        f.boundary._pinned_viewers.update((f.desktop.token, f.phone.token))
        old = None
        for n in range(25):
            child = await f.boundary.new_session(f.phone,
                control.OwnerBinding("owner", "d"*64, 1, "phone-"+str(n)), connected_tokens=set())
            assert not child.can_take
            old = old or child
            f.clock[0] += 20
        assert len(f.boundary.viewers) <= 16
        assert f.phone.token in f.boundary.viewers and f.desktop.token in f.boundary.viewers
        with pytest.raises(stream.StreamRejected): f.boundary.viewer(old.token)
    asyncio.run(scenario())


def test_session_capacity_preserves_connected_viewer_and_holder(tmp_path):
    async def scenario():
        f = fixture(tmp_path)
        f.boundary._viewer_clock = lambda: f.clock[0]
        f.boundary._pinned_viewers.update((f.desktop.token, f.phone.token))
        await take(f)
        children=[]
        for n in range(14):
            children.append(await f.boundary.new_session(f.phone,
                control.OwnerBinding("owner", "e"*64, 1, "connected-"+str(n)), connected_tokens=set()))
        f.clock[0] += 30
        with pytest.raises(stream.StreamRejected, match="viewer_capacity"):
            await f.boundary.new_session(f.phone, control.OwnerBinding("owner", "f"*64, 1, "overflow"),
                connected_tokens={v.token for v in children})
        assert f.desktop.token in f.boundary.viewers
        assert all(v.token in f.boundary.viewers for v in children)
    asyncio.run(scenario())


def test_explicit_phone_move_drains_old_input_and_starts_private(tmp_path):
    async def scenario():
        f=fixture(tmp_path)
        old=await take(f);old_token=f.boundary.input_token
        observed=f.c.observation_mode(f.identity,f.desktop.owner,old.lease.lease_id,old.revision,'observe')
        phone=f.boundary.add_viewer(f.phone.owner,can_take=True)
        entered,finish=asyncio.Event(),asyncio.Event()
        async def delayed(message,display_id='primary',conn_id=None):
            f.handler.pressed_keys[97]=True;entered.set();await finish.wait()
        f.boundary._dispatch=delayed;f.connections[1]=old_token
        active=asyncio.create_task(f.handler.on_message('kd,97',conn_id=1));await entered.wait()
        move=asyncio.create_task(f.boundary.move(phone,request_id='move-phone',revision=observed.revision,auth_expires_at=2000))
        await asyncio.sleep(0)
        assert not move.done() and f.c.state(f.identity).mode=='paused'
        assert not f.boundary.authorized(old_token)
        with pytest.raises(control.ControlRejected):
            f.c.authorize_observation(f.identity,f.desktop.owner,old.lease.lease_id,observed.lease.observation_epoch)
        finish.set();await active;state=await move
        assert state.lease.owner==phone.owner and state.lease.observation_mode=='private'
        assert f.boundary.input_token!=old_token and not f.handler.pressed_keys
        assert f.events.index('release-keys')<len(f.events)-1 and f.events[-1]=='native-fence'
        assert 'fresh-observation' not in f.events
        token=f.boundary.input_token
        await f.boundary.disconnect(old_token)
        assert f.boundary.input_token==token and f.boundary.authorized(token)
        replay=await f.boundary.move(phone,request_id='move-phone',revision=observed.revision,auth_expires_at=2000)
        assert replay.lease.lease_id==state.lease.lease_id and f.boundary.input_token==token
    asyncio.run(scenario())


@pytest.mark.parametrize('invalid',['view-only','foreign-owner','stale-revision'])
def test_phone_move_rejects_unqualified_requests_without_revoking(tmp_path,invalid):
    async def scenario():
        f=fixture(tmp_path);state=await take(f);token=f.boundary.input_token
        phone=f.phone if invalid=='view-only' else f.boundary.add_viewer(
            control.OwnerBinding('someone-else','c'*64,1,'other') if invalid=='foreign-owner' else f.phone.owner,can_take=True)
        with pytest.raises(stream.StreamRejected):
            await f.boundary.move(phone,request_id='move',revision=state.revision-1 if invalid=='stale-revision' else state.revision,auth_expires_at=2000)
        assert f.boundary.input_token==token and f.boundary.authorized(token)
    asyncio.run(scenario())


def test_phone_move_failed_drain_cannot_grant_input(tmp_path):
    async def scenario():
        f=fixture(tmp_path);state=await take(f);token=f.boundary.input_token
        phone=f.boundary.add_viewer(f.phone.owner,can_take=True)
        f.handler.xdisplay.query_keymap=lambda:[1]*32
        with pytest.raises(stream.StreamRejected,match='move_unconfirmed'):
            await f.boundary.move(phone,request_id='move',revision=state.revision,auth_expires_at=2000)
        assert f.boundary.input_token is None and f.boundary._blocked
        assert not f.boundary.authorized(token) and f.c.state(f.identity).lease is None
    asyncio.run(scenario())


def test_move_discards_an_observation_already_in_flight(tmp_path):
    from tests.test_selkies_platform import platform
    async def scenario():
        f=fixture(tmp_path);state=await take(f)
        state=f.c.observation_mode(f.identity,f.desktop.owner,state.lease.lease_id,state.revision,'observe')
        p=platform.Platform.__new__(platform.Platform);p.boundary=f.boundary;p.bridge=SimpleNamespace(_controller=f.c);p.owned=SimpleNamespace(identity=f.identity)
        ctx=SimpleNamespace(run_id='observer',dispatch_key='observer-dispatch')
        p.observers={(ctx.run_id,ctx.dispatch_key):(f.desktop.owner,state.lease.lease_id,state.lease.observation_epoch)}
        entered,finish=asyncio.Event(),asyncio.Event()
        async def capture():entered.set();await finish.wait();return {'page':'must-not-be-delivered'}
        p.snapshot=capture
        read=asyncio.create_task(p.observation(ctx));await entered.wait()
        phone=f.boundary.add_viewer(f.phone.owner,can_take=True)
        move=asyncio.create_task(f.boundary.move(phone,request_id='move',revision=state.revision,auth_expires_at=2000));await asyncio.sleep(0)
        assert not move.done() and f.c.state(f.identity).mode=='paused'
        finish.set()
        with pytest.raises(control.ControlRejected,match='browser_observation_denied'):await read
        assert (await move).lease.observation_mode=='private'
    asyncio.run(scenario())


@pytest.mark.parametrize('revocation', ['expiry', 'retirement'])
def test_late_platform_capture_cannot_outlive_lease_or_generation(tmp_path, revocation):
    from tests.test_selkies_platform import platform
    async def scenario():
        f = fixture(tmp_path)
        state = await take(f)
        state = f.c.observation_mode(f.identity, f.desktop.owner,
            state.lease.lease_id, state.revision, 'observe')
        p = platform.Platform.__new__(platform.Platform)
        p.boundary = f.boundary
        p.bridge = SimpleNamespace(_controller=f.c)
        p.owned = SimpleNamespace(identity=f.identity)
        context = SimpleNamespace(run_id='observer', dispatch_key='observer-dispatch')
        p.observers = {(context.run_id, context.dispatch_key):
            (f.desktop.owner, state.lease.lease_id, state.lease.observation_epoch)}
        entered, finish = asyncio.Event(), asyncio.Event()
        async def capture():
            entered.set()
            await finish.wait()
            return {'page': 'synthetic-withheld-page'}
        p.snapshot = capture
        read = asyncio.create_task(p.observation(context))
        await entered.wait()
        if revocation == 'expiry':
            f.clock[0] += 11
        else:
            f.c.retire_browser(f.identity, control.RetirementObservation(f.identity, True, True))
        finish.set()
        with pytest.raises(control.ControlRejected, match='browser_observation_denied'):
            await read
    asyncio.run(scenario())


@pytest.mark.parametrize("changed", [
    {"request_id": ""}, {"request_id": None},
    {"revision": None}, {"revision": True}, {"revision": "3"},
    {"auth_expires_at": 999}, {"auth_expires_at": float("nan")},
])
def test_malformed_phone_transfer_preserves_current_human_lease(tmp_path, changed):
    async def scenario():
        f = fixture(tmp_path)
        state = await take(f)
        token = f.boundary.input_token
        phone = f.boundary.add_viewer(f.phone.owner, can_take=True)
        values = {"request_id": "move", "revision": state.revision, "auth_expires_at": 2000, **changed}
        with pytest.raises(control.ControlRejected):
            await f.boundary.move(phone, **values)
        assert f.boundary.state() == state
        assert f.boundary.input_token == token and f.boundary.authorized(token)
        assert not f.boundary._blocked
    asyncio.run(scenario())
