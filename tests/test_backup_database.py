import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.tools.backup_database import (
    DatabaseBackupError,
    create_database_backup,
)


class DatabaseBackupTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        self.root = Path(self.temp_directory.name)
        self.database_path = self.root / "live.db"
        self.backup_directory = self.root / "backups"
        self.database = Database(self.database_path)
        await self.database.initialize()

    async def test_creates_verified_database_copy(
        self,
    ) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES ('backup-test', 'preserved')
                """
            )
            await connection.commit()

            # Keep an application connection open to
            # exercise SQLite's online backup behavior.
            result = create_database_backup(
                self.database_path,
                self.backup_directory,
                created_at=datetime(
                    2026,
                    7,
                    31,
                    8,
                    30,
                    tzinfo=UTC,
                ),
            )

        self.assertTrue(result.backup_path.is_file())
        self.assertEqual(
            result.backup_path.name,
            "chimebuddy-20260731T083000000000Z.db",
        )

        with closing(
            sqlite3.connect(result.backup_path)
        ) as connection:
            stored_value = connection.execute(
                """
                SELECT value
                FROM app_settings
                WHERE key = 'backup-test'
                """
            ).fetchone()
            integrity = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

        self.assertEqual(stored_value, ("preserved",))
        self.assertEqual(integrity, ("ok",))

    async def test_retention_only_removes_old_backups(
        self,
    ) -> None:
        unrelated_file = (
            self.backup_directory / "personal.db"
        )
        self.backup_directory.mkdir()
        unrelated_file.write_text(
            "do not remove",
            encoding="utf-8",
        )
        start = datetime(
            2026,
            7,
            31,
            tzinfo=UTC,
        )

        results = [
            create_database_backup(
                self.database_path,
                self.backup_directory,
                retained_backup_count=2,
                created_at=start + timedelta(minutes=index),
            )
            for index in range(3)
        ]

        retained_names = {
            path.name
            for path in self.backup_directory.glob(
                "chimebuddy-*.db"
            )
        }

        self.assertFalse(results[0].backup_path.exists())
        self.assertTrue(results[1].backup_path.exists())
        self.assertTrue(results[2].backup_path.exists())
        self.assertEqual(len(retained_names), 2)
        self.assertTrue(unrelated_file.exists())

    async def test_missing_database_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(DatabaseBackupError):
            create_database_backup(
                self.root / "missing.db",
                self.backup_directory,
            )


if __name__ == "__main__":
    unittest.main()
