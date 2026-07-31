import json
import tempfile
import time
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterRequestRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)
from chimebuddy.services import (
    BroadcasterRestorationBlockedError,
    BroadcasterSuspensionService,
)


class BroadcasterSuspensionServiceTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        self.database = Database(
            Path(self.temp_directory.name) / "test.db"
        )
        await self.database.initialize()

        self.identity_repository = IdentityRepository(
            self.database
        )
        self.credential_repository = (
            OAuthCredentialRepository(self.database)
        )
        self.request_repository = (
            BroadcasterRequestRepository(self.database)
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
        await self.credential_repository.save(
            OAuthCredential(
                twitch_user_id="456",
                credential_kind=(
                    OAuthCredentialKind.BROADCASTER
                ),
                access_token="access",
                refresh_token="refresh",
                scopes=("channel:bot",),
                expires_at=int(time.time()) + 3600,
            )
        )

        self.request = await self.request_repository.create(
            BroadcasterRequest(
                twitch_user_id="456",
                discord_user_id="123",
            )
        )
        await self.request_repository.transition(
            self.request.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=BroadcasterRequestStatus.ACTIVE,
            event_type="test_activated",
        )

        self.service = BroadcasterSuspensionService(
            request_repository=self.request_repository,
            credential_repository=self.credential_repository,
        )

    async def test_suspend_and_restore_are_atomic_and_audited(
        self,
    ) -> None:
        suspended = await self.service.suspend(
            self.request.request_id,
            developer_discord_user_id="999",
            internal_reason="Closed-beta safety test.",
        )
        profile = await self.identity_repository.get_broadcaster(
            "456"
        )
        events = await self.request_repository.list_events(
            self.request.request_id
        )

        self.assertEqual(
            suspended.status,
            BroadcasterRequestStatus.SUSPENDED,
        )
        self.assertIsNone(suspended.decision_reason)
        self.assertFalse(profile.enabled)
        self.assertEqual(
            events[-1].event_type,
            "broadcaster_suspended",
        )
        self.assertEqual(
            events[-1].actor_discord_user_id,
            "999",
        )
        self.assertEqual(
            json.loads(events[-1].details_json)[
                "internal_reason"
            ],
            "Closed-beta safety test.",
        )

        restored = await self.service.restore(
            self.request.request_id,
            developer_discord_user_id="999",
        )
        profile = await self.identity_repository.get_broadcaster(
            "456"
        )
        events = await self.request_repository.list_events(
            self.request.request_id
        )

        self.assertEqual(
            restored.status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertTrue(profile.enabled)
        self.assertEqual(
            events[-1].event_type,
            "broadcaster_restored",
        )
        self.assertEqual(
            events[-1].actor_discord_user_id,
            "999",
        )

    async def test_repeated_suspension_is_idempotent(
        self,
    ) -> None:
        await self.service.suspend(
            self.request.request_id,
            developer_discord_user_id="999",
            internal_reason="First reason.",
        )
        await self.service.suspend(
            self.request.request_id,
            developer_discord_user_id="999",
            internal_reason="Repeated click.",
        )

        events = await self.request_repository.list_events(
            self.request.request_id
        )
        suspension_events = [
            event
            for event in events
            if event.event_type == "broadcaster_suspended"
        ]

        self.assertEqual(len(suspension_events), 1)

    async def test_restore_requires_authorization(self) -> None:
        await self.service.suspend(
            self.request.request_id,
            developer_discord_user_id="999",
            internal_reason="Test suspension.",
        )
        await self.credential_repository.delete(
            "456",
            OAuthCredentialKind.BROADCASTER,
        )

        with self.assertRaises(
            BroadcasterRestorationBlockedError
        ):
            await self.service.restore(
                self.request.request_id,
                developer_discord_user_id="999",
            )

        request = await self.request_repository.get(
            self.request.request_id
        )
        profile = await self.identity_repository.get_broadcaster(
            "456"
        )
        self.assertEqual(
            request.status,
            BroadcasterRequestStatus.SUSPENDED,
        )
        self.assertFalse(profile.enabled)


if __name__ == "__main__":
    unittest.main()
