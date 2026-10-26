"""Closed controller-to-browser protocol; no SPACE management operations."""
import math
import importlib.util
from pathlib import Path
import re
import time

SCHEMA = "radhouse.space-browser.v1"
MAX_BODY = 64 * 1024
MAX_FRAME = 8 * 1024 * 1024
GRANT_SECONDS = 3.0
OPERATIONS = frozenset({"start", "status", "stop", "publish", "renew", "freeze", "thaw", "drain", "files"})


class Rejected(ValueError):
    """Fixed code only. Callers must not include request or response contents."""


class Uncertain(RuntimeError):
    """A mutation may have happened. Never retry or replace automatically."""


def identifier(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{32}", value) is None:
        raise Rejected("invalid_identity")
    return value


def token(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is None:
        raise Rejected("invalid_capability")
    return value


def request(value):
    if type(value) is not dict or set(value) != {"schema", "launch_id", "request_id", "sequence", "op", "body"}:
        raise Rejected("invalid_request")
    if value["schema"] != SCHEMA or type(value["op"]) is not str or value["op"] not in OPERATIONS:
        raise Rejected("invalid_request")
    identifier(value["launch_id"])
    identifier(value["request_id"])
    if type(value["sequence"]) is not int or not 1 <= value["sequence"] < 2**53:
        raise Rejected("invalid_sequence")
    body = value["body"]
    if value["op"] == "files":
        # The file module owns the closed per-action shape; never a path or CDP command.
        spec = importlib.util.spec_from_file_location("space_file_contract", Path(__file__).with_name("browser_files.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate(body)
        return value
    fields = {"publish": {"table", "ttl", "not_after"}, "renew": {"ttl", "not_after"}, "thaw": {"freeze_id"}}.get(value["op"], set())
    if value["op"] == "publish" and type(body) is dict and "files" in body:
        fields = fields | {"files"}
        if (type(body["files"]) is not dict or set(body["files"]) != {"private", "producer"}
                or type(body["files"]["private"]) is not bool or body["files"]["producer"] not in {"user", "assistant"}):
            raise Rejected("invalid_file_visibility")
    if type(body) is not dict or set(body) != fields:
        raise Rejected("invalid_request")
    if "ttl" in fields:
        duration(body["ttl"])
        if type(body["not_after"]) not in {int, float} or not math.isfinite(body["not_after"]) or body["not_after"] <= 0:
            raise Rejected("invalid_grant_deadline")
    if "table" in fields:
        grants(body["table"])
    if "freeze_id" in fields:
        identifier(body["freeze_id"])
    return value


def duration(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= GRANT_SECONDS:
        raise Rejected("invalid_grant_duration")
    return value


def grants(table):
    if type(table) is not dict or len(table) > 17:
        raise Rejected("invalid_grants")
    holders = []
    for capability, value in table.items():
        token(capability)
        if (type(value) is not dict or set(value) not in ({"role", "slot"}, {"role", "slot", "mk_control"})
                or value["role"] != "viewer" or value["slot"] is not None
                or "mk_control" in value and value["mk_control"] is not True):
            raise Rejected("invalid_grants")
        if value.get("mk_control"):
            holders.append(capability)
    if len(holders) > 1:
        raise Rejected("multiple_controllers")
    return holders[0] if holders else None


class GrantFence:
    """Guest-side execution fence. The external browser controller owns policy.

    Expiration latches: delayed renewals cannot resurrect a dead grant. Only an
    new launch may establish permissions again. The host treats a renewal
    failure as uncertain and retires the generation before replacement.
    """
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.table = {}
        self.input_token = None
        self.deadline = 0.0
        self.expired = True
        self.freeze_id = None
        self.initialized = False

    def live(self):
        if self.clock() >= self.deadline:
            self.expired = True
        return not self.expired

    def allowed(self, capability):
        return bool(self.live() and self.freeze_id is None and capability is not None
                    and capability == self.input_token)

    def publish(self, table, ttl):
        holder = grants(table)
        duration(ttl)
        if self.initialized and not self.live():
            raise Rejected("grant_expired")
        self.table = {k: dict(v) for k, v in table.items()}
        self.input_token = holder
        self.deadline = self.clock() + ttl
        self.expired = False
        self.initialized = True

    def renew(self, ttl):
        duration(ttl)
        if not self.live():
            raise Rejected("grant_expired")
        self.deadline = self.clock() + ttl

    def freeze(self, request_id):
        identifier(request_id)
        if self.freeze_id is not None:
            raise Rejected("input_already_frozen")
        self.freeze_id = request_id

    def thaw(self, freeze_id):
        identifier(freeze_id)
        if self.freeze_id != freeze_id or not self.live():
            raise Rejected("input_release_unconfirmed")
        self.freeze_id = None

    def revoke(self):
        self.expired = True
        self.table = {}
        self.input_token = None
