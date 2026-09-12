"""Protected, bounded secret-file reads for deployment composition."""
from __future__ import annotations

import os
from pathlib import Path
import stat


class SecretFileError(ValueError):
    """A bounded secret-file refusal that never returns file content."""


def read_secret_file(path: str | Path, *, maximum_bytes: int = 16_384) -> str:
    target = Path(path)
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise SecretFileError("secret_file_not_regular")
            if metadata.st_uid not in {0, os.geteuid()}:
                raise SecretFileError("secret_file_owner_untrusted")
            if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_IROTH):
                raise SecretFileError("secret_file_permissions_too_broad")
            raw = source.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            raise SecretFileError("secret_file_too_large")
        value = raw.decode("utf-8").strip()
    except SecretFileError:
        raise
    except (OSError, UnicodeError):
        raise SecretFileError("secret_file_unreadable") from None
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise SecretFileError("secret_file_invalid")
    return value
