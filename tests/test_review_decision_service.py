import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    BroadcasterBlacklistRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)
from chimebuddy.services import (
    ReviewDecisionService,
    ReviewRequestNotFoundError,
    ReviewRequestStateError,
)


class ReviewDecisionServiceTests(
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

        await identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123",
                username="example_user",
                display_name="Example User",
            )
        )

        await identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="456",
                login="example_streamer",
                display_name="Example Streamer",
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

        self.service = ReviewDecisionService(
            self.request_repository
        )

        self.request = (
            await self.request_repository.create(
                BroadcasterRequest(
                    twitch_user_id="456",
                    discord_user_id="123",
                    requester_message="Please add me.",
                )
            )
        )

    async def test_approve_claims_pending_request(
        self,
    ) -> None:
        decided = await self.service.approve(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        self.assertEqual(
            decided.status,
            BroadcasterRequestStatus.APPROVING,
        )
        self.assertEqual(
            decided.decided_by_discord_user_id,
            "999",
        )
        self.assertIsNotNone(decided.decided_at)

        events = (
            await self.request_repository.list_events(
                self.request.request_id
            )
        )

        self.assertEqual(
            events[-1].event_type,
            "request_approved",
        )

    async def test_second_decision_is_rejected(
        self,
    ) -> None:
        await self.service.approve(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        with self.assertRaises(
            ReviewRequestStateError
        ):
            await self.service.reject(
                self.request.request_id,
                actor_discord_user_id="999",
                requester_message="Too late.",
            )

    async def test_rejection_records_message(
        self,
    ) -> None:
        decided = await self.service.reject(
            self.request.request_id,
            actor_discord_user_id="999",
            requester_message=(
                "Testing is currently closed."
            ),
        )

        self.assertEqual(
            decided.status,
            BroadcasterRequestStatus.REJECTED,
        )
        self.assertEqual(
            decided.decision_reason,
            "Testing is currently closed.",
        )
        self.assertEqual(
            decided.decided_by_discord_user_id,
            "999",
        )
        self.assertIsNotNone(decided.decided_at)

    async def test_rejection_message_is_optional(
        self,
    ) -> None:
        decided = await self.service.reject(
            self.request.request_id,
            actor_discord_user_id="999",
        )

        self.assertEqual(
            decided.status,
            BroadcasterRequestStatus.REJECTED,
        )
        self.assertIsNone(
            decided.decision_reason
        )

    async def test_blacklist_is_atomic(
        self,
    ) -> None:
        decided = await self.service.blacklist(
            self.request.request_id,
            actor_discord_user_id="999",
            internal_reason=(
                "Repeated abuse during testing."
            ),
            requester_message=(
                "Access cannot be granted."
            ),
        )

        blacklist_entry = (
            await self.blacklist_repository.find_active(
                discord_user_id="123",
                twitch_user_id="456",
            )
        )

        self.assertEqual(
            decided.status,
            BroadcasterRequestStatus.BLACKLISTED,
        )
        self.assertEqual(
            decided.decision_reason,
            "Access cannot be granted.",
        )
        self.assertIsNotNone(blacklist_entry)
        self.assertEqual(
            blacklist_entry.internal_reason,
            "Repeated abuse during testing.",
        )
        self.assertEqual(
            blacklist_entry.created_by_discord_user_id,
            "999",
        )

        events = (
            await self.request_repository.list_events(
                self.request.request_id
            )
        )

        self.assertEqual(
            events[-1].event_type,
            "request_blacklisted",
        )

    async def test_unknown_request_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ReviewRequestNotFoundError
        ):
            await self.service.approve(
                99999,
                actor_discord_user_id="999",
            )


if __name__ == "__main__":
    unittest.main()