import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.broadcaster_panel import (
    TITLE_TRIGGERS_BUTTON_CUSTOM_ID,
    BroadcasterManagementView,
)
from chimebuddy.discord_admin.trigger_management import (
    TriggerListView,
    build_trigger_list_embed,
    parse_match_type,
    parse_priority,
    parse_trigger_id,
)
from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
)
from chimebuddy.services import (
    TriggerValidationError,
)


class FakeTriggerController:
    def can_manage(self, discord_user_id, status):
        return True


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

    def test_parses_trigger_id(self) -> None:
        self.assertEqual(parse_trigger_id(" 42 "), 42)

        with self.assertRaises(
            TriggerValidationError
        ):
            parse_trigger_id("0")

        with self.assertRaises(
            TriggerValidationError
        ):
            parse_trigger_id("abc")

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

    def test_embed_marks_selected_trigger(
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
        )

        embed = build_trigger_list_embed(
            status,
            [trigger],
            selected_trigger_id=1,
        )

        self.assertIn(
            "Selected",
            embed.fields[0].name,
        )

    def test_view_disables_trigger_actions_without_selection(
        self,
    ) -> None:
        status = SimpleNamespace(
            twitch_user_id="456",
            owner_discord_user_id="123",
        )
        trigger = Trigger(
            trigger_id=1,
            broadcaster_twitch_user_id="456",
            name="Solo Mode",
            expression="solo",
            response_message="Solo is active.",
        )

        view = TriggerListView(
            FakeTriggerController(),
            status,
            [trigger],
        )

        disabled_labels = {
            child.label
            for child in view.children
            if getattr(child, "disabled", False)
        }

        self.assertIn("Edit", disabled_labels)
        self.assertIn("Disable", disabled_labels)
        self.assertIn("Delete", disabled_labels)

    def test_view_enables_selected_disabled_trigger(
        self,
    ) -> None:
        status = SimpleNamespace(
            twitch_user_id="456",
            owner_discord_user_id="123",
        )
        trigger = Trigger(
            trigger_id=1,
            broadcaster_twitch_user_id="456",
            name="Solo Mode",
            expression="solo",
            response_message="Solo is active.",
            enabled=False,
        )

        view = TriggerListView(
            FakeTriggerController(),
            status,
            [trigger],
            selected_trigger_id=1,
        )

        toggle = next(
            child
            for child in view.children
            if getattr(child, "label", None) == "Enable"
        )

        self.assertFalse(toggle.disabled)

    def test_broadcaster_panel_has_title_trigger_button(
        self,
    ) -> None:
        status = SimpleNamespace(
            twitch_user_id="456",
            broadcaster_enabled=True,
        )
        controller = SimpleNamespace()

        view = BroadcasterManagementView(
            controller,
            status,
        )

        custom_ids = {
            child.custom_id
            for child in view.children
            if getattr(child, "custom_id", None)
        }

        self.assertIn(
            TITLE_TRIGGERS_BUTTON_CUSTOM_ID,
            custom_ids,
        )


if __name__ == "__main__":
    unittest.main()