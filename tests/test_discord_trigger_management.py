import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.broadcaster_panel import (
    TITLE_TRIGGERS_BUTTON_CUSTOM_ID,
    BroadcasterManagementView,
)
from chimebuddy.discord_admin.trigger_management import (
    AddTriggerModal,
    DiscordTriggerManagementController,
    TriggerListView,
    build_trigger_list_embed,
    parse_match_type,
    parse_pin_message,
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


class FakeInteractionResponse:
    def __init__(self) -> None:
        self.deferred = None
        self.messages = []
        self.modals = []

    async def defer(self, **kwargs) -> None:
        self.deferred = kwargs

    async def send_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))

    async def send_modal(self, modal) -> None:
        self.modals.append(modal)


class FakeInteraction:
    def __init__(self, user_id=123) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeInteractionResponse()
        self.edits = []
        self.message = None

    async def edit_original_response(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeStatusService:
    def __init__(self, status) -> None:
        self.status = status
        self.loaded_ids = []

    async def get_for_broadcaster(self, twitch_user_id):
        self.loaded_ids.append(twitch_user_id)
        return self.status


class FakeManagementService:
    def __init__(self, triggers=None) -> None:
        self.triggers = list(triggers or [])
        self.created_kwargs = None

    async def list_triggers(self, twitch_user_id):
        return list(self.triggers)

    async def create_trigger(self, twitch_user_id, **kwargs):
        self.created_kwargs = {
            "twitch_user_id": twitch_user_id,
            **kwargs,
        }
        trigger = Trigger(
            trigger_id=2,
            broadcaster_twitch_user_id=twitch_user_id,
            name=kwargs["name"].strip(),
            expression=kwargs["expression"].strip(),
            response_message=(
                kwargs["response_message"].strip()
            ),
            match_type=kwargs["match_type"],
            priority=kwargs["priority"],
            pin_message=kwargs["pin_message"],
            enabled=kwargs["enabled"],
        )
        self.triggers.append(trigger)
        return trigger


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

    def test_parses_pin_message(self) -> None:
        self.assertTrue(parse_pin_message(" Yes "))
        self.assertFalse(parse_pin_message("no"))

        with self.assertRaises(
            TriggerValidationError
        ):
            parse_pin_message("maybe")

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
            selected_trigger_id=1,
        )

        rendered = " ".join(
            str(field.value)
            for field in embed.fields
        )

        self.assertIn("solo", rendered)
        self.assertIn("Solo is active.", rendered)
        self.assertIn("Pin message: `Yes`", rendered)

    def test_add_modal_asks_about_pinning(
        self,
    ) -> None:
        modal = AddTriggerModal(
            SimpleNamespace(),
            "456",
        )
        labels = {
            child.to_component_dict()["label"]
            for child in modal.children
        }

        self.assertIn(
            "Pin response? yes or no",
            labels,
        )
        self.assertFalse(
            any(
                "Priority" in label
                for label in labels
            )
        )

    def test_embed_fits_discord_limit_with_25_triggers(
        self,
    ) -> None:
        status = SimpleNamespace(
            twitch_login="example_streamer"
        )
        triggers = [
            Trigger(
                trigger_id=index,
                broadcaster_twitch_user_id="456",
                name=f"Trigger {index} " + "n" * 35,
                expression="expression " + "x" * 180,
                response_message="r" * 450,
                priority=index,
            )
            for index in range(1, 26)
        ]

        embed = build_trigger_list_embed(
            status,
            triggers,
            selected_trigger_id=25,
        )

        self.assertLessEqual(len(embed), 6000)
        self.assertLessEqual(len(embed.fields), 25)

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

        selected_fields = [
            field
            for field in embed.fields
            if "Selected trigger" in field.name
        ]

        self.assertEqual(
            len(selected_fields),
            1,
        )
        self.assertIn(
            "Solo Mode",
            selected_fields[0].name,
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


class DiscordTriggerManagementControllerTests(
    unittest.IsolatedAsyncioTestCase
):
    def build_status(self):
        return SimpleNamespace(
            twitch_user_id="456",
            twitch_login="example_streamer",
            owner_discord_user_id="123",
        )

    async def test_show_triggers_lists_private_controls(
        self,
    ) -> None:
        trigger = Trigger(
            trigger_id=1,
            broadcaster_twitch_user_id="456",
            name="Solo Mode",
            expression="solo",
            response_message="Solo is active.",
        )
        controller = DiscordTriggerManagementController(
            management_service=FakeManagementService(
                [trigger]
            ),
            status_service=FakeStatusService(
                self.build_status()
            ),
            developer_discord_user_id=999,
        )
        interaction = FakeInteraction(user_id=123)

        await controller.show_triggers(
            interaction,
            "456",
        )

        self.assertTrue(
            interaction.response.deferred["ephemeral"]
        )
        self.assertEqual(len(interaction.edits), 1)
        self.assertIn(
            "Title triggers",
            interaction.edits[0]["embed"].title,
        )
        self.assertIsInstance(
            interaction.edits[0]["view"],
            TriggerListView,
        )

    async def test_create_trigger_uses_discord_input(
        self,
    ) -> None:
        management_service = FakeManagementService()
        controller = DiscordTriggerManagementController(
            management_service=management_service,
            status_service=FakeStatusService(
                self.build_status()
            ),
            developer_discord_user_id=999,
        )
        interaction = FakeInteraction(user_id=123)

        await controller.create_trigger(
            interaction,
            twitch_user_id="456",
            name=" Solo Mode ",
            expression=" solo ",
            response_message=" Solo is active. ",
            match_type_text="contains",
            pin_message_text="no",
        )

        self.assertEqual(
            management_service.created_kwargs[
                "match_type"
            ],
            TriggerMatchType.CONTAINS,
        )
        self.assertEqual(
            management_service.created_kwargs[
                "priority"
            ],
            100,
        )
        self.assertFalse(
            management_service.created_kwargs[
                "pin_message"
            ]
        )
        self.assertIn(
            "was created",
            interaction.edits[0]["content"],
        )
        self.assertIsInstance(
            interaction.edits[0]["view"],
            TriggerListView,
        )


if __name__ == "__main__":
    unittest.main()
