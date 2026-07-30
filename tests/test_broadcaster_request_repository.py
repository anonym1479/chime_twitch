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
    BroadcasterRequestRepository,
    IdentityRepository,
    OpenBroadcasterRequestError,
)


class BroadcasterRequestRepositoryTests(
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

        self.repository = (
            BroadcasterRequestRepository(
                self.database
            )
        )

    async def create_request(
        self,
    ) -> BroadcasterRequest:
        return await self.repository.create(
            BroadcasterRequest(
                twitch_user_id="456",
                discord_user_id="123",
                requester_message=(
                    "I would like to test ChimeBuddy."
                ),
            )
        )

    async def test_create_request_and_event(
        self,
    ) -> None:
        created = await self.create_request()

        self.assertIsNotNone(created.request_id)
        self.assertEqual(
            created.status,
            BroadcasterRequestStatus.PENDING,
        )

        events = await self.repository.list_events(
            created.request_id
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0].event_type,
            "request_created",
        )
        self.assertEqual(
            events[0].to_status,
            BroadcasterRequestStatus.PENDING,
        )

    async def test_rejects_second_open_request(
        self,
    ) -> None:
        await self.create_request()

        with self.assertRaises(
            OpenBroadcasterRequestError
        ):
            await self.create_request()

    async def test_latest_request_includes_closed_requests(
        self,
    ) -> None:
        created = await self.create_request()

        await self.repository.transition(
            created.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=BroadcasterRequestStatus.REJECTED,
            event_type="request_rejected",
        )

        latest = (
            await self.repository.get_latest_for_discord(
                "123"
            )
        )

        self.assertIsNotNone(latest)
        self.assertEqual(
            latest.request_id,
            created.request_id,
        )
        self.assertEqual(
            latest.status,
            BroadcasterRequestStatus.REJECTED,
        )

    async def test_transition_is_atomic(
        self,
    ) -> None:
        created = await self.create_request()

        first_result = await self.repository.transition(
            created.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus.APPROVING
            ),
            event_type="request_approved",
            actor_discord_user_id="999",
        )

        second_result = await self.repository.transition(
            created.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus.APPROVING
            ),
            event_type="request_approved",
            actor_discord_user_id="999",
        )

        loaded = await self.repository.get(
            created.request_id
        )
        events = await self.repository.list_events(
            created.request_id
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(
            loaded.status,
            BroadcasterRequestStatus.APPROVING,
        )
        self.assertEqual(
            loaded.decided_by_discord_user_id,
            "999",
        )
        self.assertEqual(len(events), 2)

    async def test_rejection_records_reason(
        self,
    ) -> None:
        created = await self.create_request()

        changed = await self.repository.transition(
            created.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus.REJECTED
            ),
            event_type="request_rejected",
            actor_discord_user_id="999",
            decision_reason="Testing is currently closed.",
        )

        loaded = await self.repository.get(
            created.request_id
        )

        self.assertTrue(changed)
        self.assertEqual(
            loaded.status,
            BroadcasterRequestStatus.REJECTED,
        )
        self.assertEqual(
            loaded.decision_reason,
            "Testing is currently closed.",
        )
        self.assertEqual(
            loaded.decided_by_discord_user_id,
            "999",
        )
        self.assertIsNotNone(loaded.decided_at)

    async def test_saves_review_message_location(
        self,
    ) -> None:
        created = await self.create_request()

        changed = (
            await self.repository.set_review_message(
                created.request_id,
                guild_id="1000",
                channel_id="2000",
                message_id="3000",
            )
        )

        loaded = await self.repository.get(
            created.request_id
        )

        self.assertTrue(changed)
        self.assertEqual(
            loaded.review_guild_id,
            "1000",
        )
        self.assertEqual(
            loaded.review_channel_id,
            "2000",
        )
        self.assertEqual(
            loaded.review_message_id,
            "3000",
        )

    async def test_reauthorization_pauses_broadcaster_atomically(
        self,
    ) -> None:
        created = await self.create_request()

        await self.repository.transition(
            created.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=BroadcasterRequestStatus.ACTIVE,
            event_type="test_activated",
        )

        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO account_links (
                    twitch_user_id,
                    discord_user_id,
                    status,
                    verification_method,
                    verified_at
                )
                VALUES (?, ?, 'verified', ?, CURRENT_TIMESTAMP)
                """,
                ("456", "123", "test"),
            )
            await connection.execute(
                """
                INSERT INTO broadcasters (
                    twitch_user_id,
                    owner_discord_user_id,
                    enabled
                )
                VALUES (?, ?, 1)
                """,
                ("456", "123"),
            )
            await connection.commit()

        changed = (
            await self.repository
            .require_reauthorization_for_broadcaster(
                "456",
                reason="Refresh token rejected.",
            )
        )

        loaded = await self.repository.get(
            created.request_id
        )
        events = await self.repository.list_events(
            created.request_id
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT enabled
                FROM broadcasters
                WHERE twitch_user_id = ?
                """,
                ("456",),
            )
            broadcaster_row = await cursor.fetchone()
            await cursor.close()

        self.assertTrue(changed)
        self.assertEqual(
            loaded.status,
            BroadcasterRequestStatus
            .REAUTHORIZATION_REQUIRED,
        )
        self.assertEqual(broadcaster_row["enabled"], 0)
        self.assertEqual(
            events[-1].event_type,
            "broadcaster_reauthorization_required",
        )
        self.assertEqual(
            events[-1].from_status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertEqual(
            events[-1].to_status,
            BroadcasterRequestStatus
            .REAUTHORIZATION_REQUIRED,
        )

        restored = (
            await self.repository
            .complete_broadcaster_reauthorization(
                created.request_id,
                twitch_user_id="456",
                discord_user_id="123",
            )
        )

        loaded = await self.repository.get(
            created.request_id
        )
        events = await self.repository.list_events(
            created.request_id
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT enabled
                FROM broadcasters
                WHERE twitch_user_id = ?
                """,
                ("456",),
            )
            broadcaster_row = await cursor.fetchone()
            await cursor.close()

        self.assertTrue(restored)
        self.assertEqual(
            loaded.status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertEqual(broadcaster_row["enabled"], 1)
        self.assertEqual(
            events[-1].event_type,
            "broadcaster_reauthorization_completed",
        )


if __name__ == "__main__":
    unittest.main()
