import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.trigger_management import (
    build_trigger_list_embed,
    parse_match_type,
    parse_priority,
)
from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
)
from chimebuddy.services import (
    TriggerValidationError,
)


class DiscordTriggerManagementTests(
    unittest.TestCase
):
    def test_parses_match_type(self) -> None:
        self.assertEqual(
            parse_match_type(" Contains "),
            TriggerMatchType.CONTAINS,
        )
        self.assertEqual(
            parse_match_type("exact"),
            TriggerMatchType.EXACT,
        )

        with self.assertRaises(
            TriggerValidationError
        ):
            parse_match_type("regex")

    def test_parses_priority(self) -> None:
        self.assertEqual(parse_priority(""), 100)
        self.assertEqual(parse_priority("25"), 25)

        with self.assertRaises(
            TriggerValidationError
        ):
            parse_priority("-1")

        with self.assertRaises(
            TriggerValidationError
        ):
            parse_priority("high")

    def test_empty_embed_explains_add_action(
        self,
    ) -> None:
        status = SimpleNamespace(
            twitch_login="example_streamer"
        )

        embed = build_trigger_list_embed(
            status,
            [],
        )

        self.assertIn(
            "No triggers configured",
            embed.fields[0].name,
        )

    def test_embed_lists_trigger_details(
        self,
    ) -> None:
        status = SimpleNamespace(
            twitch_login="example_streamer"
        )

        trigger = Trigger(
            trigger_id=1,
            broadcaster_twitch_user_id="456",
            name="Solo Mode",
            expression="solo",
            response_message="Solo is active.",
            priority=25,
        )

        embed = build_trigger_list_embed(
            status,
            [trigger],
        )

        rendered = " ".join(
            str(field.value)
            for field in embed.fields
        )

        self.assertIn("solo", rendered)
        self.assertIn("Solo is active.", rendered)
        self.assertIn("25", rendered)


if __name__ == "__main__":
    unittest.main()