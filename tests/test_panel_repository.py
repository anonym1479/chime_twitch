import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    BroadcasterPanel,
    BroadcasterRequest,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterPanelExistsError,
    BroadcasterPanelRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)


class BroadcasterPanelRepositoryTests(
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

        identity_repository = IdentityRepository(
            self.database
        )

        await identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="456",
                login="example_streamer",
                display_name="Example Streamer",
            )
        )

        await identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123",
                username="example_user",
                display_name="Example User",
            )
        )

        await identity_repository.save_account_link(
            AccountLink(
                twitch_user_id="456",
                discord_user_id="123",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        await identity_repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="456",
                owner_discord_user_id="123",
            )
        )

        request_repository = (
            BroadcasterRequestRepository(
                self.database
            )
        )

        self.request = await request_repository.create(
            BroadcasterRequest(
                twitch_user_id="456",
                discord_user_id="123",
            )
        )

        self.repository = (
            BroadcasterPanelRepository(
                self.database
            )
        )

    def make_panel(self) -> BroadcasterPanel:
        return BroadcasterPanel(
            twitch_user_id="456",
            request_id=self.request.request_id,
            discord_guild_id="1000",
            discord_channel_id="2000",
        )

    async def test_create_and_load_panel(
        self,
    ) -> None:
        created = await self.repository.create(
            self.make_panel()
        )

        loaded = (
            await self.repository
            .get_for_broadcaster("456")
        )

        self.assertEqual(
            created.discord_channel_id,
            "2000",
        )
        self.assertEqual(
            loaded.request_id,
            self.request.request_id,
        )

    async def test_find_panel_by_channel(
        self,
    ) -> None:
        await self.repository.create(
            self.make_panel()
        )

        loaded = (
            await self.repository
            .get_for_channel("2000")
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(
            loaded.twitch_user_id,
            "456",
        )

    async def test_rejects_duplicate_panel(
        self,
    ) -> None:
        await self.repository.create(
            self.make_panel()
        )

        with self.assertRaises(
            BroadcasterPanelExistsError
        ):
            await self.repository.create(
                self.make_panel()
            )

    async def test_sets_opening_message(
        self,
    ) -> None:
        await self.repository.create(
            self.make_panel()
        )

        changed = (
            await self.repository
            .set_opening_message(
                "456",
                "3000",
            )
        )

        loaded = (
            await self.repository
            .get_for_broadcaster("456")
        )

        self.assertTrue(changed)
        self.assertEqual(
            loaded.opening_message_id,
            "3000",
        )

    async def test_delete_is_idempotent(
        self,
    ) -> None:
        await self.repository.create(
            self.make_panel()
        )

        first_result = await self.repository.delete(
            "456"
        )
        second_result = await self.repository.delete(
            "456"
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)


if __name__ == "__main__":
    unittest.main()