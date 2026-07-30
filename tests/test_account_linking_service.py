import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLinkSessionStatus,
    AccountLinkStatus,
    Broadcaster,
    BroadcasterBlacklistEntry,
    BroadcasterRequestStatus,
    DiscordAccount,
    OAuthCredentialKind,
)
from chimebuddy.repositories import (
    AccountLinkCompletionRepository,
    AccountLinkSessionRepository,
    BroadcasterBlacklistRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)
from chimebuddy.services import (
    AccountLinkingService,
    BlacklistedIdentityError,
    ExistingBroadcasterRequestError,
    LinkAuthorizationValidationError,
    OnboardingService,
)
from chimebuddy.twitch.device_authorization import (
    DeviceAuthorization,
)
from chimebuddy.twitch.oauth_client import (
    RefreshedTokens,
    TokenValidation,
)


class FakeDeviceClient:
    def __init__(self) -> None:
        self.start_calls = 0

    async def start(
        self,
        scopes: tuple[str, ...],
    ) -> DeviceAuthorization:
        self.start_calls += 1

        return DeviceAuthorization(
            device_code="secret-device-code",
            user_code="PUBLIC123",
            verification_uri=(
                "https://www.twitch.tv/activate"
            ),
            expires_in=300,
            interval=1,
        )


class FakeOAuthClient:
    client_id = "test-client-id"

    def __init__(
        self,
        *,
        user_id: str = "456",
        login: str = "example_streamer",
    ) -> None:
        self.user_id = user_id
        self.login = login

    async def validate(
        self,
        access_token: str,
    ) -> TokenValidation:
        return TokenValidation(
            client_id=self.client_id,
            user_id=self.user_id,
            login=self.login,
            scopes=("channel:bot",),
            expires_in=3600,
        )


async def fake_authorization_waiter(
    device_client,
    authorization,
    scopes,
) -> RefreshedTokens:
    return RefreshedTokens(
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        scopes=("channel:bot",),
        expires_in=3600,
        token_type="bearer",
    )


