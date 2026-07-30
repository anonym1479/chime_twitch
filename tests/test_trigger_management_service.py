import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    DiscordAccount,
    TriggerMatchType,
    TwitchAccount,
)
from chimebuddy.repositories import (
    IdentityRepository,
    TriggerRepository,
)
from chimebuddy.services import (
    ManagedTriggerNotFoundError,
    TriggerBusyError,
    TriggerLimitReachedError,
    TriggerManagementService,
    TriggerNameConflictError,
    TriggerValidationError,
)


class TriggerManagementServiceTests(
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
        self.trigger_repository = TriggerRepository(
            self.database
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
            )
        )

        self.service = TriggerManagementService(
            trigger_repository=(
                self.trigger_repository
            ),
            identity_repository=(
                self.identity_repository
            ),
        )

    async def create_trigger(self):
        return await self.service.create_trigger(
            "456",
            name="Solo Mode",
            expression="solo",
            response_message=(
                "The streamer is playing solo."
            ),
        )

    async def activate_trigger(
        self,
        trigger_id: int,
    ) -> None:
        claimed = (
            await self.trigger_repository
            .claim_activation(
                trigger_id,
                "Ranked solo gameplay",
            )
        )

        self.assertTrue(claimed)

        completed = (
            await self.trigger_repository
            .complete_activation(
                trigger_id,
                "message-123",
                is_pinned=True,
            )
        )

        self.assertTrue(completed)

    async def test_creates_and_lists_trigger(
        self,
    ) -> None:
        created = await self.service.create_trigger(
            "456",
            name="  Solo Mode  ",
            expression="  solo  ",
            response_message="  Solo is active.  ",
            match_type=TriggerMatchType.CONTAINS,
            priority=25,
        )

        triggers = await self.service.list_triggers(
            "456"
        )

        self.assertEqual(len(triggers), 1)
        self.assertEqual(
            created.name,
            "Solo Mode",
        )
        self.assertEqual(
            created.expression,
            "solo",
        )
        self.assertEqual(
            created.response_message,
            "Solo is active.",
        )
        self.assertEqual(created.priority, 25)

    async def test_duplicate_name_is_translated(
        self,
    ) -> None:
        await self.create_trigger()

        with self.assertRaises(
            TriggerNameConflictError
        ):
            await self.service.create_trigger(
                "456",
                name="solo mode",
                expression="different",
                response_message="Different message.",
            )

    async def test_trigger_limit_is_enforced(
        self,
    ) -> None:
        limited_service = TriggerManagementService(
            trigger_repository=(
                self.trigger_repository
            ),
            identity_repository=(
                self.identity_repository
            ),
            max_triggers=1,
        )

        await self.create_trigger()

        with self.assertRaises(
            TriggerLimitReachedError
        ):
            await limited_service.create_trigger(
                "456",
                name="Second trigger",
                expression="second",
                response_message="Second message.",
            )

    async def test_invalid_input_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            TriggerValidationError
        ):
            await self.service.create_trigger(
                "456",
                name=" ",
                expression="solo",
                response_message="Message.",
            )

        with self.assertRaises(
            TriggerValidationError
        ):
            await self.service.create_trigger(
                "456",
                name="Valid name",
                expression="solo",
                response_message="x" * 451,
            )

    async def test_other_broadcaster_cannot_access_trigger(
        self,
    ) -> None:
        trigger = await self.create_trigger()

        with self.assertRaises(
            ManagedTriggerNotFoundError
        ):
            await self.service.set_enabled(
                "different-broadcaster",
                trigger.trigger_id,
                False,
            )

        stored = (
            await self.trigger_repository.get_trigger(
                trigger.trigger_id
            )
        )

        self.assertTrue(stored.enabled)

    async def test_active_trigger_cannot_be_edited(
        self,
    ) -> None:
        trigger = await self.create_trigger()
        await self.activate_trigger(
            trigger.trigger_id
        )

        with self.assertRaises(
            TriggerBusyError
        ):
            await self.service.update_trigger(
                "456",
                trigger.trigger_id,
                name="Edited Trigger",
                expression="edited",
                response_message="Edited message.",
                match_type=TriggerMatchType.CONTAINS,
                pin_message=True,
                priority=100,
                enabled=True,
            )

    async def test_active_trigger_cannot_be_deleted(
        self,
    ) -> None:
        trigger = await self.create_trigger()
        await self.activate_trigger(
            trigger.trigger_id
        )

        with self.assertRaises(
            TriggerBusyError
        ):
            await self.service.delete_trigger(
                "456",
                trigger.trigger_id,
            )

        stored = (
            await self.trigger_repository.get_trigger(
                trigger.trigger_id
            )
        )

        self.assertIsNotNone(stored)

    async def test_active_trigger_can_be_disabled(
        self,
    ) -> None:
        trigger = await self.create_trigger()
        await self.activate_trigger(
            trigger.trigger_id
        )

        updated = await self.service.set_enabled(
            "456",
            trigger.trigger_id,
            False,
        )

        self.assertFalse(updated.enabled)

        state = (
            await self.trigger_repository
            .get_runtime_state(trigger.trigger_id)
        )

        # Twitch cleanup happens asynchronously in the
        # title monitor, so the state is still active here.
        self.assertEqual(
            state.status.value,
            "active",
        )

    async def test_inactive_trigger_can_be_updated(
        self,
    ) -> None:
        trigger = await self.create_trigger()

        updated = await self.service.update_trigger(
            "456",
            trigger.trigger_id,
            name="Ranked Solo",
            expression="ranked solo",
            response_message=(
                "Ranked solo mode is active."
            ),
            match_type=TriggerMatchType.EXACT,
            pin_message=False,
            priority=10,
            enabled=True,
        )

        self.assertEqual(
            updated.name,
            "Ranked Solo",
        )
        self.assertEqual(
            updated.match_type,
            TriggerMatchType.EXACT,
        )
        self.assertFalse(updated.pin_message)
        self.assertEqual(updated.priority, 10)

    async def test_inactive_trigger_can_be_deleted(
        self,
    ) -> None:
        trigger = await self.create_trigger()

        await self.service.delete_trigger(
            "456",
            trigger.trigger_id,
        )

        stored = (
            await self.trigger_repository.get_trigger(
                trigger.trigger_id
            )
        )
        state = (
            await self.trigger_repository
            .get_runtime_state(trigger.trigger_id)
        )

        self.assertIsNone(stored)
        self.assertIsNone(state)


if __name__ == "__main__":
    unittest.main()