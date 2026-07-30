import tempfile
import unittest
from pathlib import Path

import aiosqlite

from chimebuddy.database import Database


EXPECTED_TABLES = {
    "schema_migrations",
    "app_settings",
    "twitch_accounts",
    "discord_accounts",
    "account_links",
    "broadcasters",
    "triggers",
    "trigger_runtime_state",
    "oauth_credentials",
    "account_link_sessions",
    "broadcaster_requests",
    "broadcaster_panels",
    "broadcaster_blacklist",
    "onboarding_request_events",
    "runtime_health",
    "runtime_error_events",
}


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
        self.assertEqual(applied_versions, [1, 2, 3, 4, 5, 6])

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

        for expected_table in EXPECTED_TABLES:
            self.assertIn(expected_table, table_names)

    async def test_migrations_are_not_repeated(self) -> None:
        first_result = await self.database.initialize()
        second_result = await self.database.initialize()

        self.assertEqual(first_result, [1, 2, 3, 4, 5, 6])
        self.assertEqual(second_result, [])

    async def test_identity_and_broadcaster_relationships(self) -> None:
        await self.database.initialize()

        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO twitch_accounts (
                    twitch_user_id,
                    login,
                    display_name
                )
                VALUES (?, ?, ?)
                """,
                (
                    "211164044",
                    "example_streamer",
                    "Example_Streamer",
                ),
            )

            await connection.execute(
                """
                INSERT INTO discord_accounts (
                    discord_user_id,
                    username,
                    display_name
                )
                VALUES (?, ?, ?)
                """,
                (
                    "123456789012345678",
                    "example_discord_user",
                    "Example Discord User",
                ),
            )

            await connection.execute(
                """
                INSERT INTO account_links (
                    twitch_user_id,
                    discord_user_id,
                    status,
                    verification_method,
                    verified_at
                )
                VALUES (?, ?, 'verified', ?, CURRENT_TIMESTAMP)
                """,
                (
                    "211164044",
                    "123456789012345678",
                    "test",
                ),
            )

            await connection.execute(
                """
                INSERT INTO broadcasters (
                    twitch_user_id,
                    owner_discord_user_id
                )
                VALUES (?, ?)
                """,
                (
                    "211164044",
                    "123456789012345678",
                ),
            )

            await connection.commit()

            cursor = await connection.execute(
                """
                SELECT
                    broadcasters.twitch_user_id,
                    broadcasters.owner_discord_user_id,
                    twitch_accounts.login,
                    account_links.status
                FROM broadcasters
                JOIN twitch_accounts
                    ON twitch_accounts.twitch_user_id =
                       broadcasters.twitch_user_id
                JOIN account_links
                    ON account_links.twitch_user_id =
                       broadcasters.twitch_user_id
                """
            )

            row = await cursor.fetchone()
            await cursor.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["twitch_user_id"], "211164044")
        self.assertEqual(
            row["owner_discord_user_id"],
            "123456789012345678",
        )
        self.assertEqual(row["login"], "example_streamer")
        self.assertEqual(row["status"], "verified")

    async def test_unknown_accounts_cannot_be_broadcasters(self) -> None:
        await self.database.initialize()

        async with self.database.connect() as connection:
            with self.assertRaises(aiosqlite.IntegrityError):
                await connection.execute(
                    """
                    INSERT INTO broadcasters (
                        twitch_user_id,
                        owner_discord_user_id
                    )
                    VALUES (?, ?)
                    """,
                    (
                        "unknown-twitch-id",
                        "unknown-discord-id",
                    ),
                )

    async def test_discord_account_cannot_link_twice(
        self,
    ) -> None:
        await self.database.initialize()

        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO discord_accounts (
                    discord_user_id,
                    username,
                    display_name
                )
                VALUES (?, ?, ?)
                """,
                (
                    "123456789",
                    "example_user",
                    "Example User",
                ),
            )

            await connection.executemany(
                """
                INSERT INTO twitch_accounts (
                    twitch_user_id,
                    login,
                    display_name
                )
                VALUES (?, ?, ?)
                """,
                [
                    (
                        "100",
                        "streamer_one",
                        "Streamer One",
                    ),
                    (
                        "200",
                        "streamer_two",
                        "Streamer Two",
                    ),
                ],
            )

            await connection.execute(
                """
                INSERT INTO account_links (
                    twitch_user_id,
                    discord_user_id,
                    status
                )
                VALUES (?, ?, 'verified')
                """,
                (
                    "100",
                    "123456789",
                ),
            )

            await connection.commit()

            with self.assertRaises(
                aiosqlite.IntegrityError
            ):
                await connection.execute(
                    """
                    INSERT INTO account_links (
                        twitch_user_id,
                        discord_user_id,
                        status
                    )
                    VALUES (?, ?, 'verified')
                    """,
                    (
                        "200",
                        "123456789",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
