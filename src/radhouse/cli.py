"""Bounded operator commands; credentials are accepted only by file reference."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

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
        MigrationError,
        SecretFileError,
    ) as error:
        print(json.dumps({"result": "refused", "code": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
