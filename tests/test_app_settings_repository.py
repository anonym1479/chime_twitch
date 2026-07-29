import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.repositories import (
    AppSettingsRepository,
)


class AppSettingsRepositoryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.addCleanup(
            self.temp_directory.cleanup
        )

        database_path = (
            Path(self.temp_directory.name)
            / "test.db"
        )

        self.database = Database(database_path)
        await self.database.initialize()

        self.repository = AppSettingsRepository(
            self.database
        )

    async def test_set_and_get_setting(
        self,
    ) -> None:
        await self.repository.set(
            "discord.review_channel_id",
            "123456789",
        )

        value = await self.repository.get(
            "discord.review_channel_id"
        )

        self.assertEqual(value, "123456789")

    async def test_setting_can_be_updated(
        self,
    ) -> None:
        await self.repository.set(
            "discord.review_channel_id",
            "100",
        )

        await self.repository.set(
            "discord.review_channel_id",
            "200",
        )

        value = await self.repository.get_positive_int(
            "discord.review_channel_id"
        )

        self.assertEqual(value, 200)

    async def test_delete_is_idempotent(
        self,
    ) -> None:
        await self.repository.set(
            "test.setting",
            "test-value",
        )

        first_result = await self.repository.delete(
            "test.setting"
        )
        second_result = await self.repository.delete(
            "test.setting"
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)

    async def test_rejects_empty_key(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "key cannot be empty",
        ):
            await self.repository.get("")


if __name__ == "__main__":
    unittest.main()