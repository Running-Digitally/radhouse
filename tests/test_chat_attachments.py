"""Attachment preparation, durable replay and authenticated original access."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import sqlite3
from uuid import uuid4
import wave
from zipfile import ZipFile, ZIP_DEFLATED

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from radhouse.chat.app import create_app, BoundedBody
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


def test_audio_unavailability_preserves_original_for_retry(chat):
    service,hermes = chat; key = str(uuid4()); calls = []
    class Speech:
        def transcribe(self,attachment):
            calls.append(1)
            if len(calls) == 1: raise Rejected("audio_transcription_unavailable",503)
            return "Now available"
    service.transcriber = Speech()
    with pytest.raises(Rejected,match="audio_transcription_unavailable"):
        service.send("alice",key,"",decode_uploads([upload("note.wav",wav())]))
    assert not hermes.requests and service.store.attachment("alice",key,0).data == wav()
    assert service.store.pending("alice")["error"] == "audio_transcription_unavailable"
    service.retry("alice",key)
    assert len(hermes.requests) == 1 and len(calls) == 2


def test_missing_audio_connection_and_no_speech_are_honest(chat):
    service,hermes = chat; files = decode_uploads([upload("note.wav",wav())]); key = str(uuid4())
    with pytest.raises(Rejected,match="audio_transcription_not_configured"): service.send("alice",key,"",files)
    assert service.store.history("alice")["turns"] == []
    class Silence:
        def transcribe(self,_): raise Rejected("audio_no_speech",422)
    service.transcriber = Silence()
    with pytest.raises(Rejected,match="audio_no_speech"): service.send("alice",key,"",files)
    assert service.store.pending("alice") is None
    service.send("alice",str(uuid4()),"Try text")
    assert len(hermes.requests) == 1


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
        key = str(uuid4()); body = {"request_id":key,"text":"","attachments":[upload("voice note.wav",wav())]}
        assert client.post("/chat/messages",json=body,headers=HEADERS).status_code == 401
        client.cookies.set(auth.cookie_name,"synthetic-cookie")
        assert client.post("/chat/messages",json=body,headers={"Origin":"http://127.0.0.1"}).status_code == 403
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


@pytest.mark.parametrize("name,data,code",[
    ("../image.png",PNG,"attachment_invalid"),("bad.txt",b"\x00secret","attachment_unsupported"),
    ("old.doc",b"old","attachment_unsupported"),("picture.svg",b"<svg/>","attachment_unsupported"),
    ("empty.txt",b"","attachment_empty"),("huge.txt",b"x"*(MAX_TEXT+1),"attachment_text_too_large"),
    ("huge.png",PNG+b"x"*MAX_IMAGE,"attachment_too_large"),("bad.wav",b"bad","attachment_invalid")])
def test_invalid_formats_and_limits_are_refused(name,data,code):
    with pytest.raises(Rejected,match=code): decode_uploads([upload(name,data)])


def test_file_count_image_total_and_invalid_base64_are_bounded():
    with pytest.raises(Rejected,match="attachments_too_many"): decode_uploads([upload("x.txt",b"x")]*5)
    with pytest.raises(Rejected,match="attachments_too_large"): decode_uploads([upload("x.png",PNG+b"x"*(3*1024*1024))]*3)
    with pytest.raises(Rejected,match="attachment_invalid"): decode_uploads([{"name":"x.txt","content":"%%%"}])


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
    with store.connection() as db: assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_chunked_request_is_bounded_before_json_parser(monkeypatch):
    import radhouse.chat.app as module
    monkeypatch.setattr(module,"MAX_REQUEST",10)
    calls = []; sent = []; messages = iter([{"type":"http.request","body":b"123456","more_body":True},{"type":"http.request","body":b"123456","more_body":False}])
    async def receive(): return next(messages)
    async def send(message): sent.append(message)
    async def downstream(*_): calls.append(1)
    asyncio.run(BoundedBody(downstream)({"type":"http","method":"POST"},receive,send))
    assert not calls and sent[0]["status"] == 413
