import time
import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    BroadcasterBlacklistEntry,
    BroadcasterRequestStatus,
    DiscordAccount,
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterBlacklistRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)
from chimebuddy.services import (
    AccountLinkRequiredError,
    BlacklistedIdentityError,
    BroadcasterAuthorizationRequiredError,
    OnboardingService,
    RequestStateConflictError,
)


class OnboardingServiceTests(
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
        self.credential_repository = (
            OAuthCredentialRepository(
                self.database
            )
        )
        self.request_repository = (
            BroadcasterRequestRepository(
                self.database
            )
        )
        self.blacklist_repository = (
            BroadcasterBlacklistRepository(
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
                verification_method="device_code",
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

        self.service = OnboardingService(
            identity_repository=(
                self.identity_repository
            ),
            credential_repository=(
                self.credential_repository
            ),
            request_repository=(
                self.request_repository
            ),
            blacklist_repository=(
                self.blacklist_repository
            ),
        )

    async def create_request(self):
        return await self.service.create_request(
            twitch_user_id="456",
            discord_user_id="123",
            requester_message="Please add my channel.",
        )

    async def test_creates_valid_request(
        self,
    ) -> None:
        request = await self.create_request()

        self.assertEqual(
            request.status,
            BroadcasterRequestStatus.PENDING,
        )
        self.assertEqual(
            request.requester_message,
            "Please add my channel.",
        )

    async def test_requires_matching_verified_link(
        self,
    ) -> None:
        with self.assertRaises(
            AccountLinkRequiredError
        ):
            await self.service.create_request(
                twitch_user_id="456",
                discord_user_id="different-user",
            )

    async def test_requires_broadcaster_authorization(
        self,
    ) -> None:
        await self.credential_repository.delete(
            "456",
            OAuthCredentialKind.BROADCASTER,
        )

        with self.assertRaises(
            BroadcasterAuthorizationRequiredError
        ):
            await self.create_request()

    async def test_rejects_blacklisted_identity(
        self,
    ) -> None:
        await self.blacklist_repository.create(
            BroadcasterBlacklistEntry(
                discord_user_id="123",
                twitch_user_id="456",
                internal_reason="Test blacklist.",
                created_by_discord_user_id="999",
            )
        )

        with self.assertRaises(
            BlacklistedIdentityError
        ):
            await self.create_request()

    async def test_approval_is_idempotent(
        self,
    ) -> None:
        request = await self.create_request()

        approved = await self.service.begin_approval(
            request.request_id,
            developer_discord_user_id="999",
        )

        self.assertEqual(
            approved.status,
            BroadcasterRequestStatus.APPROVING,
        )

        with self.assertRaises(
            RequestStateConflictError
        ):
            await self.service.begin_approval(
                request.request_id,
                developer_discord_user_id="999",
            )

    async def test_rejection_records_reason(
        self,
    ) -> None:
        request = await self.create_request()

        rejected = await self.service.reject_request(
            request.request_id,
            developer_discord_user_id="999",
            reason="Testing capacity is currently full.",
        )

        self.assertEqual(
            rejected.status,
            BroadcasterRequestStatus.REJECTED,
        )
        self.assertEqual(
            rejected.decision_reason,
            "Testing capacity is currently full.",
        )


if __name__ == "__main__":
    unittest.main()