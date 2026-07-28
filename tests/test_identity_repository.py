import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AccountLinkNotVerifiedError,
    IdentityRepository,
)


class IdentityRepositoryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        database_path = (
            Path(self.temp_directory.name) / "test.db"
        )

        self.database = Database(database_path)
        await self.database.initialize()

        self.repository = IdentityRepository(self.database)

        self.twitch_account = TwitchAccount(
            twitch_user_id="211164044",
            login="Example_Streamer",
            display_name="Example Streamer",
        )

        self.discord_account = DiscordAccount(
            discord_user_id="123456789012345678",
            username="example_user",
            display_name="Example User",
        )

        await self.repository.save_twitch_account(
            self.twitch_account
        )
        await self.repository.save_discord_account(
            self.discord_account
        )

    async def test_verified_link_allows_broadcaster(
        self,
    ) -> None:
        await self.repository.save_account_link(
            AccountLink(
                twitch_user_id=(
                    self.twitch_account.twitch_user_id
                ),
                discord_user_id=(
                    self.discord_account.discord_user_id
                ),
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        await self.repository.save_broadcaster(
            Broadcaster(
                twitch_user_id=(
                    self.twitch_account.twitch_user_id
                ),
                owner_discord_user_id=(
                    self.discord_account.discord_user_id
                ),
            )
        )

        profile = await self.repository.get_broadcaster(
            self.twitch_account.twitch_user_id
        )

        self.assertIsNotNone(profile)
        self.assertEqual(
            profile.twitch_user_id,
            "211164044",
        )
        self.assertEqual(
            profile.twitch_login,
            "example_streamer",
        )
        self.assertEqual(
            profile.link_status,
            AccountLinkStatus.VERIFIED,
        )
        self.assertTrue(profile.enabled)

    async def test_pending_link_rejects_broadcaster(
        self,
    ) -> None:
        await self.repository.save_account_link(
            AccountLink(
                twitch_user_id=(
                    self.twitch_account.twitch_user_id
                ),
                discord_user_id=(
                    self.discord_account.discord_user_id
                ),
                status=AccountLinkStatus.PENDING,
            )
        )

        with self.assertRaises(
            AccountLinkNotVerifiedError
        ):
            await self.repository.save_broadcaster(
                Broadcaster(
                    twitch_user_id=(
                        self.twitch_account.twitch_user_id
                    ),
                    owner_discord_user_id=(
                        self.discord_account.discord_user_id
                    ),
                )
            )

    async def test_names_can_change_without_changing_ids(
        self,
    ) -> None:
        await self.repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="211164044",
                login="new_streamer_name",
                display_name="New Streamer Name",
            )
        )

        await self.repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123456789012345678",
                username="new_discord_name",
                display_name="New Discord Name",
            )
        )

        await self.repository.save_account_link(
            AccountLink(
                twitch_user_id="211164044",
                discord_user_id="123456789012345678",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        await self.repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="211164044",
                owner_discord_user_id=(
                    "123456789012345678"
                ),
            )
        )

        profile = await self.repository.get_broadcaster(
            "211164044"
        )

        self.assertEqual(
            profile.twitch_login,
            "new_streamer_name",
        )
        self.assertEqual(
            profile.owner_discord_username,
            "new_discord_name",
        )

    async def test_enabled_filter(self) -> None:
        await self.repository.save_account_link(
            AccountLink(
                twitch_user_id="211164044",
                discord_user_id="123456789012345678",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        await self.repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="211164044",
                owner_discord_user_id=(
                    "123456789012345678"
                ),
            )
        )

        changed = (
            await self.repository.set_broadcaster_enabled(
                "211164044",
                False,
            )
        )

        enabled_profiles = (
            await self.repository.list_broadcasters(
                enabled_only=True
            )
        )

        all_profiles = (
            await self.repository.list_broadcasters()
        )

        self.assertTrue(changed)
        self.assertEqual(enabled_profiles, [])
        self.assertEqual(len(all_profiles), 1)
        self.assertFalse(all_profiles[0].enabled)


if __name__ == "__main__":
    unittest.main()