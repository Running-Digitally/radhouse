"""Explicit loopback-only proxy selection; never inherit ambient proxy settings."""
import re


def push_proxy(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_push_proxy")
    match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", value)
    if match is None or not 1024 <= int(match[1]) <= 65535:
        raise ValueError("invalid_push_proxy")
    return value
