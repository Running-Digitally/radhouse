"""Optional adapter to the existing fixed OpenAI-compatible STT service."""
import ipaddress
import json
from urllib.parse import urlsplit

import httpx
from radhouse.domain.tasks import Rejected
from .attachments import MAX_TEXT


class Transcriber:
    def __init__(self, endpoint, *, bearer=None, transport=None):
        url = urlsplit(endpoint)
        if (url.scheme not in {"https","http"} or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path != "/v1/audio/transcriptions"):
            raise ValueError("invalid_transcription_endpoint")
        if url.scheme == "http":
            try: address = ipaddress.ip_address(url.hostname)
            except ValueError: raise ValueError("invalid_transcription_endpoint") from None
            if not (address.is_private or address.is_loopback): raise ValueError("invalid_transcription_endpoint")
        if bearer is not None and (not bearer or any(ord(c)<=32 or ord(c)>126 for c in bearer)):
            raise ValueError("invalid_transcription_bearer")
        self.endpoint = endpoint
        self.client = httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(120,connect=5),
            headers={"Authorization":"Bearer "+bearer} if bearer else {}, transport=transport)

    def close(self): self.client.close()

    def transcribe(self, attachment):
        try:
            with attachment.open() as audio, self.client.stream("POST", self.endpoint, data={"model":"whisper-1","response_format":"json","temperature":"0"},
                    files={"file":(attachment.name,audio,attachment.media_type)}) as response:
                if response.status_code != 200: raise Rejected("audio_transcription_unavailable",503)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>MAX_TEXT*6+32768: raise Rejected("audio_transcription_unavailable",503)
                value = json.loads(body)
                text = value.get("text") if isinstance(value,dict) else None
                if not isinstance(text,str) or not text.strip() or "\x00" in text:
                    raise Rejected("audio_no_speech",422)
                if len(text.encode()) > MAX_TEXT: raise Rejected("attachment_text_too_large",422)
                return text
        except (httpx.HTTPError,ValueError):
            raise Rejected("audio_transcription_unavailable",503) from None
