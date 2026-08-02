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
    TriggerRuntimeStatus,
    TwitchAccount,
)
from chimebuddy.repositories import (
    IdentityRepository,
    TriggerRepository,
)
from chimebuddy.services import (
    TitleTriggerMatcher,
    TriggerCoordinator,
    TriggerStateMachine,
)


class FakeChatGateway:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []

    async def send_message(
        self,
        broadcaster_twitch_user_id: str,
        message: str,
    ) -> str:
        self.sent_messages.append(
            (
                broadcaster_twitch_user_id,
                message,
            )
        )

        return f"message-{len(self.sent_messages)}"


class FakePinGateway:
    def __init__(self) -> None:
        self.pinned: list[tuple[str, str]] = []
        self.unpinned: list[tuple[str, str]] = []
        self.fail_pinning = False

    async def pin_message(
        self,
        broadcaster_twitch_user_id: str,
        message_id: str,
    ) -> None:
        if self.fail_pinning:
            raise RuntimeError("Test pin failure.")

        self.pinned.append(
            (
                broadcaster_twitch_user_id,
                message_id,
            )
        )

    async def unpin_message(
        self,
        broadcaster_twitch_user_id: str,
        message_id: str,
    ) -> None:
        self.unpinned.append(
            (
                broadcaster_twitch_user_id,
                message_id,
            )
        )


class TriggerCoordinatorTests(
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

        self.trigger_repository = TriggerRepository(
            self.database
        )

        self.chat_gateway = FakeChatGateway()
        self.pin_gateway = FakePinGateway()

        self.coordinator = TriggerCoordinator(
            repository=self.trigger_repository,
            matcher=TitleTriggerMatcher(),
            state_machine=TriggerStateMachine(),
            chat_gateway=self.chat_gateway,
            pin_gateway=self.pin_gateway,
        )

    async def create_trigger(
        self,
        *,
        name: str = "Solo Mode",
        expression: str = "solo",
        response_message: str = "Solo mode is active.",
        priority: int = 100,
    ) -> Trigger:
        return await self.trigger_repository.create_trigger(
            Trigger(
                broadcaster_twitch_user_id="211164044",
                name=name,
                expression=expression,
                response_message=response_message,
                priority=priority,
            )
        )

    async def test_matching_title_sends_only_once(
        self,
    ) -> None:
        trigger = await self.create_trigger()

        with self.assertLogs(
            "chimebuddy.twitch.triggers",
            level="INFO",
        ) as captured:
            first_report = (
                await self.coordinator.process_title(
                    "211164044",
                    "Ranked solo gameplay",
                )
            )

        second_report = await self.coordinator.process_title(
            "211164044",
            "Ranked solo gameplay",
        )

        self.assertEqual(
            first_report.activated_trigger_ids,
            (trigger.trigger_id,),
        )
        self.assertEqual(
            second_report.activated_trigger_ids,
            (),
        )
        self.assertEqual(
            len(self.chat_gateway.sent_messages),
            1,
        )
        self.assertEqual(
            len(self.pin_gateway.pinned),
            1,
        )
        rendered_logs = " ".join(captured.output)
        self.assertIn(
            "Title trigger matched",
            rendered_logs,
        )
        self.assertIn(
            "Trigger activated",
            rendered_logs,
        )
        self.assertIn(
            "pinned=True",
            rendered_logs,
        )
        self.assertNotIn(
            "Solo mode is active.",
            rendered_logs,
        )

    async def test_nonmatching_title_unpins_message(
        self,
    ) -> None:
        trigger = await self.create_trigger()

        await self.coordinator.process_title(
            "211164044",
            "Ranked solo gameplay",
        )

        with self.assertLogs(
            "chimebuddy.twitch.triggers",
            level="INFO",
        ) as captured:
            report = await self.coordinator.process_title(
                "211164044",
                "Playing with viewers",
            )

        state = (
            await self.trigger_repository.get_runtime_state(
                trigger.trigger_id
            )
        )

        self.assertEqual(
            report.deactivated_trigger_ids,
            (trigger.trigger_id,),
        )
        self.assertEqual(
            self.pin_gateway.unpinned,
            [
                (
                    "211164044",
                    "message-1",
                )
            ],
        )
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.INACTIVE,
        )
        self.assertIn(
            "reason=title_no_longer_matches",
            " ".join(captured.output),
        )

    async def test_highest_priority_match_is_selected(
        self,
    ) -> None:
        await self.create_trigger(
            name="General Solo",
            expression="solo",
            response_message="General solo message.",
            priority=100,
        )

        selected = await self.create_trigger(
            name="Ranked Solo",
            expression="ranked solo",
            response_message="Ranked solo message.",
            priority=10,
        )

        report = await self.coordinator.process_title(
            "211164044",
            "Ranked solo practice",
        )

        self.assertEqual(
            report.selected_trigger_id,
            selected.trigger_id,
        )
        self.assertEqual(
            self.chat_gateway.sent_messages,
            [
                (
                    "211164044",
                    "Ranked solo message.",
                )
            ],
        )

    async def test_pin_failure_does_not_repeat_message(
        self,
    ) -> None:
        trigger = await self.create_trigger()
        self.pin_gateway.fail_pinning = True

        with self.assertLogs(
            "chimebuddy.twitch.triggers",
            level="WARNING",
        ) as captured:
            first_report = (
                await self.coordinator.process_title(
                    "211164044",
                    "Solo gameplay",
                )
            )

        second_report = await self.coordinator.process_title(
            "211164044",
            "Solo gameplay",
        )

        state = (
            await self.trigger_repository.get_runtime_state(
                trigger.trigger_id
            )
        )

        self.assertEqual(
            len(self.chat_gateway.sent_messages),
            1,
        )
        self.assertEqual(
            first_report.activated_trigger_ids,
            (trigger.trigger_id,),
        )
        self.assertTrue(first_report.errors)
        self.assertEqual(
            second_report.activated_trigger_ids,
            (),
        )
        self.assertEqual(
            state.status,
            TriggerRuntimeStatus.ACTIVE,
        )
        self.assertFalse(state.is_pinned)
        self.assertIn(
            "Trigger pinning failed",
            " ".join(captured.output),
        )


if __name__ == "__main__":
    unittest.main()
