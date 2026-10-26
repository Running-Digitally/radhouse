"""Opt-in real Chrome qualification against an owned synthetic HTTP fixture."""
import asyncio
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from tests.test_browser_files import guest


async def eventually(probe):
    for _ in range(500):
        value = await probe()
        if value:
            return value
        await asyncio.sleep(.02)
    raise AssertionError("Synthetic browser condition did not complete")


def test_real_chooser_original_upload_download_and_private_outbox(tmp_path):
    executable = os.environ.get("RADHOUSE_TEST_CHROME")
    if not executable:
        root = Path(__file__).parents[1]
        module = os.environ.get("RADHOUSE_PLAYWRIGHT_MODULE", str(root / "web/node_modules/@playwright/test/index.mjs"))
        result = subprocess.run(["node", "--input-type=module", "-e",
            "import{pathToFileURL}from'node:url';const{chromium}=await import(pathToFileURL(process.argv[1]));console.log(chromium.executablePath());", module],
            capture_output=True, text=True, check=True, timeout=15)
        executable = result.stdout.strip()
    assert Path(executable).is_file(), "Install the qualification fixture's Chromium executable"
    async def scenario():
        content = bytes(range(256)) * 600
        received = []
        async def index(request):
            return web.Response(content_type="text/html", text='''<!doctype html><title>File bridge fixture</title>
                <input type="file" id="file" onchange="fetch('/upload',{method:'POST',body:this.files[0]}).then(r=>r.json()).then(r=>window.receipt=r)">
                <a id="download" href="/download" download>Download synthetic original</a>''')
        async def upload(request):
            data = await request.read(); received.append(data)
            return web.json_response({"sha256": hashlib.sha256(data).hexdigest()})
        async def download(request):
            return web.Response(body=content, headers={"Content-Disposition": 'attachment; filename="fixture.bin"'})
        app = web.Application(client_max_size=1024 * 1024)
        app.add_routes([web.get("/", index), web.post("/upload", upload), web.get("/download", download)])
        async with TestServer(app) as server:
            profile = tmp_path / "chrome"; profile.mkdir()
            process = await asyncio.create_subprocess_exec(executable,
                "--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--remote-debugging-port=0", "--user-data-dir=" + str(profile), "about:blank",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            files = guest.Files(tmp_path / "outbox", "a" * 32)
            try:
                async def port_file():
                    return (profile / "DevToolsActivePort").exists()
                await eventually(port_file)
                port, path = (profile / "DevToolsActivePort").read_text().splitlines()[:2]
                await files.start("ws://127.0.0.1:" + port + path)
                async def session_ready(): return next(iter(files.sessions), None)
                session = await eventually(session_ready)
                url = str(server.make_url("/"))
                await files.call("Page.navigate", {"url": url}, session)
                async def eval_js(expression):
                    return await files.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "userGesture": True}, session)
                async def page_ready(): return (await eval_js("Boolean(document.getElementById('file'))"))["result"].get("value")
                await eventually(page_ready)
                await eval_js("document.getElementById('file').click()")
                chooser = await eventually(files.chooser_state)
                assert chooser["destination"] == url
                identity = uuid4().hex
                await files.execute({"action": "begin", "id": identity, "chooser": chooser["id"],
                    "destination": url, "name": "original.bin", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
                for offset in range(0, len(content), guest.CHUNK):
                    await files.execute({"action": "write", "id": identity, "offset": offset,
                        "data": base64.b64encode(content[offset:offset + guest.CHUNK]).decode()})
                assert await files.execute({"action": "commit", "id": identity}) == {"applied": True}
                async def upload_ready(): return received
                await eventually(upload_ready)
                assert received == [content]
                for private, producer in [(True, "user"), (False, "assistant")]:
                    files.visibility(private, producer)
                    await eval_js("document.getElementById('download').click()")
                    async def completed():
                        return [row for row in (await files.execute({"action": "list"}))["downloads"] if row["state"] == "completed"]
                    rows = await eventually(completed)
                    assert len(rows) == 1
                    row = rows[0]
                    assert bool(row["private"]) == private and row["producer"] == producer
                    output = bytearray()
                    for offset in range(0, row["size"], guest.CHUNK):
                        value = await files.execute({"action": "read", "id": row["id"], "offset": offset})
                        output.extend(base64.b64decode(value["data"]))
                    assert output == content
                    await files.execute({"action": "ack", "id": row["id"], "sha256": row["sha256"]})
                await eval_js("document.getElementById('file').click()")
                chooser = await eventually(files.chooser_state)
                await files.call("Page.navigate", {"url": url + "?changed=1"}, session)
                async def cleared(): return files.chooser is None
                await eventually(cleared)
                with pytest.raises(ValueError, match="file_chooser_changed"):
                    await files.execute({"action": "begin", "id": uuid4().hex, "chooser": chooser["id"],
                        "destination": url, "name": "example.txt", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()})
            finally:
                await files.close()
                process.terminate()
                await process.wait()
    asyncio.run(scenario())
