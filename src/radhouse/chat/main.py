"""Explicit factory. Reads private configuration; never provisions or migrates PostgreSQL."""
import json
import os
import importlib.util
from pathlib import Path
from contextlib import asynccontextmanager

from radhouse.auth.local import LocalAuthService
from radhouse.integrations.hermes import HermesRunsClient
from .app import create_app
from .service import ChatService
from .store import ChatStore
from .transcription import Transcriber
from .admin import AdminService, AssistantSignal, DocumentSignal, EffectiveSettings


def app_factory():
    path = Path(os.environ["RADHOUSE_CHAT_CONFIG"])
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("chat_config_requires_private_file")
    config = json.loads(path.read_text())
    required = {"auth_dsn", "auth_database", "deployment_id", "auth_encryption_key",
                "origin", "owner_id", "hermes_endpoint", "hermes_bearer", "transcript_path"}
    optional = {"transcription_endpoint", "transcription_bearer"}
    if not required <= set(config) or set(config) - required - optional or ("transcription_bearer" in config and "transcription_endpoint" not in config):
        raise ValueError("invalid_chat_config")
    auth = LocalAuthService(config["auth_dsn"], expected_database=config["auth_database"],
        deployment_id=config["deployment_id"], encryption_key=config["auth_encryption_key"],
        expected_origin=config["origin"])
    auth.health()  # Exact existing database/deployment/schema digest; no migration.
    hermes = HermesRunsClient(config["hermes_endpoint"], config["hermes_bearer"])
    status_client = HermesRunsClient(config["hermes_endpoint"], config["hermes_bearer"],
        connect_timeout=1, read_timeout=2, request_deadline=3)
    transcriber = Transcriber(config["transcription_endpoint"], bearer=config.get("transcription_bearer")) if "transcription_endpoint" in config else None
    store = ChatStore(Path(config["transcript_path"]))

    def assistant_status():
        capabilities = status_client.capabilities()
        return AssistantSignal(ready=capabilities.disable_tools
            and capabilities.idempotency_retention_seconds > 60)

    def document_status():
        available = (importlib.util.find_spec("radhouse.chat.document_parser") is not None
            and importlib.util.find_spec("pypdf") is not None)
        return DocumentSignal(available=available, connected=False)

    # Source deployments without a release receipt report an unknown revision.
    # Never infer a live revision from an archived repository checkout.
    admin = AdminService(store, settings=EffectiveSettings(**auth.session_limits(),
            transcription_enabled=transcriber is not None),
        assistant_probe=assistant_status,
        document_probe=document_status, release_commit=os.environ.get("RADHOUSE_RELEASE_COMMIT"))
    app = create_app(auth, ChatService(store, hermes, owner_id=config["owner_id"], transcriber=transcriber), admin=admin)

    observe_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        try:
            async with observe_lifespan(_app):
                yield
        finally:
            hermes.close()
            status_client.close()
            if transcriber: transcriber.close()
    app.router.lifespan_context = lifespan
    return app
