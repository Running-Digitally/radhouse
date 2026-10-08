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
from .document_bridge import DocumentBridge
from .browser import BrowserService, HermesBrowserClient


def app_factory():
    config = _load_chat_config()
    document_access = config.get("document_access_enabled", False)
    browser_enabled = config.get("browser_enabled", False)
    auth = LocalAuthService(config["auth_dsn"], expected_database=config["auth_database"],
        deployment_id=config["deployment_id"], encryption_key=config["auth_encryption_key"],
        expected_origin=config["origin"])
    auth.health()  # Exact existing database/deployment/schema digest; no migration.
    hermes = HermesRunsClient(config["hermes_endpoint"], config["hermes_bearer"])
    status_client = HermesRunsClient(config["hermes_endpoint"], config["hermes_bearer"],
        connect_timeout=1, read_timeout=2, request_deadline=3)
    transcriber = Transcriber(config["transcription_endpoint"], bearer=config.get("transcription_bearer")) if "transcription_endpoint" in config else None
    store = ChatStore(Path(config["transcript_path"]))
    browser_client = HermesBrowserClient(config["hermes_endpoint"], config["hermes_bearer"]) if browser_enabled else None

    assistant_status = lambda: _assistant_status(status_client, document_access, browser_enabled)
    def document_status():
        available = (importlib.util.find_spec("radhouse.chat.document_parser") is not None
            and importlib.util.find_spec("pypdf") is not None)
        return DocumentSignal(available=available, connected=document_access and status_client.capabilities().document_scope)

    # Source deployments without a release receipt report an unknown revision.
    # Never infer a live revision from an archived repository checkout.
    admin = AdminService(store, settings=EffectiveSettings(**auth.session_limits(),
            transcription_enabled=transcriber is not None, document_access_enabled=document_access,
            browser_enabled=browser_enabled),
        assistant_probe=assistant_status,
        document_probe=document_status,
        network_policy_probe=(lambda: status_client.capabilities().browser_network_policy) if browser_enabled else None,
        release_commit=os.environ.get("RADHOUSE_RELEASE_COMMIT"))
    service = ChatService(store, hermes, owner_id=config["owner_id"], transcriber=transcriber,
        document_access=document_access, browser_enabled=browser_enabled)
    app = create_app(auth, service, admin=admin,
        documents=DocumentBridge(store, status_client, owner_id=config["owner_id"]) if document_access else None,
        browser=BrowserService(store, browser_client, owner_id=config["owner_id"]) if browser_enabled else None)

    observe_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        try:
            async with observe_lifespan(_app):
                yield
        finally:
            hermes.close()
            status_client.close()
            if browser_client: browser_client.close()
            if transcriber: transcriber.close()
    app.router.lifespan_context = lifespan
    return app

def _load_chat_config():
    path = Path(os.environ["RADHOUSE_CHAT_CONFIG"])
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("chat_config_requires_private_file")
    config = json.loads(path.read_text())
    required = {"auth_dsn", "auth_database", "deployment_id", "auth_encryption_key",
                "origin", "owner_id", "hermes_endpoint", "hermes_bearer", "transcript_path"}
    optional = {"transcription_endpoint", "transcription_bearer", "document_access_enabled", "browser_enabled"}
    if not required <= set(config) or set(config) - required - optional or ("transcription_bearer" in config and "transcription_endpoint" not in config):
        raise ValueError("invalid_chat_config")
    if any(type(config.get(key, False)) is not bool for key in ("document_access_enabled", "browser_enabled")):
        raise ValueError("invalid_chat_config")
    return config


def _assistant_status(status_client, document_access, browser_enabled):
    capabilities = status_client.capabilities()
    return AssistantSignal(ready=capabilities.disable_tools
        and capabilities.idempotency_retention_seconds > 60
        and (not document_access or capabilities.allowed_tools and capabilities.document_scope)
        and (not browser_enabled or capabilities.allowed_tools and capabilities.browser_view))


