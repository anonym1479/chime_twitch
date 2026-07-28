import unittest

from chimebuddy.models import (
    Trigger,
    TriggerRuntimeState,
    TriggerRuntimeStatus,
)
from chimebuddy.services import (
    TriggerAction,
    TriggerStateMachine,
)


class TriggerStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = TriggerStateMachine()

    @staticmethod
    def create_trigger(
        *,
        enabled: bool = True,
        trigger_id: int = 1,
    ) -> Trigger:
        return Trigger(
            trigger_id=trigger_id,
            broadcaster_twitch_user_id="211164044",
            name="Solo Mode",
            expression="solo",
            response_message="Solo mode is active.",
            enabled=enabled,
        )

    @staticmethod
    def create_state(
        status: TriggerRuntimeStatus,
        *,
        trigger_id: int = 1,
        message_id: str | None = None,
    ) -> TriggerRuntimeState:
        return TriggerRuntimeState(
            trigger_id=trigger_id,
            status=status,
            last_title=None,
            message_id=message_id,
            is_pinned=message_id is not None,
            activated_at=None,
            operation_started_at=None,
            updated_at="2026-01-01 00:00:00",
            last_error=None,
        )

    def test_inactive_match_activates(self) -> None:
        decision = self.machine.decide(
            self.create_trigger(),
            self.create_state(
                TriggerRuntimeStatus.INACTIVE
            ),
            title_matches=True,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.ACTIVATE,
        )
        self.assertTrue(decision.requires_action)

    def test_active_match_does_nothing(self) -> None:
        decision = self.machine.decide(
            self.create_trigger(),
            self.create_state(
                TriggerRuntimeStatus.ACTIVE,
                message_id="message-123",
            ),
            title_matches=True,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.NONE,
        )

    def test_active_non_match_deactivates(self) -> None:
        decision = self.machine.decide(
            self.create_trigger(),
            self.create_state(
                TriggerRuntimeStatus.ACTIVE,
                message_id="message-123",
            ),
            title_matches=False,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.DEACTIVATE,
        )

    def test_disabling_active_trigger_deactivates(
        self,
    ) -> None:
        decision = self.machine.decide(
            self.create_trigger(enabled=False),
            self.create_state(
                TriggerRuntimeStatus.ACTIVE,
                message_id="message-123",
            ),
            title_matches=True,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.DEACTIVATE,
        )

    def test_disabled_inactive_trigger_does_nothing(
        self,
    ) -> None:
        decision = self.machine.decide(
            self.create_trigger(enabled=False),
            self.create_state(
                TriggerRuntimeStatus.INACTIVE
            ),
            title_matches=True,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.NONE,
        )

    def test_operation_in_progress_does_nothing(
        self,
    ) -> None:
        for status in (
            TriggerRuntimeStatus.ACTIVATING,
            TriggerRuntimeStatus.DEACTIVATING,
        ):
            with self.subTest(status=status):
                decision = self.machine.decide(
                    self.create_trigger(),
                    self.create_state(status),
                    title_matches=True,
                )

                self.assertEqual(
                    decision.action,
                    TriggerAction.NONE,
                )

    def test_error_with_message_requests_cleanup(
        self,
    ) -> None:
        decision = self.machine.decide(
            self.create_trigger(),
            self.create_state(
                TriggerRuntimeStatus.ERROR,
                message_id="message-123",
            ),
            title_matches=True,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.DEACTIVATE,
        )

    def test_error_without_message_resets(self) -> None:
        decision = self.machine.decide(
            self.create_trigger(),
            self.create_state(
                TriggerRuntimeStatus.ERROR
            ),
            title_matches=True,
        )

        self.assertEqual(
            decision.action,
            TriggerAction.RESET_ERROR,
        )

    def test_mismatched_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "IDs do not match",
        ):
            self.machine.decide(
                self.create_trigger(trigger_id=1),
                self.create_state(
                    TriggerRuntimeStatus.INACTIVE,
                    trigger_id=2,
                ),
                title_matches=True,
            )


if __name__ == "__main__":
    unittest.main()