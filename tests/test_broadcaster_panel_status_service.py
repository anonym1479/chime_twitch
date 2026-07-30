import tempfile
import time
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
    OAuthCredential,
    OAuthCredentialKind,
    Trigger,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterPanelRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
    TriggerRepository,
)
from chimebuddy.services import (
    BroadcasterPanelNotFoundError,
    BroadcasterPanelStatusService,
)


class BroadcasterPanelStatusServiceTests(
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

        self.identity_repository = IdentityRepository(
            self.database
        )
        self.request_repository = (
            BroadcasterRequestRepository(
                self.database
            )
        )
        self.panel_repository = (
            BroadcasterPanelRepository(
                self.database
            )
        )
        self.credential_repository = (
            OAuthCredentialRepository(
                self.database
            )
        )
        self.trigger_repository = (
            TriggerRepository(
                self.database
            )
        )

        await self.identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="456",
                login="example_streamer",
                display_name="Example Streamer",
            )
        )

        await self.identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123",
                username="example_user",
                display_name="Example User",
            )
        )

        await self.identity_repository.save_account_link(
            AccountLink(
                twitch_user_id="456",
                discord_user_id="123",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        await self.identity_repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="456",
                owner_discord_user_id="123",
                enabled=True,
            )
        )

        request = await self.request_repository.create(
            BroadcasterRequest(
                twitch_user_id="456",
                discord_user_id="123",
            )
        )

        await self.panel_repository.create(
            BroadcasterPanel(
                twitch_user_id="456",
                request_id=request.request_id,
                discord_guild_id="1000",
                discord_channel_id="2000",
                opening_message_id="3000",
            )
        )

        await self.credential_repository.save(
            OAuthCredential(
                twitch_user_id="456",
                credential_kind=(
                    OAuthCredentialKind.BROADCASTER
                ),
                access_token="test-access-token",
                refresh_token="test-refresh-token",
                scopes=("channel:bot",),
                expires_at=int(time.time()) + 3600,
            )
        )

        await self.trigger_repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="456",
                name="Enabled Trigger",
                expression="enabled",
                response_message="Enabled response.",
                enabled=True,
            )
        )

        await self.trigger_repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="456",
                name="Disabled Trigger",
                expression="disabled",
                response_message="Disabled response.",
                enabled=False,
            )
        )

        self.service = BroadcasterPanelStatusService(
            panel_repository=self.panel_repository,
            identity_repository=(
                self.identity_repository
            ),
            request_repository=(
                self.request_repository
            ),
            credential_repository=(
                self.credential_repository
            ),
            trigger_repository=(
                self.trigger_repository
            ),
        )

    async def test_builds_complete_status(
        self,
    ) -> None:
        status = (
            await self.service.get_for_broadcaster(
                "456"
            )
        )

        self.assertEqual(
            status.twitch_login,
            "example_streamer",
        )
        self.assertEqual(
            status.owner_discord_user_id,
            "123",
        )
        self.assertTrue(
            status.broadcaster_enabled
        )
        self.assertEqual(
            status.total_triggers,
            2,
        )
        self.assertEqual(
            status.enabled_triggers,
            1,
        )
        self.assertEqual(
            status.disabled_triggers,
            1,
        )
        self.assertTrue(
            status.credential_stored
        )
        self.assertIsNotNone(
            status.credential_expires_at
        )

    async def test_loads_status_from_channel(
        self,
    ) -> None:
        status = (
            await self.service.get_for_channel(
                "2000"
            )
        )

        self.assertEqual(
            status.twitch_user_id,
            "456",
        )
        self.assertEqual(
            status.opening_message_id,
            "3000",
        )

    async def test_rejects_unknown_panel(
        self,
    ) -> None:
        with self.assertRaises(
            BroadcasterPanelNotFoundError
        ):
            await self.service.get_for_broadcaster(
                "unknown"
            )


if __name__ == "__main__":
    unittest.main()