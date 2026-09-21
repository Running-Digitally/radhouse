import pytest

from radhouse.channels.buzz_files import reference_files
from radhouse.domain.tasks import Rejected


class TextOnlyRelay:
    origin = "https://relay.test"
    owner_attestation = None

    def event(self, *_args, **_kwargs):
        raise AssertionError("image notices must not fetch or authorize media")


def image_event(url="https://relay.test/media/" + "a" * 64 + ".png"):
    return {
        "tags": [
            [
                "imeta",
                "url " + url,
                "m image/png",
                "x " + "a" * 64,
                "size 1024",
                "dim 1200x900",
                "blurhash placeholder",
                "thumb https://relay.test/media/thumb.png",
                "filename current-preview.png",
            ]
        ]
    }


def test_image_attachment_becomes_an_explicit_text_only_notice():
    files = reference_files(TextOnlyRelay(), image_event())

    assert len(files) == 1
    assert files[0].name == "image-aaaaaaaa-notice.txt"
    assert "current-preview.png" in files[0].content
    assert "cannot inspect its pixels" in files[0].content


def test_image_notice_keeps_the_exact_relay_origin_boundary():
    with pytest.raises(Rejected, match="conversation_attachment_denied"):
        reference_files(
            TextOnlyRelay(),
            image_event("https://elsewhere.test/media/" + "a" * 64 + ".png"),
        )
