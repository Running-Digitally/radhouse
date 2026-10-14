"""Privacy revocation must win a native snapshot already in flight."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_browser_control import control

spec=importlib.util.spec_from_file_location('platform_under_test',Path(__file__).parents[1]/'runtime/selkies/platform.py')
platform=importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


def test_private_waits_for_and_discards_inflight_observation(tmp_path):
    async def scenario():
        c=control.BrowserController(tmp_path/'control.sqlite3',maintenance_held=lambda:False)
        identity=control.BrowserIdentity('conversation','session','generation')
        run=control.RunBinding('old-run','session','old-dispatch')
        owner=control.OwnerBinding('alice','a'*64,1,'tab')
        state=c.bind_browser(identity,run,'alice')
        state=c.request_takeover(identity,owner,'take',revision=state.revision,auth_expires_at=10**10)
        state=c.confirm_takeover(identity,state.revision,control.FenceObservation(identity,state.takeover_after,True))
        state=c.observation_mode(identity,owner,state.lease.lease_id,state.revision,'observe')
        p=platform.Platform.__new__(platform.Platform)
        p.bridge=SimpleNamespace(_controller=c)
        p.owned=SimpleNamespace(identity=identity)
        p.boundary=SimpleNamespace(input_lock=asyncio.Lock(),transition_lock=asyncio.Lock())
        context=SimpleNamespace(run_id='observer',dispatch_key='observer-dispatch')
        p.observers={(context.run_id,context.dispatch_key):(owner,state.lease.lease_id,state.lease.observation_epoch)}
        capture_started=asyncio.Event();finish_capture=asyncio.Event()
        async def snapshot():
            capture_started.set();await finish_capture.wait()
            return {'secret':'must never be returned'}
        p.snapshot=snapshot
        read=asyncio.create_task(p.observation(context))
        await capture_started.wait()
        private=asyncio.create_task(p.visibility(owner,{'lease_id':state.lease.lease_id,'revision':state.revision,'mode':'private'}))
        await asyncio.sleep(0)
        assert c.state(identity).lease.observation_mode=='private'
        assert not private.done()
        finish_capture.set()
        with pytest.raises(control.ControlRejected,match='browser_observation_denied'):
            await read
        assert (await private).lease.observation_mode=='private'
        with pytest.raises(control.ControlRejected): await p.observation(context)
    asyncio.run(scenario())
