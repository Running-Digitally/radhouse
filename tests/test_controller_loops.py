from threading import Event
from types import SimpleNamespace
from time import monotonic

import pytest

from radhouse.application.controller_loops import ControllerLoops


def test_stalled_buzz_ingress_and_failed_egress_do_not_block_execution():
    blocked, release, progressed = Event(), Event(), Event()
    class Bridge:
        def run(self, phase):
            if phase == 'ingress':
                blocked.set()
                release.wait(5)
            else:
                raise RuntimeError('private data must not appear in status')
            return {'error_code': None}
    class Coordinator:
        count = 0
        def run_once(self):
            self.count += 1
            if self.count >= 3: progressed.set()
            return SimpleNamespace(receipts=())
    controller = SimpleNamespace(coordinator=Coordinator(), conversations=(Bridge(),))
    loops = ControllerLoops(controller, interval=0.1)
    loops.start()
    try:
        assert blocked.wait(2) and progressed.wait(3)
        state = loops.snapshot()
        assert state['execution']['cycles'] >= 3
        assert state['ingress']['cycles'] == 0
        assert state['egress']['error_code'] == 'conversation_cycle_error'
        assert 'private data' not in repr(state)
    finally:
        release.set()
        loops.stop()
    assert not any(state['thread_alive'] for state in loops.snapshot().values())


def test_adapter_failure_does_not_starve_other_channel_in_the_same_cycle():
    visited = []
    class Broken:
        def run(self, _): raise RuntimeError('failed')
    class Ready:
        def run(self, phase):
            visited.append(phase)
            return {'error_code': None}
    loops = ControllerLoops(SimpleNamespace(conversations=(Broken(), Ready())), interval=0.1)
    assert loops.run_once('ingress') == 1 and visited == ['ingress']


@pytest.mark.parametrize('interval', [0, 61, float('nan')])
def test_invalid_loop_interval_is_refused(interval):
    with pytest.raises(ValueError): ControllerLoops(None, interval=interval)


@pytest.mark.parametrize('enabled', [False, True])
def test_serialized_cli_refuses_owned_artifact_route_even_when_admission_is_disabled(monkeypatch, capsys, enabled):
    import json
    import radhouse.cli as cli
    config = SimpleNamespace(durable_work_enabled=enabled,
        buzz=SimpleNamespace(conversations=(SimpleNamespace(workflow_version='artifact-v1'),)))
    monkeypatch.setattr(cli, 'load_config', lambda *_: config)
    monkeypatch.setattr(cli, 'compose_controller', lambda *_: pytest.fail('serial path must not compose'))
    assert cli.main(['coordinator-once', '--config', 'synthetic']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'independent_cycles_required'
