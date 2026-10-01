"""Real web admission and artifact retrieval, including unfinished terminal agent work."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from radhouse.api.app import create_app
from tests.test_local_reauthentication import local_client

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('controls', [False, True])
def test_artifact_work_browser_retains_blocked_outcome(local_client, service, fake_work, clock, tmp_path, controls):
    root = Path(__file__).resolve().parents[1]
    playwright = os.environ.get('RADHOUSE_PLAYWRIGHT_MODULE', str(root/'web/node_modules/@playwright/test/index.mjs'))
    assert Path(playwright).is_file()
    _, auth, totp, password = local_client
    service.durable_work_enabled = True
    if controls:
        fake_work.mode = 'running'
    clock.now = datetime.now(timezone.utc)
    sock = socket.socket(); sock.bind(('127.0.0.1',0))
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    auth._expected_origin = origin; auth.secure_cookie = False
    app = create_app(service,auth.auth_context,local_auth=auth,web_root=root/'web')
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread = threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    stop = threading.Event()
    def coordinate():
        while not stop.wait(0.2):
            for task_id in service.coordination_candidates(10):
                with service.store.transaction() as tx:
                    work = tx.work_for_task(task_id)
                blocked = 'blocked' in work.brief
                fake_work.result_content = json.dumps(dict(protocol='work-result-v1',work_id=work.work_id,
                    scope_revision=1,step_key='deliver-artifact',outcome='blocked' if blocked else 'succeeded',
                    summary='Dependency prevented delivery.' if blocked else 'Created the requested report.',
                    artifact=None if blocked else dict(name='report.md',media_type='text/markdown',
                        content='# Useful report\nSynthetic result.\n<script>window.unsafe=true</script>'),
                    reason_code='dependency_unavailable' if blocked else None,checkpoint=None))
                service.advance(task_id,'work-browser')
    worker = threading.Thread(target=coordinate,daemon=True)
    thread.start(); worker.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(0.02)
        script = 'work-controls-walkthrough.mjs' if controls else 'work-walkthrough.mjs'
        run = subprocess.run(['node',str(root/'web/test'/script)],env={**os.environ,
            'RADHOUSE_PLAYWRIGHT_MODULE':playwright,'RADHOUSE_BROWSER_ORIGIN':origin,
            'RADHOUSE_TEST_PASSWORD':password,'RADHOUSE_TEST_TOTP':totp.at(clock()),
            'RADHOUSE_SCREENSHOT':str(tmp_path/'work-outcomes.png')},capture_output=True,text=True,timeout=90)
        assert run.returncode == 0, run.stdout+run.stderr
        with service.store.transaction() as tx:
            work = tx.work_items('alice','personal-alice')
            if controls:
                assert len(work) == 1 and work[0].state == 'cancelled'
            else:
                assert len(work) == 2 and {row.state for row in work} == {'completed','waiting'}
        assert fake_work.start_count == 2
    finally:
        stop.set();server.should_exit=True
        worker.join(timeout=5);thread.join(timeout=5);sock.close()
