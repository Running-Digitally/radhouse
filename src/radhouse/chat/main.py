"""Explicit factory. Reads private configuration; never provisions or migrates PostgreSQL."""
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

from radhouse.auth.local import LocalAuthService
from radhouse.integrations.hermes import HermesRunsClient
from .app import create_app
from .service import ChatService
from .store import ChatStore
from .transcription import Transcriber


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
    transcriber = Transcriber(config["transcription_endpoint"], bearer=config.get("transcription_bearer")) if "transcription_endpoint" in config else None
    store = ChatStore(Path(config["transcript_path"]))
    app = create_app(auth, ChatService(store, hermes, owner_id=config["owner_id"], transcriber=transcriber))

    observe_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        try:
            async with observe_lifespan(_app):
                yield
        finally:
            hermes.close()
            if transcriber: transcriber.close()
    app.router.lifespan_context = lifespan
    return app
