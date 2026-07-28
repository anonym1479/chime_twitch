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


if __name__ == "__main__":
    unittest.main()