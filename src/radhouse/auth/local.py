"""Database-backed local accounts with password, TOTP and revocable sessions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
import psycopg
from psycopg.rows import dict_row
import pyotp
from starlette.requests import Request

from radhouse.domain.access import AuthContext
from radhouse.domain.tasks import Rejected
from radhouse.storage.postgres import (
    ApplicationStorageError,
    _application_connection_parameters,
    schema_digest,
)


_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class LocalAuthError(ValueError):
    """A bounded local-authentication configuration or operation failure."""


@dataclass(frozen=True)
class LocalSession:
    token: str
    csrf_token: str
    principal_id: str
    username: str
    assurance_until: datetime
    conversation_id: str
    binding_revision: int
    project_id: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _username(value: str) -> str:
    normalized = value.strip().lower()
    if not _USERNAME.fullmatch(normalized):
        raise LocalAuthError("invalid_username")
    return normalized


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise LocalAuthError("invalid_local_auth_key") from None


def _verified_connection(connection, deployment_id: str, database: str) -> None:
    rows = connection.execute(
        "SELECT deployment_id,schema_version,migration_sha256,current_database() AS database "
        "FROM public.radhouse_metadata WHERE singleton"
    ).fetchall()
    if (
        len(rows) != 1
        or rows[0]["deployment_id"] != deployment_id
        or rows[0]["schema_version"] != 1
        or rows[0]["migration_sha256"] != schema_digest()
        or rows[0]["database"] != database
    ):
        raise LocalAuthError("database_identity_mismatch")


def provision_local_user(
    dsn: str,
    *,
    expected_database: str,
    deployment_id: str,
    encryption_key: str,
    principal_id: str,
    username: str,
    role: str,
    password: str,
    totp_secret: str,
    project_id: str,
    project_name: str,
    bot_id: str,
    bot_display_name: str,
    bot_role_name: str,
    provider_binding: str,
    now: datetime | None = None,
) -> None:
    """Create one explicitly scoped local user and its initial work-home grant."""
    normalized = _username(username)
    if role not in {"admin", "operator", "viewer"}:
        raise LocalAuthError("invalid_role")
    if not 14 <= len(password) <= 1024:
        raise LocalAuthError("invalid_password")
    if not re.fullmatch(r"[A-Z2-7]{16,128}", totp_secret):
        raise LocalAuthError("invalid_totp_secret")
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", item)
               for item in (principal_id, project_id, bot_id)):
        raise LocalAuthError("invalid_identifier")
    current = now or datetime.now(timezone.utc)
    password_hash = PasswordHasher().hash(password)
    encrypted_totp = _fernet(encryption_key).encrypt(totp_secret.encode("ascii"))
    params = _application_connection_parameters(dsn, expected_database)
    params["application_name"] = "radhouse-local-user-provision"
    try:
        with psycopg.connect(**params, row_factory=dict_row) as connection:
            _verified_connection(connection, deployment_id, expected_database)
            connection.execute(
                "INSERT INTO public.bots"
                "(bot_id,display_name,role_name,provider_binding,state) "
                "VALUES (%s,%s,%s,%s,'ready') ON CONFLICT (bot_id) DO NOTHING",
                (bot_id, bot_display_name, bot_role_name, provider_binding),
            )
            bot = connection.execute(
                "SELECT provider_binding FROM public.bots WHERE bot_id=%s", (bot_id,)
            ).fetchone()
            if bot is None or bot["provider_binding"] != provider_binding:
                raise LocalAuthError("bot_binding_mismatch")
            connection.execute(
                "INSERT INTO public.actors(principal_id,role,active) VALUES (%s,%s,true) "
                "ON CONFLICT (principal_id) DO UPDATE SET role=EXCLUDED.role,active=true",
                (principal_id, role),
            )
            connection.execute(
                "INSERT INTO public.projects(project_id,owner_id,display_name,state) "
                "VALUES (%s,%s,%s,'active') ON CONFLICT (project_id) DO NOTHING",
                (project_id, principal_id, project_name),
            )
            owner = connection.execute(
                "SELECT owner_id FROM public.projects WHERE project_id=%s", (project_id,)
            ).fetchone()
            if owner is None or owner["owner_id"] != principal_id:
                raise LocalAuthError("project_owner_mismatch")
            connection.execute(
                "INSERT INTO public.bot_grants(principal_id,bot_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING", (principal_id, bot_id),
            )
            connection.execute(
                "INSERT INTO public.project_members(principal_id,project_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING", (principal_id, project_id),
            )
            conversation_id = f"{project_id}:{principal_id}:radhouse"
            existing = connection.execute(
                "SELECT principal_id,project_id FROM public.channel_bindings "
                "WHERE channel='radhouse' AND subject=%s AND conversation_id=%s",
                (normalized, conversation_id),
            ).fetchone()
            if existing and existing != {"principal_id": principal_id, "project_id": project_id}:
                raise LocalAuthError("binding_conflict")
            connection.execute(
                "INSERT INTO public.channel_bindings"
                "(channel,subject,conversation_id,principal_id,project_id,revision,active) "
                "VALUES ('radhouse',%s,%s,%s,%s,1,true) ON CONFLICT DO NOTHING",
                (normalized, conversation_id, principal_id, project_id),
            )
            connection.execute(
                "INSERT INTO public.local_credentials"
                "(principal_id,username,password_hash,totp_secret_ciphertext,last_totp_counter,updated_at) "
                "VALUES (%s,%s,%s,%s,NULL,%s) "
                "ON CONFLICT (principal_id) DO UPDATE SET username=EXCLUDED.username,"
                "password_hash=EXCLUDED.password_hash,totp_secret_ciphertext=EXCLUDED.totp_secret_ciphertext,"
                "last_totp_counter=NULL,updated_at=EXCLUDED.updated_at",
                (principal_id, normalized, password_hash, encrypted_totp, current),
            )
            connection.execute(
                "UPDATE public.local_sessions SET revoked_at=%s "
                "WHERE principal_id=%s AND revoked_at IS NULL", (current, principal_id),
            )
    except LocalAuthError:
        raise
    except (psycopg.Error, ApplicationStorageError):
        raise LocalAuthError("local_user_provision_failed") from None


class LocalAuthService:
    def __init__(
        self,
        dsn: str,
        *,
        expected_database: str,
        deployment_id: str,
        encryption_key: str,
        expected_origin: str,
        cookie_name: str = "radhouse_session",
        secure_cookie: bool = True,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        idle_ttl: timedelta = timedelta(minutes=30),
        absolute_ttl: timedelta = timedelta(hours=12),
        assurance_ttl: timedelta = timedelta(minutes=10),
    ):
        if not expected_origin.startswith("https://") and expected_origin not in {
            "http://127.0.0.1", "http://localhost"
        }:
            raise LocalAuthError("invalid_expected_origin")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cookie_name):
            raise LocalAuthError("invalid_cookie_name")
        self._params = _application_connection_parameters(dsn, expected_database)
        self._params["application_name"] = "radhouse-local-auth"
        self._database = expected_database
        self._deployment_id = deployment_id
        self._fernet = _fernet(encryption_key)
        self._expected_origin = expected_origin.rstrip("/")
        self.cookie_name = cookie_name
        self.secure_cookie = secure_cookie
        self._clock = clock
        self._idle_ttl = idle_ttl
        self._absolute_ttl = absolute_ttl
        self._assurance_ttl = assurance_ttl
        self._passwords = PasswordHasher()
        self._dummy_hash = self._passwords.hash(secrets.token_urlsafe(32))
        self._throttle_key = hashlib.sha256(encryption_key.encode("ascii") + b"throttle").digest()

    def _keyed_digest(self, value: str) -> str:
        return hmac.new(self._throttle_key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _source(self, request: Request) -> str:
        return request.client.host if request.client is not None else "unknown"

    def verify_origin(self, request: Request) -> None:
        if request.headers.get("origin", "").rstrip("/") != self._expected_origin:
            raise Rejected("request_origin_denied", 403)

    def _connection(self):
        return psycopg.connect(**self._params, row_factory=dict_row)

    def health(self) -> None:
        try:
            with self._connection() as connection:
                _verified_connection(connection, self._deployment_id, self._database)
        except (psycopg.Error, ApplicationStorageError, LocalAuthError):
            raise Rejected("service_unavailable", 503) from None

    def login(self, username: str, password: str, totp_code: str, source: str) -> LocalSession:
        try:
            normalized = _username(username)
        except LocalAuthError:
            normalized = "invalid"
        if len(password) > 1024 or not re.fullmatch(r"[0-9]{6}", totp_code):
            raise Rejected("invalid_credentials", 401)
        now = self._clock()
        username_hash = self._keyed_digest(normalized)
        source_hash = self._keyed_digest(source)
        lock = int.from_bytes(bytes.fromhex(username_hash)[:8], "big", signed=True)
        try:
            with self._connection() as connection:
                _verified_connection(connection, self._deployment_id, self._database)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
                throttle = connection.execute(
                    "SELECT * FROM public.local_login_throttles "
                    "WHERE username_hash=%s AND source_hash=%s FOR UPDATE",
                    (username_hash, source_hash),
                ).fetchone()
                if throttle and throttle["locked_until"] and throttle["locked_until"] > now:
                    raise Rejected("invalid_credentials", 401)
                credential = connection.execute(
                    "SELECT c.*,a.active FROM public.local_credentials c "
                    "JOIN public.actors a USING(principal_id) WHERE c.username=%s",
                    (normalized,),
                ).fetchone()
                encoded = credential["password_hash"] if credential else self._dummy_hash
                password_ok = False
                try:
                    password_ok = self._passwords.verify(encoded, password)
                except (VerifyMismatchError, VerificationError, InvalidHashError):
                    pass
                totp_ok = False
                counter = None
                if credential and credential["active"] and password_ok:
                    try:
                        secret = self._fernet.decrypt(bytes(credential["totp_secret_ciphertext"]))
                        totp = pyotp.TOTP(secret.decode("ascii"))
                        counter = int(now.timestamp()) // totp.interval
                        totp_ok = totp.verify(totp_code, for_time=now, valid_window=1)
                        last = credential["last_totp_counter"]
                        totp_ok = bool(totp_ok and (last is None or counter > last))
                    except (InvalidToken, UnicodeError, ValueError):
                        totp_ok = False
                if not credential or not credential["active"] or not password_ok or not totp_ok:
                    self._record_failure(connection, username_hash, source_hash, throttle, now)
                    # Preserve throttling even though authentication is denied.
                    connection.commit()
                    raise Rejected("invalid_credentials", 401)
                connection.execute(
                    "DELETE FROM public.local_login_throttles WHERE username_hash=%s AND source_hash=%s",
                    (username_hash, source_hash),
                )
                if self._passwords.check_needs_rehash(encoded):
                    connection.execute(
                        "UPDATE public.local_credentials SET password_hash=%s,updated_at=%s "
                        "WHERE principal_id=%s", (self._passwords.hash(password), now, credential["principal_id"]),
                    )
                connection.execute(
                    "UPDATE public.local_credentials SET last_totp_counter=%s WHERE principal_id=%s",
                    (counter, credential["principal_id"]),
                )
                token = secrets.token_urlsafe(32)
                csrf = secrets.token_urlsafe(32)
                assurance_until = now + self._assurance_ttl
                connection.execute(
                    "INSERT INTO public.local_sessions"
                    "(token_hash,principal_id,csrf_hash,created_at,last_seen_at,idle_expires_at,"
                    "absolute_expires_at,assurance_until) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (_digest(token), credential["principal_id"], _digest(csrf), now, now,
                     now + self._idle_ttl, now + self._absolute_ttl, assurance_until),
                )
                binding = self._binding(connection, credential["principal_id"], normalized)
                return LocalSession(token, csrf, credential["principal_id"], normalized,
                                    assurance_until, **binding)
        except Rejected:
            raise
        except (psycopg.Error, ApplicationStorageError):
            raise Rejected("authentication_unavailable", 503) from None

    def _record_failure(self, connection, username_hash, source_hash, row, now) -> None:
        window = timedelta(minutes=15)
        failures = 1
        started = now
        if row and row["window_started_at"] + window > now:
            failures = row["failures"] + 1
            started = row["window_started_at"]
        locked = now + timedelta(minutes=5) if failures >= 5 else None
        connection.execute(
            "INSERT INTO public.local_login_throttles"
            "(username_hash,source_hash,window_started_at,failures,locked_until) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (username_hash,source_hash) DO UPDATE SET "
            "window_started_at=EXCLUDED.window_started_at,failures=EXCLUDED.failures,"
            "locked_until=EXCLUDED.locked_until",
            (username_hash, source_hash, started, failures, locked),
        )

    def _binding(self, connection, principal_id: str, username: str) -> dict:
        binding = connection.execute(
            "SELECT conversation_id,revision AS binding_revision,project_id "
            "FROM public.channel_bindings WHERE channel='radhouse' AND subject=%s "
            "AND principal_id=%s AND active ORDER BY conversation_id LIMIT 1",
            (username, principal_id),
        ).fetchone()
        if binding is None:
            raise Rejected("work_home_unavailable", 403)
        return dict(binding)

    def session(self, request: Request) -> LocalSession:
        token = request.cookies.get(self.cookie_name, "")
        if not token or len(token) > 128:
            raise Rejected("authentication_required", 401)
        now = self._clock()
        try:
            with self._connection() as connection:
                _verified_connection(connection, self._deployment_id, self._database)
                row = connection.execute(
                    "SELECT s.*,c.username,a.active FROM public.local_sessions s "
                    "JOIN public.local_credentials c USING(principal_id) "
                    "JOIN public.actors a USING(principal_id) WHERE s.token_hash=%s FOR UPDATE",
                    (_digest(token),),
                ).fetchone()
                if (
                    row is None or not row["active"] or row["revoked_at"] is not None
                    or row["idle_expires_at"] <= now or row["absolute_expires_at"] <= now
                ):
                    raise Rejected("authentication_required", 401)
                if request.method in _UNSAFE_METHODS:
                    if request.headers.get("origin", "").rstrip("/") != self._expected_origin:
                        raise Rejected("request_origin_denied", 403)
                    supplied = request.headers.get("x-radhouse-csrf", "")
                    if not supplied or not hmac.compare_digest(_digest(supplied), row["csrf_hash"]):
                        raise Rejected("csrf_denied", 403)
                idle_expires = min(now + self._idle_ttl, row["absolute_expires_at"])
                connection.execute(
                    "UPDATE public.local_sessions SET last_seen_at=%s,idle_expires_at=%s "
                    "WHERE token_hash=%s", (now, idle_expires, row["token_hash"]),
                )
                binding = self._binding(connection, row["principal_id"], row["username"])
                csrf = request.headers.get("x-radhouse-csrf", "")
                return LocalSession(token, csrf, row["principal_id"], row["username"],
                                    row["assurance_until"], **binding)
        except Rejected:
            raise
        except (psycopg.Error, ApplicationStorageError):
            raise Rejected("authentication_unavailable", 503) from None

    def refresh(self, request: Request) -> LocalSession:
        session = self.session(request)
        csrf = secrets.token_urlsafe(32)
        try:
            with self._connection() as connection:
                _verified_connection(connection, self._deployment_id, self._database)
                cursor = connection.execute(
                    "UPDATE public.local_sessions SET csrf_hash=%s WHERE token_hash=%s "
                    "AND revoked_at IS NULL", (_digest(csrf), _digest(session.token)),
                )
                if cursor.rowcount != 1:
                    raise Rejected("authentication_required", 401)
        except Rejected:
            raise
        except (psycopg.Error, ApplicationStorageError):
            raise Rejected("authentication_unavailable", 503) from None
        return replace(session, csrf_token=csrf)

    def auth_context(self, request: Request) -> AuthContext:
        session = self.session(request)
        return AuthContext(session.principal_id, "radhouse", session.username,
                           session.assurance_until)

    def revoke(self, request: Request) -> None:
        session = self.session(request)
        now = self._clock()
        try:
            with self._connection() as connection:
                _verified_connection(connection, self._deployment_id, self._database)
                connection.execute(
                    "UPDATE public.local_sessions SET revoked_at=%s WHERE token_hash=%s",
                    (now, _digest(session.token)),
                )
        except (psycopg.Error, ApplicationStorageError):
            raise Rejected("authentication_unavailable", 503) from None
