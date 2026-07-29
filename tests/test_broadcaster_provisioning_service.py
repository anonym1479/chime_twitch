import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterBlacklistRepository,
    BroadcasterPanelRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)
from chimebuddy.services import (
    BroadcasterProvisioningFailedError,
    BroadcasterProvisioningService,
    BroadcasterProvisioningStateError,
    DiscordPanelLocation,
    OnboardingService,
)


class FakePanelGateway:
    def __init__(self) -> None:
        self.calls = 0
        self.failures_remaining = 0

    async def ensure_panel(
        self,
        *,
        request,
        twitch_login,
        existing_panel,
    ) -> DiscordPanelLocation:
        self.calls += 1

        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise RuntimeError(
                "Test Discord failure."
            )

        return DiscordPanelLocation(
            discord_guild_id="1000",
            discord_channel_id="2000",
            opening_message_id="3000",
        )


class BroadcasterProvisioningServiceTests(
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

        self.onboarding_service = OnboardingService(
            identity_repository=(
                self.identity_repository
            ),
            credential_repository=(
                OAuthCredentialRepository(
                    self.database
                )
            ),
            request_repository=(
                self.request_repository
            ),
            blacklist_repository=(
                BroadcasterBlacklistRepository(
                    self.database
                )
            ),
        )

        self.gateway = FakePanelGateway()

        self.service = BroadcasterProvisioningService(
            onboarding_service=(
                self.onboarding_service
            ),
            identity_repository=(
                self.identity_repository
            ),
            request_repository=(
                self.request_repository
            ),
            panel_repository=(
                self.panel_repository
            ),
            panel_gateway=self.gateway,
        )

        self.request = (
            await self.request_repository.create(
                BroadcasterRequest(
                    twitch_user_id="456",
                    discord_user_id="123",
                )
            )
        )

    async def approve_request(self) -> None:
        await self.onboarding_service.begin_approval(
            self.request.request_id,
            developer_discord_user_id="999",
        )

    async def test_successful_provisioning(
        self,
    ) -> None:
        await self.approve_request()

        result = await self.service.provision(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        request = await self.request_repository.get(
            self.request.request_id
        )
        broadcaster = (
            await self.identity_repository
            .get_broadcaster("456")
        )
        panel = (
            await self.panel_repository
            .get_for_broadcaster("456")
        )

        self.assertEqual(
            request.status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertTrue(broadcaster.enabled)
        self.assertEqual(
            panel.discord_channel_id,
            "2000",
        )
        self.assertEqual(
            result.discord_channel_id,
            "2000",
        )
        self.assertFalse(result.already_active)
        self.assertEqual(self.gateway.calls, 1)

    async def test_active_request_is_idempotent(
        self,
    ) -> None:
        await self.approve_request()

        await self.service.provision(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        second_result = await self.service.provision(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        self.assertTrue(
            second_result.already_active
        )
        self.assertEqual(self.gateway.calls, 1)

    async def test_failure_is_recorded_and_retryable(
        self,
    ) -> None:
        await self.approve_request()
        self.gateway.failures_remaining = 1

        with self.assertRaises(
            BroadcasterProvisioningFailedError
        ):
            await self.service.provision(
                self.request.request_id,
                actor_discord_user_id="999",
            )

        failed_request = (
            await self.request_repository.get(
                self.request.request_id
            )
        )
        broadcaster = (
            await self.identity_repository
            .get_broadcaster("456")
        )

        self.assertEqual(
            failed_request.status,
            BroadcasterRequestStatus.PROVISIONING_FAILED,
        )
        self.assertFalse(broadcaster.enabled)

        result = await self.service.provision(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        retried_request = (
            await self.request_repository.get(
                self.request.request_id
            )
        )

        self.assertEqual(
            retried_request.status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertEqual(
            result.discord_channel_id,
            "2000",
        )
        self.assertEqual(self.gateway.calls, 2)

    async def test_pending_request_cannot_be_provisioned(
        self,
    ) -> None:
        with self.assertRaises(
            BroadcasterProvisioningStateError
        ):
            await self.service.provision(
                self.request.request_id,
                actor_discord_user_id="999",
            )

        self.assertEqual(self.gateway.calls, 0)


if __name__ == "__main__":
    unittest.main()