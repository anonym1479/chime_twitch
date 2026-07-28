import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        self.database_path = (
            Path(self.temp_directory.name)
            / "nested"
            / "test.db"
        )

        self.database = Database(self.database_path)

    async def test_initialize_creates_database(self) -> None:
        applied_versions = await self.database.initialize()

        self.assertTrue(self.database_path.exists())
        self.assertEqual(applied_versions, [1])

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            )

            rows = await cursor.fetchall()
            await cursor.close()

        table_names = {row["name"] for row in rows}

        self.assertIn("schema_migrations", table_names)
        self.assertIn("app_settings", table_names)

    async def test_migrations_are_not_repeated(self) -> None:
        first_result = await self.database.initialize()
        second_result = await self.database.initialize()

        self.assertEqual(first_result, [1])
        self.assertEqual(second_result, [])


if __name__ == "__main__":
    unittest.main()