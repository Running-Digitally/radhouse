"""Adapt the existing authoritative controller to acknowledged guest input fencing."""
import asyncio
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4

import radhouse_space_protocol as protocol


class InputLock:
    """Controller critical sections include guest input quiescence, not just a local mutex."""
    def __init__(self, client, publish):
        self.client, self.publish = client, publish
        self.local = asyncio.Lock()
        self.freeze_id = None

    def locked(self):
        return self.local.locked()

    async def __aenter__(self):
        await self.local.acquire()
        try:
            value = await self.client.call("freeze")
            self.freeze_id = protocol.identifier(value.get("freeze_id"))
            if value.get("drained") is not True:
                raise protocol.Uncertain("guest_input_not_drained")
            return self
        except BaseException:
            self.local.release()
            raise

    async def __aexit__(self, kind, value, traceback):
        try:
            # Publish current authority even when the critical section failed.
            # A failed handback cannot thaw an obsolete human grant.
            await self.publish()
            result = await self.client.call("thaw", freeze_id=self.freeze_id)
            if result.get("released") is not True:
                raise protocol.Uncertain("guest_input_release_unconfirmed")
        finally:
            self.freeze_id = None
            self.local.release()


def create(platform, bridge, owned):
    # A status request can reach ensure after the native idle reaper has
    # positively retired Chrome. Do not allocate a new stream for that stale
    # native session, or lose the old handle while asynchronous startup waits.
    chrome = platform._chrome
    if chrome is None or chrome.retired:
        raise protocol.Rejected("browser_generation_unavailable")
    stream = platform.load("radhouse_platform_control", Path(__file__).with_name("control.py"))

    class Boundary(stream.StreamingControl):
        async def _drain(self):
            if self.chrome.retired:
                return  # The positively acknowledged guest stop supersedes input drain.
            value = await self.remote.call("drain")
            if value.get("drained") is not True:
                self._blocked = True
                raise protocol.Uncertain("guest_input_not_drained")

    class RemotePlatform(platform.Platform):
        async def start(self):
            self.chrome = chrome
            from radhouse_browser_file_bridge import remember
            remember(bridge, owned, chrome.client)
            self.remote = self.chrome.client
            self.client_permissions = {}
            self.renewer = None
            self.sandbox = platform.load("radhouse_platform_sandbox", Path(__file__).with_name("sandbox.py"))
            control, native = bridge._control_modules()

            async def fence(state):
                handle = owned.channel.fence_after(uuid4().hex, owned.last_handle)
                owned.last_handle = handle
                ack = await handle.wait()
                if not isinstance(ack, native.FenceAck) or not ack.quiescent:
                    raise ValueError("native_fence_unconfirmed")
                return control.FenceObservation(owned.identity, state.takeover_after, True)

            async def publish(table):
                boundary = self.boundary
                # The guest receives an execution grant, never independent policy.
                if not boundary.authorized(boundary.input_token):
                    table = {k: v for k, v in table.items() if not v.get("mk_control")}
                ttl = self.ttl()
                state = bridge._controller.state(owned.identity)
                private = state.mode != "agent" and not (state.mode == "human" and state.lease and state.lease.observation_mode == "observe")
                result = await self.remote.call("publish", table=table, ttl=ttl,
                    not_after=time.time() + ttl, files={"private": private,
                    "producer": "assistant" if state.mode == "agent" else "user"})
                self.accept_status(result)

            async def resume(owner, revision, observation):
                self.handover = control.HumanReturnObservation(owned.identity, owner, revision, True)

            async def clear_clipboard():
                result = await self.remote.call("drain")
                return result.get("drained") is True

            self.boundary = boundary = Boundary(bridge._controller, owned.identity,
                fence=fence, observe=self.snapshot, publish=publish, resume=resume,
                current=lambda: owned.identity.generation if self.chrome.poll() is None and not self.chrome.unavailable else None,
                clear_clipboard=clear_clipboard, sensitive_clear=self.sensitive_clear)
            boundary.remote = self.remote
            boundary.chrome = self.chrome
            # No local X11 input. All injection and held-input tracking is in the guest.
            boundary.handler = SimpleNamespace(key_repeat_enabled=True)
            boundary._repeat_enabled = True
            boundary.input_lock = InputLock(self.remote, boundary._publish)
            await boundary.provision()
            self.renewer = asyncio.create_task(self.renew())
            self.renewer.add_done_callback(platform.consume_failure)
            self.watcher = asyncio.create_task(self.watch())
            self.watcher.add_done_callback(self.watch_finished)

        def ttl(self):
            state = bridge._controller.state(owned.identity)
            if self.boundary.input_token is not None and state.lease is not None:
                remaining = min(state.lease.expires_at, state.lease.auth_expires_at) - time.time()
                if remaining <= 0:
                    raise protocol.Rejected("controller_lease_expired")
                return min(protocol.GRANT_SECONDS, remaining)
            return protocol.GRANT_SECONDS

        def accept_status(self, value):
            connected = value.get("connected")
            if (value.get("state") != "running" or value.get("faulted") is not False or type(connected) is not list
                    or len(connected) > 32):
                raise protocol.Uncertain("guest_status_unconfirmed")
            for capability in connected:
                protocol.token(capability)
            self.client_permissions = {i: {"token": t} for i, t in enumerate(connected)}

        async def renew(self):
            try:
                while True:
                    await asyncio.sleep(.5)
                    # Publish the current controller table on every renewal.
                    # Expired/revoked human authority must not gain another TTL.
                    await self.boundary._publish()
            except asyncio.CancelledError:
                raise
            except Exception:
                # The guest independently expires the lease. Also fence local
                # admission; the existing watcher owns positive retirement.
                self.chrome.unavailable = True
                self.boundary._blocked = True
                self.boundary.input_token = None
                if self.chrome.tunnel is not None:
                    await asyncio.to_thread(self.chrome.tunnel.close)
                raise protocol.Uncertain("guest_lease_unconfirmed") from None

        async def cleanup(self):
            if self.chrome.unavailable and not self.chrome.retired:
                if not await asyncio.to_thread(self.chrome.reconcile_retirement):
                    raise protocol.Uncertain("guest_retirement_unconfirmed")
            await super().cleanup()

        async def stop_transport(self):
            if getattr(self, "renewer", None) is not None:
                self.renewer.cancel()
                await asyncio.gather(self.renewer, return_exceptions=True)
            if (self.retirement is not None and self.retirement.done()
                    and not self.retirement.cancelled() and self.retirement.exception() is not None):
                # A prior lost stop reply must not make cleanup permanently
                # fail after the host has positively retired that execution.
                if await asyncio.to_thread(self.chrome.reconcile_retirement):
                    # Finish the shared retirement path, including the native
                    # driver. Clearing the future would skip that completion.
                    self.retirement = asyncio.create_task(asyncio.to_thread(platform.retire))
                    self.retirement.add_done_callback(platform.consume_failure)
            await super().stop_transport()

    return RemotePlatform(bridge, owned)
