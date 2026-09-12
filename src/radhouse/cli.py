"""Bounded operator commands; credentials are accepted only by file reference."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

import uvicorn

from radhouse.api.app import create_app
from radhouse.auth.local import LocalAuthError, LocalAuthService, provision_local_user
from radhouse.composition import compose_controller
from radhouse.config import ConfigurationError, load_config
from radhouse.secrets import SecretFileError, read_secret_file
from radhouse.storage.migrations import MigrationError, initialize_database
from radhouse.storage.postgres import ApplicationStorageError


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="radhouse")
    commands = result.add_subparsers(dest="command", required=True)
    check = commands.add_parser("config-check", help="validate configuration without reading secrets")
    check.add_argument("--config", required=True)
    check.add_argument("--overlay")
    preflight = commands.add_parser(
        "preflight", help="validate protected deployment composition without network access",
    )
    preflight.add_argument("--config", required=True)
    preflight.add_argument("--overlay")
    migrate = commands.add_parser("migrate", help="initialize or verify the configured control database")
    migrate.add_argument("--config", required=True)
    migrate.add_argument("--overlay")
    migrate.add_argument("--owner-dsn-file", required=True)
    migrate.add_argument("--runtime-role", required=True)
    migrate.add_argument("--apply", action="store_true")
    user = commands.add_parser("local-user", help="provision one explicit local user and work home")
    user.add_argument("--config", required=True)
    user.add_argument("--overlay")
    user.add_argument("--principal-id", required=True)
    user.add_argument("--username", required=True)
    user.add_argument("--role", choices=("admin", "operator", "viewer"), required=True)
    user.add_argument("--password-file", required=True)
    user.add_argument("--totp-secret-file", required=True)
    user.add_argument("--project-id", required=True)
    user.add_argument("--project-name", required=True)
    user.add_argument("--bot-id", required=True)
    user.add_argument("--bot-display-name", required=True)
    user.add_argument("--bot-role-name", required=True)
    user.add_argument("--apply", action="store_true")
    serve = commands.add_parser("serve", help="serve the authenticated operator interface")
    serve.add_argument("--config", required=True)
    serve.add_argument("--overlay")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8088)
    serve.add_argument("--ssl-certfile")
    serve.add_argument("--ssl-keyfile")
    cycle = commands.add_parser("coordinator-once", help="run one bounded coordinator cycle")
    cycle.add_argument("--config", required=True)
    cycle.add_argument("--overlay")
    return result


def _summary(config) -> dict:
    return {
        "result": "valid",
        "schema_version": config.schema_version,
        "deployment_id": config.database.deployment_id,
        "database": config.database.name,
        "provider_count": len(config.providers),
        "bot_count": len(config.bots),
    }


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        config = load_config(args.config, getattr(args, "overlay", None))
        if args.command == "config-check":
            output = _summary(config)
        elif args.command == "preflight":
            with compose_controller(config):
                pass
            output = {**_summary(config), "result": "offline_ready"}
        elif args.command == "serve":
            if config.authentication is None:
                raise LocalAuthError("authentication_not_configured")
            if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
                raise LocalAuthError("incomplete_tls_configuration")
            with compose_controller(config) as controller:
                auth = LocalAuthService(
                    read_secret_file(config.database.dsn.path),
                    expected_database=config.database.name,
                    deployment_id=config.database.deployment_id,
                    encryption_key=read_secret_file(config.authentication.encryption_key.path),
                    expected_origin=config.authentication.expected_origin,
                    cookie_name=config.authentication.cookie_name,
                    secure_cookie=config.authentication.secure_cookie,
                )
                app = create_app(
                    controller.service, auth.auth_context,
                    web_root=controller.web_root, local_auth=auth,
                )
                uvicorn.run(
                    app, host=args.host, port=args.port, proxy_headers=True,
                    forwarded_allow_ips="127.0.0.1", access_log=False,
                    ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile,
                )
            return 0
        elif args.command == "coordinator-once":
            with compose_controller(config) as controller:
                cycle = controller.coordinator.run_once()
            output = {
                "result": "complete", "worker_id": cycle.worker_id,
                "task_count": len(cycle.receipts),
                "errors": sum(receipt.error_code is not None for receipt in cycle.receipts),
            }
        elif args.command == "local-user":
            if not args.apply:
                output = {**_summary(config), "result": "apply_required"}
            elif config.authentication is None:
                raise LocalAuthError("authentication_not_configured")
            else:
                bot = next((item for item in config.bots if item.bot_id == args.bot_id), None)
                if bot is None:
                    raise LocalAuthError("bot_not_configured")
                provision_local_user(
                    read_secret_file(config.database.dsn.path),
                    expected_database=config.database.name,
                    deployment_id=config.database.deployment_id,
                    encryption_key=read_secret_file(config.authentication.encryption_key.path),
                    principal_id=args.principal_id,
                    username=args.username,
                    role=args.role,
                    password=read_secret_file(args.password_file),
                    totp_secret=read_secret_file(args.totp_secret_file),
                    project_id=args.project_id,
                    project_name=args.project_name,
                    bot_id=args.bot_id,
                    bot_display_name=args.bot_display_name,
                    bot_role_name=args.bot_role_name,
                    provider_binding=bot.provider_binding,
                )
                output = {
                    "result": "provisioned", "principal_id": args.principal_id,
                    "username": args.username.lower(), "role": args.role,
                    "project_id": args.project_id, "bot_id": args.bot_id,
                }
        elif not args.apply:
            output = {**_summary(config), "result": "apply_required"}
        else:
            owner_dsn = read_secret_file(args.owner_dsn_file)
            receipt = initialize_database(
                owner_dsn,
                expected_database=config.database.name,
                deployment_id=config.database.deployment_id,
                runtime_role=args.runtime_role,
            )
            output = asdict(receipt)
    except (
        ApplicationStorageError,
        ConfigurationError,
        LocalAuthError,
        MigrationError,
        SecretFileError,
    ) as error:
        print(json.dumps({"result": "refused", "code": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
