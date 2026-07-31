from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chimebuddy.config import (
    ConfigurationError,
    load_settings,
)


BACKUP_PREFIX = "chimebuddy-"
BACKUP_SUFFIX = ".db"
DEFAULT_RETAINED_BACKUPS = 14


class DatabaseBackupError(RuntimeError):
    """Raised when a verified SQLite backup cannot be made."""


@dataclass(frozen=True, slots=True)
class DatabaseBackupResult:
    backup_path: Path
    removed_backup_count: int


def create_database_backup(
    database_path: str | Path,
    backup_directory: str | Path,
    *,
    retained_backup_count: int = (
        DEFAULT_RETAINED_BACKUPS
    ),
    created_at: datetime | None = None,
) -> DatabaseBackupResult:
    """
    Create and verify an online SQLite backup.

    SQLite's backup API produces a consistent snapshot
    even while the Twitch and Discord processes are
    reading and writing the source database.
    """

    source_path = Path(database_path).expanduser().resolve()
    destination_directory = (
        Path(backup_directory).expanduser().resolve()
    )

    if retained_backup_count <= 0:
        raise ValueError(
            "retained_backup_count must be positive."
        )

    if not source_path.is_file():
        raise DatabaseBackupError(
            f"Database does not exist: {source_path}"
        )

    destination_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        created_at
        if created_at is not None
        else datetime.now(UTC)
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    timestamp = timestamp.astimezone(UTC)
    filename = (
        BACKUP_PREFIX
        + f"{timestamp:%Y%m%dT%H%M%S%fZ}"
        + BACKUP_SUFFIX
    )
    backup_path = destination_directory / filename
    temporary_path = backup_path.with_suffix(
        f"{BACKUP_SUFFIX}.tmp"
    )

    if backup_path.exists() or temporary_path.exists():
        raise DatabaseBackupError(
            "The generated backup path already exists."
        )

    try:
        with closing(
            sqlite3.connect(
                source_path,
                timeout=30,
            )
        ) as source_connection:
            with closing(
                sqlite3.connect(
                    temporary_path,
                    timeout=30,
                )
            ) as backup_connection:
                source_connection.backup(
                    backup_connection,
                    pages=1000,
                    sleep=0.05,
                )

                integrity_rows = (
                    backup_connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchall()
                )

                if integrity_rows != [("ok",)]:
                    raise DatabaseBackupError(
                        "SQLite integrity verification "
                        "failed for the new backup."
                    )

        os.replace(temporary_path, backup_path)

        try:
            backup_path.chmod(0o600)
        except OSError:
            # Some filesystems do not expose POSIX modes.
            pass

    except DatabaseBackupError:
        temporary_path.unlink(missing_ok=True)
        raise
    except (OSError, sqlite3.Error) as exc:
        temporary_path.unlink(missing_ok=True)
        raise DatabaseBackupError(
            "SQLite backup creation failed."
        ) from exc

    removed_count = _prune_old_backups(
        destination_directory,
        retained_backup_count,
    )

    return DatabaseBackupResult(
        backup_path=backup_path,
        removed_backup_count=removed_count,
    )


def _prune_old_backups(
    backup_directory: Path,
    retained_backup_count: int,
) -> int:
    backup_paths = sorted(
        (
            path
            for path in backup_directory.glob(
                f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"
            )
            if path.is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )

    removed_count = 0

    for expired_path in backup_paths[
        retained_backup_count:
    ]:
        expired_path.unlink()
        removed_count += 1

    return removed_count


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a verified online backup of the "
            "ChimeBuddy SQLite database."
        )
    )
    parser.add_argument(
        "--destination",
        type=Path,
        help=(
            "Backup directory. Defaults to a backups "
            "directory beside the configured database."
        ),
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_RETAINED_BACKUPS,
        help=(
            "Number of newest ChimeBuddy backups to keep "
            f"(default: {DEFAULT_RETAINED_BACKUPS})."
        ),
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    arguments = parser.parse_args()

    try:
        settings = load_settings()
        destination = (
            arguments.destination
            if arguments.destination is not None
            else settings.database_path.parent / "backups"
        )
        result = create_database_backup(
            settings.database_path,
            destination,
            retained_backup_count=arguments.keep,
        )
    except (
        ConfigurationError,
        DatabaseBackupError,
        ValueError,
    ) as exc:
        raise SystemExit(
            f"Database backup error: {exc}"
        ) from exc

    print(f"Backup created: {result.backup_path}")
    print("SQLite integrity check: ok")
    print(
        "Expired backups removed: "
        f"{result.removed_backup_count}"
    )


if __name__ == "__main__":
    main()
