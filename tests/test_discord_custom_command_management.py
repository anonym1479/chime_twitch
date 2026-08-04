import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.broadcaster_panel import (
    CUSTOM_COMMANDS_BUTTON_CUSTOM_ID,
    BroadcasterManagementView,
)
from chimebuddy.discord_admin.custom_command_management import (
    COMMANDS_PER_PAGE,
    CustomCommandListView,
    DiscordCustomCommandManagementController,
    build_command_list_embed,
    commands_for_page,
    parse_cooldown,
    parse_permission,
)
from chimebuddy.models import (
    BroadcasterRequestStatus,
    CustomCommand,
    CustomCommandPermission,
)
from chimebuddy.services import (
    CustomCommandValidationError,
)


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

    async def edit_original_response(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeStatusService:
    def __init__(self, status) -> None:
        self.status = status

    async def get_for_broadcaster(self, twitch_user_id):
        return self.status


class FakeManagementService:
    def __init__(self, commands=None) -> None:
        self.commands = list(commands or [])
        self.created_kwargs = None

    async def list_commands(self, twitch_user_id):
        return list(self.commands)

    async def create_command(self, twitch_user_id, **kwargs):
        self.created_kwargs = {
            "twitch_user_id": twitch_user_id,
            **kwargs,
        }
        command = CustomCommand(
            command_id=len(self.commands) + 1,
            broadcaster_twitch_user_id=twitch_user_id,
            **kwargs,
        )
        self.commands.append(command)
        return command


def make_command(index: int) -> CustomCommand:
    return CustomCommand(
        command_id=index,
        broadcaster_twitch_user_id="456",
        name=f"command-{index}",
        response_message=f"Response {index}",
        permission=CustomCommandPermission.EVERYONE,
        cooldown_seconds=30,
    )


class DiscordCustomCommandManagementTests(unittest.TestCase):
    def test_parses_permission_and_cooldown(self) -> None:
        self.assertEqual(
            parse_permission(" Subscriber "),
            CustomCommandPermission.SUBSCRIBER,
        )
        self.assertEqual(parse_cooldown(" 45 "), 45)

        with self.assertRaises(CustomCommandValidationError):
            parse_permission("follower")

        with self.assertRaises(CustomCommandValidationError):
            parse_cooldown("soon")

    def test_second_page_contains_remaining_commands(self) -> None:
        commands = [make_command(index) for index in range(1, 51)]

        self.assertEqual(
            len(commands_for_page(commands, 0)),
            COMMANDS_PER_PAGE,
        )
        self.assertEqual(
            commands_for_page(commands, 1)[0].command_id,
            26,
        )

    def test_embed_fits_with_fifty_commands(self) -> None:
        status = SimpleNamespace(twitch_login="example_streamer")
        commands = [make_command(index) for index in range(1, 51)]
        embed = build_command_list_embed(
            status,
            commands,
            selected_command_id=50,
            page=1,
        )

        self.assertLessEqual(len(embed), 6000)
        self.assertIn("page 2/2", embed.fields[0].name)
        self.assertTrue(
            all(len(str(field.value)) <= 1024 for field in embed.fields)
        )
        self.assertIn(
            "_command-50",
            " ".join(str(field.name) for field in embed.fields),
        )

    def test_view_has_page_navigation(self) -> None:
        status = SimpleNamespace(
            twitch_user_id="456",
            owner_discord_user_id="123",
        )
        commands = [make_command(index) for index in range(1, 51)]
        controller = SimpleNamespace(can_manage=lambda *args: True)
        view = CustomCommandListView(
            controller,
            status,
            commands,
            page=1,
        )

        self.assertFalse(view.previous_button.disabled)
        self.assertTrue(view.next_button.disabled)
        select = view.children[-1]
        self.assertEqual(len(select.options), 25)

    def test_broadcaster_panel_has_custom_command_button(self) -> None:
        status = SimpleNamespace(
            twitch_user_id="456",
            broadcaster_enabled=True,
            request_status=BroadcasterRequestStatus.ACTIVE,
        )
        view = BroadcasterManagementView(SimpleNamespace(), status)
        custom_ids = {
            child.custom_id
            for child in view.children
            if getattr(child, "custom_id", None)
        }

        self.assertIn(CUSTOM_COMMANDS_BUTTON_CUSTOM_ID, custom_ids)


class DiscordCustomCommandControllerTests(
    unittest.IsolatedAsyncioTestCase
):
    def build_status(self):
        return SimpleNamespace(
            twitch_user_id="456",
            twitch_login="example_streamer",
            owner_discord_user_id="123",
        )

    async def test_show_commands_uses_private_controls(self) -> None:
        controller = DiscordCustomCommandManagementController(
            management_service=FakeManagementService([make_command(1)]),
            status_service=FakeStatusService(self.build_status()),
            developer_discord_user_id=999,
        )
        interaction = FakeInteraction()

        await controller.show_commands(interaction, "456")

        self.assertTrue(interaction.response.deferred["ephemeral"])
        self.assertIsInstance(
            interaction.edits[0]["view"],
            CustomCommandListView,
        )

    async def test_create_command_uses_modal_values(self) -> None:
        service = FakeManagementService()
        controller = DiscordCustomCommandManagementController(
            management_service=service,
            status_service=FakeStatusService(self.build_status()),
            developer_discord_user_id=999,
        )
        interaction = FakeInteraction()

        await controller.create_command(
            interaction,
            twitch_user_id="456",
            name="rules",
            response_message="Please read the rules.",
            permission_text="subscriber",
            cooldown_text="60",
        )

        self.assertEqual(
            service.created_kwargs["permission"],
            CustomCommandPermission.SUBSCRIBER,
        )
        self.assertEqual(service.created_kwargs["cooldown_seconds"], 60)
        self.assertIn("was created", interaction.edits[0]["content"])

    async def test_other_user_cannot_open_commands(self) -> None:
        controller = DiscordCustomCommandManagementController(
            management_service=FakeManagementService(),
            status_service=FakeStatusService(self.build_status()),
            developer_discord_user_id=999,
        )
        interaction = FakeInteraction(user_id=555)

        await controller.show_commands(interaction, "456")

        self.assertIn(
            "cannot manage",
            interaction.edits[0]["content"],
        )


if __name__ == "__main__":
    unittest.main()
