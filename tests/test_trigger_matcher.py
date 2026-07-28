import unittest

from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
)
from chimebuddy.services import TitleTriggerMatcher


class TitleTriggerMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = TitleTriggerMatcher()

    @staticmethod
    def create_trigger(
        *,
        name: str = "Solo Mode",
        expression: str = "solo",
        match_type: TriggerMatchType = (
            TriggerMatchType.CONTAINS
        ),
        priority: int = 100,
        enabled: bool = True,
        trigger_id: int | None = 1,
    ) -> Trigger:
        return Trigger(
            trigger_id=trigger_id,
            broadcaster_twitch_user_id="211164044",
            name=name,
            expression=expression,
            response_message="Test response.",
            match_type=match_type,
            priority=priority,
            enabled=enabled,
        )

    def test_contains_match_is_case_insensitive(
        self,
    ) -> None:
        trigger = self.create_trigger(
            expression="SoLo",
        )

        result = self.matcher.evaluate(
            "Ranked SOLO gameplay",
            [trigger],
        )

        self.assertTrue(result.has_match)
        self.assertEqual(
            result.selected_trigger,
            trigger,
        )

    def test_exact_match_ignores_case_and_outer_spaces(
        self,
    ) -> None:
        trigger = self.create_trigger(
            expression="Playing Solo",
            match_type=TriggerMatchType.EXACT,
        )

        result = self.matcher.evaluate(
            "  PLAYING SOLO  ",
            [trigger],
        )

        self.assertTrue(result.has_match)

    def test_exact_does_not_accept_partial_match(
        self,
    ) -> None:
        trigger = self.create_trigger(
            expression="solo",
            match_type=TriggerMatchType.EXACT,
        )

        result = self.matcher.evaluate(
            "Ranked solo gameplay",
            [trigger],
        )

        self.assertFalse(result.has_match)
        self.assertIsNone(result.selected_trigger)

    def test_disabled_trigger_is_ignored(
        self,
    ) -> None:
        trigger = self.create_trigger(
            enabled=False,
        )

        result = self.matcher.evaluate(
            "Solo gameplay",
            [trigger],
        )

        self.assertFalse(result.has_match)

    def test_lowest_priority_number_wins(
        self,
    ) -> None:
        lower_priority = self.create_trigger(
            trigger_id=1,
            name="General Solo",
            expression="solo",
            priority=100,
        )

        higher_priority = self.create_trigger(
            trigger_id=2,
            name="Ranked Solo",
            expression="ranked solo",
            priority=10,
        )

        result = self.matcher.evaluate(
            "Ranked solo practice",
            [
                lower_priority,
                higher_priority,
            ],
        )

        self.assertEqual(
            result.selected_trigger,
            higher_priority,
        )

        self.assertEqual(
            result.matched_triggers,
            (
                higher_priority,
                lower_priority,
            ),
        )

    def test_no_match_returns_empty_result(
        self,
    ) -> None:
        trigger = self.create_trigger(
            expression="solo",
        )

        result = self.matcher.evaluate(
            "Playing with viewers",
            [trigger],
        )

        self.assertFalse(result.has_match)
        self.assertEqual(
            result.matched_triggers,
            (),
        )


if __name__ == "__main__":
    unittest.main()