class AccountLinkingServiceTests(
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
        self.session_repository = (
            AccountLinkSessionRepository(
                self.database
            )
        )
        self.blacklist_repository = (
            BroadcasterBlacklistRepository(
                self.database
            )
        )
        self.request_repository = (
            BroadcasterRequestRepository(
                self.database
            )
        )

        onboarding_service = OnboardingService(
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

        self.device_client = FakeDeviceClient()

        self.oauth_client = FakeOAuthClient()

        self.service = AccountLinkingService(
            device_client=self.device_client,
            oauth_client=self.oauth_client,
            identity_repository=(
                self.identity_repository
            ),
            session_repository=(
                self.session_repository
            ),
            completion_repository=(
                AccountLinkCompletionRepository(
                    self.database
                )
            ),
            blacklist_repository=(
                self.blacklist_repository
            ),
            onboarding_service=onboarding_service,
            authorization_waiter=(
                fake_authorization_waiter
            ),
            scopes=("channel:bot",),
        )

        self.discord_account = DiscordAccount(
            discord_user_id="123",
            username="example_user",
            display_name="Example User",
        )

    async def prepare_reauthorization(self):
        first_challenge = await self.service.start(
            self.discord_account
        )
        first_result = await self.service.complete(
            first_challenge
        )

        await self.request_repository.transition(
            first_result.request.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=BroadcasterRequestStatus.ACTIVE,
            event_type="test_activated",
        )

        await self.identity_repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="456",
                owner_discord_user_id="123",
                enabled=True,
            )
        )

        await (
            self.request_repository
            .require_reauthorization_for_broadcaster(
                "456",
                reason="Refresh token rejected.",
            )
        )

        return first_result

    async def test_start_creates_private_challenge(
        self,
    ) -> None:
        challenge = await self.service.start(
            self.discord_account
        )

        stored_session = (
            await self.session_repository.get(
                challenge.session_id
            )
        )

        self.assertEqual(
            challenge.user_code,
            "PUBLIC123",
        )
        self.assertEqual(
            stored_session.discord_user_id,
            "123",
        )
        self.assertNotIn(
            "secret-device-code",
            repr(challenge),
        )

    async def test_authentication_does_not_save_link(
        self,
    ) -> None:
        challenge = await self.service.start(
            self.discord_account
        )

        authorization = await self.service.authenticate(
            challenge
        )

        link = (
            await self.identity_repository
            .get_account_link("456")
        )
        credential = (
            await self.credential_repository.get(
                "456",
                OAuthCredentialKind.BROADCASTER,
            )
        )
        request = (
            await self.request_repository
            .get_open_for_discord("123")
        )

        self.assertEqual(
            authorization.twitch_login,
            "example_streamer",
        )
        self.assertIsNone(link)
        self.assertIsNone(credential)
        self.assertIsNone(request)
        self.assertNotIn(
            "test-access-token",
            repr(authorization),
        )

    async def test_confirmation_creates_request(
        self,
    ) -> None:
        challenge = await self.service.start(
            self.discord_account
        )

        authorization = await self.service.authenticate(
            challenge
        )

        result = (
            await self.service
            .confirm_and_create_request(
                authorization,
                requester_message=(
                    "Please add my Twitch channel."
                ),
            )
        )

        link = (
            await self.identity_repository
            .get_account_link("456")
        )
        credential = (
            await self.credential_repository.get(
                "456",
                OAuthCredentialKind.BROADCASTER,
            )
        )

        self.assertEqual(
            link.status,
            AccountLinkStatus.VERIFIED,
        )
        self.assertIsNotNone(credential)
        self.assertEqual(
            result.request.status,
            BroadcasterRequestStatus.PENDING,
        )
        self.assertEqual(
            result.request.requester_message,
            "Please add my Twitch channel.",
        )

    async def test_cancel_discards_pending_session(
        self,
    ) -> None:
        challenge = await self.service.start(
            self.discord_account
        )

        authorization = await self.service.authenticate(
            challenge
        )

        cancelled = (
            await self.service.cancel_authorization(
                authorization
            )
        )

        stored_session = (
            await self.session_repository.get(
                challenge.session_id
            )
        )

        self.assertTrue(cancelled)
        self.assertEqual(
            stored_session.status,
            AccountLinkSessionStatus.CANCELLED,
        )

    async def test_blacklist_blocks_before_twitch(
        self,
    ) -> None:
        await self.blacklist_repository.create(
            BroadcasterBlacklistEntry(
                discord_user_id="123",
                internal_reason="Test blacklist.",
                created_by_discord_user_id="999",
            )
        )

        with self.assertRaises(
            BlacklistedIdentityError
        ):
            await self.service.start(
                self.discord_account
            )

        self.assertEqual(
            self.device_client.start_calls,
            0,
        )

    async def test_existing_request_blocks_before_twitch(
        self,
    ) -> None:
        challenge = await self.service.start(
            self.discord_account
        )

        await self.service.complete(challenge)

        self.device_client.start_calls = 0

        with self.assertRaises(
            ExistingBroadcasterRequestError
        ):
            await self.service.start(
                self.discord_account
            )

        self.assertEqual(
            self.device_client.start_calls,
            0,
        )

    async def test_reauthorization_reuses_active_request(
        self,
    ) -> None:
        first_result = await self.prepare_reauthorization()

        reconnect_challenge = await self.service.start(
            self.discord_account
        )
        authorization = await self.service.authenticate(
            reconnect_challenge
        )
        result = (
            await self.service
            .confirm_and_create_request(authorization)
        )

        broadcaster = (
            await self.identity_repository.get_broadcaster(
                "456"
            )
        )

        self.assertTrue(result.was_reauthorization)
        self.assertEqual(
            result.request.request_id,
            first_result.request.request_id,
        )
        self.assertEqual(
            result.request.status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertTrue(broadcaster.enabled)

    async def test_reauthorization_requires_same_twitch_account(
        self,
    ) -> None:
        await self.prepare_reauthorization()

        reconnect_challenge = await self.service.start(
            self.discord_account
        )

        self.oauth_client.user_id = "different-user"
        self.oauth_client.login = "wrong_streamer"

        with self.assertRaises(
            LinkAuthorizationValidationError
        ):
            await self.service.authenticate(
                reconnect_challenge
            )

        request = (
            await self.request_repository
            .get_open_for_discord("123")
        )
        broadcaster = (
            await self.identity_repository.get_broadcaster(
                "456"
            )
        )

        self.assertEqual(
            request.status,
            BroadcasterRequestStatus
            .REAUTHORIZATION_REQUIRED,
        )
        self.assertFalse(broadcaster.enabled)


if __name__ == "__main__":
    unittest.main()
