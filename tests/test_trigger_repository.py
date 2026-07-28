import asyncio
import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    DiscordAccount,
    Trigger,
    TriggerMatchType,
    TriggerRuntimeStatus,
    TwitchAccount,
)
from chimebuddy.repositories import (
    DuplicateTriggerNameError,
    IdentityRepository,
    TriggerRepository,
)


class TriggerRepositoryTests(
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

        identity_repository = IdentityRepository(
            self.database
        )

        await identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="211164044",
                login="example_streamer",
                display_name="Example Streamer",
            )
        )

        await identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123456789012345678",
                username="example_user",
                display_name="Example User",
            )
        )

        await identity_repository.save_account_link(
            AccountLink(
                twitch_user_id="211164044",
                discord_user_id="123456789012345678",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        await identity_repository.save_broadcaster(
            Broadcaster(
                twitch_user_id="211164044",
                owner_discord_user_id=(
                    "123456789012345678"
                ),
            )
        )

        self.repository = TriggerRepository(self.database)

    async def test_create_trigger_and_runtime_state(
        self,
    ) -> None:
        created = await self.repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="211164044",
                name="Solo Mode",
                expression="solo",
                response_message=(
                    "The streamer is currently playing solo."
                ),
            )
        )

        self.assertIsNotNone(created.trigger_id)
        self.assertEqual(
            created.match_type,
            TriggerMatchType.CONTAINS,
        )

        stored = await self.repository.get_trigger(
            created.trigger_id
        )

        state = await self.repository.get_runtime_state(
            created.trigger_id
        )

        self.assertEqual(stored, created)
        self.assertIsNotNone(state)
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.INACTIVE,
        )
        self.assertFalse(state.is_pinned)
        self.assertIsNone(state.message_id)

    async def test_duplicate_name_is_rejected(
        self,
    ) -> None:
        trigger = Trigger(
            broadcaster_twitch_user_id="211164044",
            name="Solo Mode",
            expression="solo",
            response_message="Solo mode is active.",
        )

        await self.repository.create_trigger(trigger)

        with self.assertRaises(
            DuplicateTriggerNameError
        ):
            await self.repository.create_trigger(
                Trigger(
                    broadcaster_twitch_user_id=(
                        "211164044"
                    ),
                    name="solo mode",
                    expression="different expression",
                    response_message="Different message.",
                )
            )

    async def test_enabled_filter_and_priority(
        self,
    ) -> None:
        first = await self.repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="211164044",
                name="Lower Priority",
                expression="first",
                response_message="First message.",
                priority=200,
            )
        )

        second = await self.repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="211164044",
                name="Higher Priority",
                expression="second",
                response_message="Second message.",
                priority=10,
            )
        )

        await self.repository.set_trigger_enabled(
            second.trigger_id,
            False,
        )

        all_triggers = (
            await self.repository.list_triggers(
                "211164044"
            )
        )

        enabled_triggers = (
            await self.repository.list_triggers(
                "211164044",
                enabled_only=True,
            )
        )

        self.assertEqual(
            [trigger.trigger_id for trigger in all_triggers],
            [second.trigger_id, first.trigger_id],
        )
        self.assertEqual(
            [trigger.trigger_id for trigger in enabled_triggers],
            [first.trigger_id],
        )
    async def create_solo_trigger(self) -> Trigger:
        return await self.repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="211164044",
                name="Solo Mode",
                expression="solo",
                response_message="Solo mode is active.",
            )
        )

    async def test_only_one_activation_claim_succeeds(
        self,
    ) -> None:
        trigger = await self.create_solo_trigger()

        results = await asyncio.gather(
            self.repository.claim_activation(
                trigger.trigger_id,
                "Ranked solo gameplay",
            ),
            self.repository.claim_activation(
                trigger.trigger_id,
                "Ranked solo gameplay",
            ),
        )

        self.assertEqual(
            sorted(results),
            [False, True],
        )

        state = await self.repository.get_runtime_state(
            trigger.trigger_id
        )

        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.ACTIVATING,
        )
        self.assertEqual(
            state.last_title,
            "Ranked solo gameplay",
        )

    async def test_complete_activation_records_message(
        self,
    ) -> None:
        trigger = await self.create_solo_trigger()

        claimed = await self.repository.claim_activation(
            trigger.trigger_id,
            "Ranked solo gameplay",
        )

        completed = (
            await self.repository.complete_activation(
                trigger.trigger_id,
                "message-123",
                is_pinned=True,
            )
        )

        state = await self.repository.get_runtime_state(
            trigger.trigger_id
        )

        self.assertTrue(claimed)
        self.assertTrue(completed)
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.ACTIVE,
        )
        self.assertEqual(
            state.message_id,
            "message-123",
        )
        self.assertTrue(state.is_pinned)
        self.assertIsNone(state.operation_started_at)

    async def test_full_deactivation_clears_state(
        self,
    ) -> None:
        trigger = await self.create_solo_trigger()

        await self.repository.claim_activation(
            trigger.trigger_id,
            "Ranked solo gameplay",
        )

        await self.repository.complete_activation(
            trigger.trigger_id,
            "message-123",
            is_pinned=True,
        )

        claimed = (
            await self.repository.claim_deactivation(
                trigger.trigger_id
            )
        )

        completed = (
            await self.repository.complete_deactivation(
                trigger.trigger_id
            )
        )

        state = await self.repository.get_runtime_state(
            trigger.trigger_id
        )

        self.assertTrue(claimed)
        self.assertTrue(completed)
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.INACTIVE,
        )
        self.assertIsNone(state.message_id)
        self.assertFalse(state.is_pinned)
        self.assertIsNone(state.last_title)

    async def test_error_without_message_can_reset(
        self,
    ) -> None:
        trigger = await self.create_solo_trigger()

        await self.repository.claim_activation(
            trigger.trigger_id,
            "Ranked solo gameplay",
        )

        marked = (
            await self.repository.mark_operation_error(
                trigger.trigger_id,
                "Test activation failure",
            )
        )

        reset = await self.repository.reset_error(
            trigger.trigger_id
        )

        state = await self.repository.get_runtime_state(
            trigger.trigger_id
        )

        self.assertTrue(marked)
        self.assertTrue(reset)
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.INACTIVE,
        )
        self.assertIsNone(state.last_error)

    async def test_error_with_message_requires_cleanup(
        self,
    ) -> None:
        trigger = await self.create_solo_trigger()

        await self.repository.claim_activation(
            trigger.trigger_id,
            "Ranked solo gameplay",
        )

        await self.repository.mark_operation_error(
            trigger.trigger_id,
            "Pinning failed after sending.",
            message_id="message-123",
            is_pinned=False,
        )

        reset = await self.repository.reset_error(
            trigger.trigger_id
        )

        state = await self.repository.get_runtime_state(
            trigger.trigger_id
        )

        self.assertFalse(reset)
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.ERROR,
        )
        self.assertEqual(
            state.message_id,
            "message-123",
        )

        cleanup_claimed = (
            await self.repository.claim_deactivation(
                trigger.trigger_id
            )
        )

        self.assertTrue(cleanup_claimed)


if __name__ == "__main__":
    unittest.main()