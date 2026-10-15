"""Independent execution/ingress/egress loops in the existing controller process.

Only execution advances work. Channel stalls cannot occupy that loop. Adapter
I/O retains its bounded timeout; these loops add no queue or runtime authority.
"""
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from time import monotonic

from radhouse.domain.tasks import Rejected, RuntimeFailure


class ControllerLoops:
    def __init__(self, controller, *, interval=5.0):
        if not 0.1 <= interval <= 60:
            raise ValueError('invalid_controller_interval')
        self.controller, self.interval = controller, interval
        self._stop, self._lock = Event(), Lock()
        self._threads = {}
        self._state = {phase: {'cycles': 0, 'errors': 0, 'error_code': None,
                              'last_completed_at': None, 'last_success_at': None}
                       for phase in ('execution', 'ingress', 'egress')}

    def run_once(self, phase):
        if phase == 'execution':
            cycle = self.controller.coordinator.run_once()
            return sum(item.error_code is not None for item in cycle.receipts)
        errors = 0
        for bridge in self.controller.conversations:
            try:
                receipt = bridge.run(phase)
                errors += receipt.get('error_code') is not None
            except Exception as error:
                # Do not leak transport arguments, prompts or private endpoints.
                code = error.code if isinstance(error, (Rejected, RuntimeFailure)) else 'conversation_internal_error'
                candidate = getattr(bridge, 'candidate', None)
                link = getattr(bridge, 'link', None)
                link_id = getattr(candidate or link, 'link_id', None)
                if link_id is not None:
                    try:
                        with self.controller.store.transaction() as tx:
                            tx.conversation_progress(link_id, error=code)
                    except Exception:
                        pass  # DB failure remains a loop error, never an acknowledgement.
                errors += 1
        return errors

    def _loop(self, phase):
        failures = 0
        while not self._stop.is_set():
            code = None
            try:
                errors = self.run_once(phase)
                if errors:
                    code = 'execution_cycle_error' if phase == 'execution' else 'conversation_cycle_error'
            except Exception as error:
                errors = 1
                code = error.code if isinstance(error, (Rejected, RuntimeFailure)) else 'controller_internal_error'
            now = datetime.now(timezone.utc).isoformat()
            with self._lock:
                state = self._state[phase]
                state.update(cycles=state['cycles'] + 1, errors=state['errors'] + errors,
                             error_code=code, last_completed_at=now)
                if code is None:
                    state['last_success_at'] = now
            failures = min(failures + 1, 6) if code else 0
            self._stop.wait(min(60, self.interval * 2 ** failures))

    def start(self):
        if self._threads or self._stop.is_set():
            raise RuntimeError('controller_loops_already_started')
        for phase in self._state:
            thread = Thread(target=self._loop, args=(phase,), name='radhouse-' + phase, daemon=True)
            self._threads[phase] = thread
            thread.start()

    def snapshot(self):
        with self._lock:
            return {phase: {**state, 'thread_alive': bool(self._threads.get(phase) and self._threads[phase].is_alive())}
                    for phase, state in self._state.items()}

    def stop(self, timeout=15):
        self._stop.set()
        deadline = monotonic() + timeout
        for thread in self._threads.values():
            thread.join(max(0, deadline - monotonic()))
        if any(thread.is_alive() for thread in self._threads.values()):
            raise Rejected('controller_shutdown_incomplete')
