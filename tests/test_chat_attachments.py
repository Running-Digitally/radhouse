"""Attachment preparation, durable replay and authenticated original access."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import sqlite3
import hashlib
import os
from pathlib import Path
from uuid import uuid4
import wave
from zipfile import ZipFile, ZIP_DEFLATED

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from radhouse.chat.app import create_app
from radhouse.chat.attachments import decode_uploads, MAX_IMAGE, MAX_TEXT
from radhouse.chat.documents import extract_document
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.chat.transcription import Transcriber
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import SyntheticAuth, SyntheticHermes

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=")
HEADERS = {"Origin":"http://127.0.0.1", "X-Radhouse-CSRF":"synthetic-csrf"}


def upload(name, data): return {"name":name,"content":base64.b64encode(data).decode()}


def wav():
    data = BytesIO()
    with wave.open(data,"wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 1600)
    return data.getvalue()


def office(extension, text="A small plan"):
    data = BytesIO()
    with ZipFile(data,"w",ZIP_DEFLATED) as archive:
        if extension == ".docx":
            archive.writestr("word/document.xml",f'<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
        elif extension == ".pptx":
            archive.writestr("ppt/slides/slide1.xml",f'<p:slide xmlns:p="urn:slide" xmlns:a="urn:drawing"><a:t>{text}</a:t></p:slide>')
        else:
            archive.writestr("xl/workbook.xml",'<s:workbook xmlns:s="urn:sheet" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><s:sheets><s:sheet name="Plan" r:id="rId1"/></s:sheets></s:workbook>')
            archive.writestr("xl/_rels/workbook.xml.rels",'<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            archive.writestr("xl/sharedStrings.xml",f'<s:sst xmlns:s="urn:sheet"><s:si><s:t>{text}</s:t></s:si></s:sst>')
            archive.writestr("xl/worksheets/sheet1.xml",'<s:worksheet xmlns:s="urn:sheet"><s:sheetData><s:row><s:c r="A1" t="s"><s:v>0</s:v></s:c><s:c r="B1"><s:f>1+1</s:f><s:v>2</s:v></s:c></s:row></s:sheetData></s:worksheet>')
    return data.getvalue()


def pdf(text="A small plan", *, encrypted=False):
    writer = PdfWriter(); page = writer.add_blank_page(400,400)
    font = DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    if text:
        stream = DecodedStreamObject(); stream.set_data(f"BT /F1 12 Tf 40 340 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted: writer.encrypt("synthetic-only")
    data = BytesIO(); writer.write(data); return data.getvalue()


@pytest.fixture
def chat(tmp_path):
    hermes = SyntheticHermes(); service = ChatService(ChatStore(tmp_path / "chat.sqlite3"),hermes.client,owner_id="alice",clock=lambda:1000)
    yield service,hermes
    hermes.client.close()


@pytest.mark.parametrize("extension",[".docx",".xlsx",".pptx",".pdf"])
def test_each_document_format_is_read_and_sent_as_text(chat, extension):
    service,hermes = chat
    data = pdf() if extension == ".pdf" else office(extension)
    files = decode_uploads([upload("plan"+extension,data)])
    key = str(uuid4()); history = service.send("alice",key,"Summarize",files)
    assert "A small plan" in hermes.requests[0][1]["input"]
    if extension == ".xlsx": assert "B1: 2 [formula: 1+1]" in hermes.requests[0][1]["input"]
    assert service.store.attachment("alice",key,0).data == data
    assert history["turns"][0]["attachments"][0]["name"] == "plan"+extension


def test_image_and_code_are_preserved_across_restart_and_replay(chat):
    service,hermes = chat; key = str(uuid4()); hermes.lose_ack = True
    files = decode_uploads([upload("diagram.png",PNG),upload("hello.py",b"print('hello')")])
    with pytest.raises(Rejected,match="assistant_unavailable"): service.send("alice",key,"",files)
    first = hermes.requests[0][1]
    assert first["disable_tools"] is True
    content = first["input"][0]["content"]
    assert "print('hello')" in content[0]["text"]
    assert content[1]["image_url"]["url"] == "data:image/png;base64,"+base64.b64encode(PNG).decode()
    restarted = ChatService(ChatStore(service.store.path),hermes.client,owner_id="alice",clock=lambda:1001)
    restarted.retry("alice",key)
    assert hermes.requests[0] == hermes.requests[1]
    assert len(hermes.runs) == 1
    with pytest.raises(Rejected,match="message_conflict"): restarted.send("alice",key,"",files[::-1])
    changed = decode_uploads([upload("diagram.png",PNG),upload("hello.py",b"print('changed')")])
    with pytest.raises(Rejected,match="message_conflict"): restarted.send("alice",key,"",changed)


def test_audio_is_transcribed_once_then_frozen_across_lost_ack(chat):
    service,hermes = chat; key = str(uuid4()); calls = []
    class Speech:
        def transcribe(self,attachment): calls.append(attachment.data); return "Start with a simple conversation."
    service.transcriber = Speech(); hermes.lose_ack = True
    with pytest.raises(Rejected): service.send("alice",key,"",decode_uploads([upload("note.wav",wav())]))
    assert len(calls) == 1
    assert "Audio transcript" in hermes.requests[0][1]["input"]
    assert "simple conversation" in hermes.requests[0][1]["input"]
    restarted = ChatService(ChatStore(service.store.path),hermes.client,owner_id="alice",clock=lambda:1001)
    restarted.retry("alice",key)  # Frozen input needs no working STT on replay.
    assert hermes.requests[0] == hermes.requests[1]
    assert service.store.history("alice")["turns"][0]["attachments"][0]["transcript"].startswith("Start")


def test_audio_unavailability_preserves_original_and_frozen_not_read_outcome(chat):
    service,hermes = chat; key = str(uuid4()); calls = []
    class Speech:
        def transcribe(self,attachment):
            calls.append(1); raise Rejected("audio_transcription_unavailable",503)
    service.transcriber = Speech(); hermes.lose_ack = True
    with pytest.raises(Rejected,match="assistant_unavailable"):
        service.send("alice",key,"",decode_uploads([upload("note.wav",wav())]))
    assert service.store.attachment("alice",key,0).data == wav()
    assert "original saved, not read" in hermes.requests[0][1]["input"]
    service.retry("alice",key)
    assert len(calls) == 1 and hermes.requests[0] == hermes.requests[1]
    assert service.store.history("alice")["turns"][0]["attachments"][0]["reading_state"] == "not_read"


def test_missing_audio_connection_is_honest_and_does_not_block_transfer(chat):
    service,hermes = chat; key = str(uuid4())
    history = service.send("alice",key,"",decode_uploads([upload("note.wav",wav())]))
    assert "audio_transcription_not_configured" in hermes.requests[0][1]["input"]
    assert history["turns"][0]["attachments"][0]["transcript"] is None
    assert service.store.attachment("alice",key,0).data == wav()


def test_concurrent_audio_retries_share_prepared_input(chat):
    service,hermes = chat; calls = []
    class Speech:
        def transcribe(self,_): calls.append(1); return "One transcript"
    service.transcriber = Speech(); files = decode_uploads([upload("note.wav",wav())]); key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _:service.send("alice",key,"",files),range(2)))
    assert len(calls) == len(hermes.requests) == 1


def test_original_download_requires_owner_and_supports_audio_range(chat):
    service,hermes = chat; auth = SyntheticAuth(); service.transcriber = type("Speech",(),{"transcribe":lambda _,a:"Hello"})()
    with TestClient(create_app(auth,service),base_url="http://127.0.0.1") as client:
        key = str(uuid4()); file_id = str(uuid4())
        body = {"request_id":key,"text":"","attachments":[file_id]}
        assert client.post("/chat/messages",json=body,headers=HEADERS).status_code == 401
        client.cookies.set(auth.cookie_name,"synthetic-cookie")
        assert client.post("/chat/messages",json=body,headers={"Origin":"http://127.0.0.1"}).status_code == 403
        assert client.put(f"/chat/files/{file_id}?name=voice%20note.wav",content=wav(),headers=HEADERS).status_code == 200
        assert client.post("/chat/messages",json=body,headers=HEADERS).status_code == 200
        assert client.post(f"/chat/messages/{key}/retry",json={}).status_code == 403
        assert client.post(f"/chat/messages/{key}/retry",json={},headers=HEADERS).status_code == 200
        path = f"/chat/messages/{key}/attachments/0"
        reply = client.get(path); assert reply.content == wav()
        assert reply.headers["content-disposition"].startswith("inline;")
        assert reply.headers["x-content-type-options"] == "nosniff"
        assert "attachment;" in client.get(path+"?download=true").headers["content-disposition"]
        part = client.get(path,headers={"Range":"bytes=4-9"}); assert part.status_code == 206 and part.content == wav()[4:10]
        assert client.get(path,headers={"Range":"bytes=999999-"}).status_code == 416
        assert client.get(path.replace(key,str(uuid4()))).status_code == 404
        auth.principal = "bob"; assert client.get(path).status_code == 403
        auth.active = False; assert client.get(path).status_code == 401


def test_names_and_base64_fixture_syntax_are_validated():
    with pytest.raises(Rejected,match="attachment_invalid"): decode_uploads([upload("../image.png",PNG)])
    with pytest.raises(Rejected,match="attachment_invalid"): decode_uploads([{"name":"x.txt","content":"%%%"}])
    # Unknown, legacy, binary and empty originals are retained for later access.
    assert decode_uploads([upload("old.doc",b"old")])[0].kind == "file"
    assert decode_uploads([upload("binary.bin",b"\x00secret")])[0].kind == "file"
    assert decode_uploads([upload("empty.txt",b"")])[0].size == 0


@pytest.mark.parametrize("data,code",[(pdf(""),"document_needs_ocr"),(pdf(encrypted=True),"document_encrypted")])
def test_scanned_and_encrypted_pdf_do_not_claim_readable_content(data,code):
    attachment = decode_uploads([upload("scan.pdf",data)])[0]
    with pytest.raises(Rejected,match=code): extract_document(attachment)


def test_office_expansion_and_xml_entities_are_refused():
    data = BytesIO()
    with ZipFile(data,"w",ZIP_DEFLATED) as archive: archive.writestr("word/document.xml",b"x"*1000000)
    with pytest.raises(Rejected,match="document_too_complex"): extract_document(decode_uploads([upload("bomb.docx",data.getvalue())])[0])
    data = BytesIO()
    with ZipFile(data,"w") as archive: archive.writestr("word/document.xml",b'<!DOCTYPE x [<!ENTITY e "injected">]><x>&e;</x>')
    with pytest.raises(Rejected,match="document_unreadable"): extract_document(decode_uploads([upload("entities.docx",data.getvalue())])[0])


def test_transcriber_uses_fixed_endpoint_multipart_and_bounds_result():
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url == "http://127.0.0.1:9000/v1/audio/transcriptions"
        assert b'filename="note.wav"' in request.content and wav() in request.content
        return httpx.Response(200,json={"text":"Spoken words"})
    transcriber = Transcriber("http://127.0.0.1:9000/v1/audio/transcriptions",transport=httpx.MockTransport(respond))
    assert transcriber.transcribe(decode_uploads([upload("note.wav",wav())])[0]) == "Spoken words"
    transcriber.close(); assert len(calls) == 1
    with pytest.raises(ValueError): Transcriber("http://example.com/v1/audio/transcriptions")
    for value,code in [({"text":""},"audio_no_speech"),({"text":"x"*(MAX_TEXT+1)},"attachment_text_too_large"),({"text":"x"*(MAX_TEXT*6+32769)},"audio_transcription_unavailable")]:
        client = Transcriber("http://127.0.0.1/v1/audio/transcriptions",transport=httpx.MockTransport(lambda _:httpx.Response(200,json=value)))
        with pytest.raises(Rejected,match=code): client.transcribe(decode_uploads([upload("note.wav",wav())])[0])
        client.close()


def test_schema_one_upgrade_retains_existing_pending_receipt(tmp_path):
    path = tmp_path / "legacy.sqlite3"; path.touch(mode=0o600)
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE conversations(owner TEXT PRIMARY KEY,session_id TEXT);
            CREATE TABLE turns(seq INTEGER PRIMARY KEY,owner TEXT,request_id TEXT,text TEXT,dispatch_key TEXT,created_at REAL,retry_until REAL,run_id TEXT,status TEXT,output TEXT,error TEXT);
            INSERT INTO conversations VALUES('alice','chat:old');
            INSERT INTO turns VALUES(1,'alice','old-request','Keep me','chat:saved',1000,4000,'run_old','running',NULL,NULL);
            PRAGMA user_version=1;''')
    store = ChatStore(path)
    assert store.session_id("alice") == "chat:old"
    assert store.find("alice","old-request")["input_text"] == "Keep me"
    assert store.pending("alice")["run_id"] == "run_old"
    assert store.history("alice")["turns"][0]["attachments"] == []
    with store.connection() as db: assert db.execute("PRAGMA user_version").fetchone()[0] == 3


def test_large_stream_upload_and_many_files_do_not_expand_prompt_or_duplicate_storage(chat):
    service,hermes = chat; auth = SyntheticAuth()
    with TestClient(create_app(auth,service),base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name,"synthetic-cookie")
        # Exceeds all former document, aggregate and HTTP size thresholds.
        chunk = b"large original line\n" * 32768
        count = 60; size = len(chunk) * count; file_id = str(uuid4())
        def chunks():
            for _ in range(count): yield chunk
        reply = client.put(f"/chat/files/{file_id}?name=large.txt",content=chunks(),headers=HEADERS)
        assert reply.status_code == 200 and reply.json()["size"] == size > 34*1024*1024
        attachment = service.store.upload("alice",file_id)
        assert isinstance(attachment.data,Path) and attachment.data.stat().st_size == size
        expected = hashlib.sha256()
        for _ in range(count): expected.update(chunk)
        assert attachment.sha256 == expected.hexdigest()
        assert attachment.data.stat().st_mode & 0o777 == 0o600
        assert service.store.files_path.stat().st_mode & 0o777 == 0o700
        assert client.put(f"/chat/files/{file_id}?name=large.txt",content=chunks(),headers=HEADERS).json() == reply.json()
        assert client.put(f"/chat/files/{file_id}?name=large.txt",content=b"different",headers=HEADERS).status_code == 409
        assert len(list(service.store.files_path.iterdir())) == 1
        files = [file_id]
        for i in range(6):
            other = str(uuid4()); files.append(other)
            assert client.put(f"/chat/files/{other}?name=note{i}.txt",content=b"small",headers=HEADERS).status_code == 200
        key = str(uuid4()); hermes.lose_ack = True
        body = {"request_id":key,"text":"Consider what you can read","attachments":files}
        assert client.post("/chat/messages",json=body,headers=HEADERS).status_code == 503
        restarted = ChatService(ChatStore(service.store.path),hermes.client,owner_id="alice",clock=lambda:1001)
        restarted.retry("alice",key)
        assert hermes.requests[0] == hermes.requests[1] and len(hermes.runs) == 1
        assert len(hermes.requests[0][1]["input"].encode()) < 262144
        history = client.get("/chat/history").json()["turns"][0]
        assert len(history["attachments"]) == 7 and history["attachments"][0]["reading_state"] == "excerpt"
        with service.store.connection() as db:
            assert db.execute("SELECT length(data),file_id FROM attachments ORDER BY position").fetchone()[0] == 0
        path = f"/chat/messages/{key}/attachments/0"
        part = client.get(path,headers={"Range":f"bytes={size-20}-{size-1}"})
        assert part.status_code == 206 and part.content == chunk[-20:]
        assert client.get(f"/chat/messages/{key}/attachments/6").content == b"small"
        # Download streaming verification avoids materializing the large original.
        digest = hashlib.sha256()
        with client.stream("GET",path) as response:
            for block in response.iter_bytes(): digest.update(block)
        assert digest.hexdigest() == expected.hexdigest()


def test_upload_checks_owner_csrf_and_origin_before_consuming_stream(chat):
    service,_ = chat; auth = SyntheticAuth(); app = create_app(auth,service)
    async def attempt(headers):
        consumed = []
        async def body(): consumed.append(1); yield b"private bytes"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            response = await client.put(f"/chat/files/{uuid4()}?name=secret.txt",content=body(),headers=headers)
        assert not consumed
        return response.status_code
    assert asyncio.run(attempt(HEADERS)) == 401
    cookie = {**HEADERS,"Cookie":"radhouse_session=synthetic-cookie"}
    # Derive the actual synthetic cookie name, not a hardcoded product name.
    cookie["Cookie"] = auth.cookie_name + "=synthetic-cookie"
    assert asyncio.run(attempt({"Cookie":cookie["Cookie"],"Origin":"http://127.0.0.1"})) == 403
    assert asyncio.run(attempt({**cookie,"Origin":"https://evil.test"})) == 403
    auth.principal = "bob"
    assert asyncio.run(attempt(cookie)) == 403
    assert list(service.store.files_path.iterdir()) == []


def test_interrupted_and_failed_storage_leave_no_partial_upload(chat, monkeypatch):
    service,_ = chat; auth = SyntheticAuth(); app = create_app(auth,service)
    async def interrupted():
        async def body(): yield b"first chunk"; raise RuntimeError("lost client")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1",cookies={auth.cookie_name:"synthetic-cookie"}) as client:
            with pytest.raises(ExceptionGroup) as failure:
                await client.put(f"/chat/files/{uuid4()}?name=note.txt",content=body(),headers=HEADERS)
            assert isinstance(failure.value.exceptions[0], RuntimeError)
            assert str(failure.value.exceptions[0]) == "lost client"
    asyncio.run(interrupted())
    assert list(service.store.files_path.iterdir()) == []
    with service.store.connection() as db: assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0
    def unavailable(*_): raise OSError("synthetic storage failure")
    monkeypatch.setattr(service.store,"commit_upload",unavailable)
    with TestClient(app,base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name,"synthetic-cookie")
        response = client.put(f"/chat/files/{uuid4()}?name=note.txt",content=b"note",headers=HEADERS)
        assert response.status_code == 507 and response.json()["error"] == "file_storage_unavailable"
    assert list(service.store.files_path.iterdir()) == []


def test_unreadable_document_and_oversize_images_remain_saved(chat):
    service,hermes = chat; key = str(uuid4())
    files = decode_uploads([upload("encrypted.pdf",pdf(encrypted=True)),
        upload("huge.png",PNG+b"x"*MAX_IMAGE), *[upload(f"image{i}.png",PNG) for i in range(5)]])
    history = service.send("alice",key,"Keep the originals",files)
    saved = history["turns"][0]["attachments"]
    assert len(saved) == 7
    assert saved[0]["reading_error"] == "document_encrypted" and saved[0]["reading_state"] == "not_read"
    assert saved[1]["reading_state"] == saved[-1]["reading_state"] == "not_read"
    content = hermes.requests[0][1]["input"][0]["content"]
    assert len([c for c in content if c["type"] == "image_url"]) == 4
    assert service.store.attachment("alice",key,1).size > MAX_IMAGE


def test_upload_writes_before_request_finishes(chat):
    service,_ = chat; auth = SyntheticAuth(); file_id = str(uuid4())
    async def stream_proof():
        first = b'\x00original block' * 65536
        async def body():
            yield first
            temporary = list(service.store.files_path.iterdir())
            assert len(temporary) == 1 and temporary[0].stat().st_size == len(first)
            with service.store.connection() as db:
                assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0
            yield b"last block"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(auth,service)),base_url="http://127.0.0.1",cookies={auth.cookie_name:"synthetic-cookie"}) as client:
            reply = await client.put(f"/chat/files/{file_id}?name=original.bin",content=body(),headers=HEADERS)
            assert reply.status_code == 200 and reply.json()["size"] == len(first)+10
    asyncio.run(stream_proof())
    assert service.store.upload("alice",file_id).data.is_file()


def test_large_inventory_is_saved_even_when_this_reading_omits_entries(chat):
    service,hermes = chat; key = str(uuid4()); hermes.lose_ack = True
    files = decode_uploads([upload(f"original{i}.txt",b"") for i in range(1000)])
    with pytest.raises(Rejected,match="assistant_unavailable"):
        service.send("alice",key,"\U0001F603"*16000,files)
    service.retry("alice",key)
    assert hermes.requests[0] == hermes.requests[1]
    prompt = hermes.requests[0][1]["input"]
    assert len(prompt.encode()) < 262144 and "additional originals are saved" in prompt
    assert len(service.store.history("alice")["turns"][0]["attachments"]) == 1000
    assert service.store.attachment("alice",key,999).size == 0


def test_schema_two_upgrade_retains_blob_and_frozen_unacknowledged_input(tmp_path):
    path = tmp_path / "schema2.sqlite3"; path.touch(mode=0o600)
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE conversations(owner TEXT PRIMARY KEY,session_id TEXT);
            CREATE TABLE turns(seq INTEGER PRIMARY KEY,owner TEXT,request_id TEXT,text TEXT,dispatch_key TEXT,created_at REAL,retry_until REAL,run_id TEXT,status TEXT,output TEXT,error TEXT,input_text TEXT);
            CREATE TABLE attachments(turn_seq INTEGER,position INTEGER,name TEXT,media_type TEXT,kind TEXT,sha256 TEXT,data BLOB,reference_text TEXT,PRIMARY KEY(turn_seq,position));
            INSERT INTO conversations VALUES('alice','chat:old');
            INSERT INTO turns VALUES(1,'alice','old-request','Keep me','chat:saved',1000,4000,NULL,'awaiting_dispatch',NULL,NULL,'Frozen existing input');
            PRAGMA user_version=2;''')
        db.execute("INSERT INTO attachments VALUES(1,0,'voice.wav','audio/wav','audio',?,?,?)",(hashlib.sha256(wav()).hexdigest(),wav(),"Saved transcript"))
    hermes = SyntheticHermes()
    try:
        service = ChatService(ChatStore(path),hermes.client,owner_id="alice",clock=lambda:1001)
        service.retry("alice","old-request")
        assert hermes.requests[0][1]["input"] == "Frozen existing input"
        assert service.store.attachment("alice","old-request",0).data == wav()
        assert service.store.history("alice")["turns"][0]["attachments"][0]["transcript"] == "Saved transcript"
        assert service.store.session_id("alice") == "chat:old"
    finally: hermes.client.close()
