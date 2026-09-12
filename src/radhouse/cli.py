"""Bounded operator commands; credentials are accepted only by file reference."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import sys

from radhouse.config import ConfigurationError, load_config
from radhouse.storage.migrations import MigrationError, initialize_database


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


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="radhouse")
    commands = result.add_subparsers(dest="command", required=True)
    check = commands.add_parser("config-check", help="validate configuration without reading secrets")
    check.add_argument("--config", required=True)
    check.add_argument("--overlay")
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
        "bot_count": len(config.bots),
    }


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        config = load_config(args.config, getattr(args, "overlay", None))
        if args.command == "config-check":
            output = _summary(config)
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
    except (ConfigurationError, MigrationError, SecretFileError) as error:
        print(json.dumps({"result": "refused", "code": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
