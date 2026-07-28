from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from chimebuddy.database.migrations import MIGRATIONS, Migration


class Database:
    """Creates SQLite connections and applies database migrations."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(
            self.path,
            timeout=5,
        )

        connection.row_factory = aiosqlite.Row

        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA busy_timeout = 5000")

        try:
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> list[int]:
        """Create the database and apply missing migrations."""

        self.path.parent.mkdir(parents=True, exist_ok=True)

        applied_versions: list[int] = []

        async with self.connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")

            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await connection.commit()

            for migration in MIGRATIONS:
                if await self._is_applied(connection, migration.version):
                    continue

                await connection.execute("BEGIN IMMEDIATE")

                try:
                    # Check again after obtaining the write lock. This protects
                    # us when Twitch and Discord start at the same time.
                    if await self._is_applied(
                        connection,
                        migration.version,
                    ):
                        await connection.rollback()
                        continue

                    await self._apply_migration(
                        connection,
                        migration,
                    )

                    await connection.execute(
                        """
                        INSERT INTO schema_migrations (version, name)
                        VALUES (?, ?)
                        """,
                        (migration.version, migration.name),
                    )

                    await connection.commit()
                    applied_versions.append(migration.version)

                except Exception:
                    await connection.rollback()
                    raise

        return applied_versions

    @staticmethod
    async def _is_applied(
        connection: aiosqlite.Connection,
        version: int,
    ) -> bool:
        cursor = await connection.execute(
            """
            SELECT 1
            FROM schema_migrations
            WHERE version = ?
            """,
            (version,),
        )

        row = await cursor.fetchone()
        await cursor.close()

        return row is not None

    @staticmethod
    async def _apply_migration(
        connection: aiosqlite.Connection,
        migration: Migration,
    ) -> None:
        for statement in migration.statements:
            await connection.execute(statement)