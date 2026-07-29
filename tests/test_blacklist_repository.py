import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    BroadcasterBlacklistEntry,
)
from chimebuddy.repositories import (
    ActiveBlacklistEntryError,
    BroadcasterBlacklistRepository,
)


class BroadcasterBlacklistRepositoryTests(
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

        self.repository = (
            BroadcasterBlacklistRepository(
                self.database
            )
        )

    def make_entry(
        self,
    ) -> BroadcasterBlacklistEntry:
        return BroadcasterBlacklistEntry(
            discord_user_id="123",
            twitch_user_id="456",
            internal_reason="Test blacklist reason.",
            requester_message="Original request.",
            created_by_discord_user_id="999",
        )

    async def test_create_and_load_entry(
        self,
    ) -> None:
        created = await self.repository.create(
            self.make_entry()
        )

        loaded = await self.repository.get(
            created.blacklist_id
        )

        self.assertIsNotNone(created.blacklist_id)
        self.assertEqual(
            loaded.discord_user_id,
            "123",
        )
        self.assertEqual(
            loaded.twitch_user_id,
            "456",
        )
        self.assertTrue(loaded.active)

    async def test_find_active_by_either_identity(
        self,
    ) -> None:
        created = await self.repository.create(
            self.make_entry()
        )

        by_discord = (
            await self.repository.find_active(
                discord_user_id="123"
            )
        )
        by_twitch = (
            await self.repository.find_active(
                twitch_user_id="456"
            )
        )

        self.assertEqual(
            by_discord.blacklist_id,
            created.blacklist_id,
        )
        self.assertEqual(
            by_twitch.blacklist_id,
            created.blacklist_id,
        )

    async def test_rejects_duplicate_active_entry(
        self,
    ) -> None:
        await self.repository.create(
            self.make_entry()
        )

        with self.assertRaises(
            ActiveBlacklistEntryError
        ):
            await self.repository.create(
                self.make_entry()
            )

    async def test_revoke_is_idempotent(
        self,
    ) -> None:
        created = await self.repository.create(
            self.make_entry()
        )

        first_result = await self.repository.revoke(
            created.blacklist_id,
            revoked_by_discord_user_id="999",
            reason="Blacklist removed after review.",
        )

        second_result = await self.repository.revoke(
            created.blacklist_id,
            revoked_by_discord_user_id="999",
            reason="Repeated click.",
        )

        loaded = await self.repository.get(
            created.blacklist_id
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertFalse(loaded.active)
        self.assertEqual(
            loaded.revocation_reason,
            "Blacklist removed after review.",
        )
        self.assertIsNotNone(loaded.revoked_at)

    async def test_revoked_identity_can_be_added_again(
        self,
    ) -> None:
        first = await self.repository.create(
            self.make_entry()
        )

        await self.repository.revoke(
            first.blacklist_id,
            revoked_by_discord_user_id="999",
            reason="Temporary removal.",
        )

        second = await self.repository.create(
            self.make_entry()
        )

        self.assertNotEqual(
            first.blacklist_id,
            second.blacklist_id,
        )
        self.assertTrue(second.active)


if __name__ == "__main__":
    unittest.main()