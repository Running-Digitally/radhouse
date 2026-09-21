import hashlib
import httpx
import pytest

from radhouse.channels.buzz_files import reference_files
from radhouse.domain.tasks import Rejected


class ImageRelay:
    origin = "https://relay.test"
    owner_attestation = None
    clock = staticmethod(lambda: 1_700_000_000)

    def __init__(self, content):
        self.content = content
        self.client = httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, content=self.content, headers={"content-type": "image/png"}
            )
        ))

    def event(self, *_args, **_kwargs):
        return {"id": "auth"}


def image_event(digest, url=None):
    url = url or f"https://relay.test/media/{digest}.png"
    return {
        "tags": [
            [
                "imeta",
                "url " + url,
                "m image/png",
                "x " + digest,
                "size 1024",
                "dim 1200x900",
                "blurhash placeholder",
                "thumb https://relay.test/media/thumb.png",
                "filename current-preview.png",
            ]
        ]
    }


def test_image_attachment_is_fetched_verified_and_retained_for_vision():
    content = b"synthetic-png-bytes"
    digest = hashlib.sha256(content).hexdigest()
    relay = ImageRelay(content)
    files = reference_files(relay, image_event(digest))
    relay.client.close()

    assert len(files) == 1
    assert files[0].name == "current-preview.png"
    assert files[0].media_type == "image/png"
    assert files[0].encoding == "base64"
    assert files[0].sha256 == digest
    assert files[0].bytes() == content


def test_image_fetch_keeps_the_exact_relay_origin_boundary():
    content = b"synthetic-png-bytes"
    digest = hashlib.sha256(content).hexdigest()
    relay = ImageRelay(content)
    with pytest.raises(Rejected, match="conversation_attachment_denied"):
        reference_files(
            relay,
            image_event(digest, "https://elsewhere.test/media/" + digest + ".png"),
        )
    relay.client.close()
