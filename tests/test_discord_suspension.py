import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.suspension import (
    DiscordBroadcasterSuspensionController,
    SuspensionConfirmationView,
)
from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    TwitchAccount,
)


class FakeResponse:
    def __init__(self) -> None:
        self.messages = []
        self.deferred = None

    async def send_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))

    async def defer(self, **kwargs) -> None:
        self.deferred = kwargs


class FakeInteraction:
    def __init__(self, user_id: int = 999) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeResponse()
        self.client = SimpleNamespace()
        self.edits = []

    async def edit_original_response(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeRequestRepository:
    def __init__(self, request) -> None:
        self.request = request
        self.listed_statuses = []

    async def list_by_status(self, statuses):
        self.listed_statuses.append(tuple(statuses))
        if self.request.status in statuses:
            return [self.request]
        return []

    async def get_open_for_twitch(self, twitch_user_id):
        if self.request.twitch_user_id == twitch_user_id:
            return self.request
        return None


class FakeIdentityRepository:
    async def get_twitch_account(self, twitch_user_id):
        if twitch_user_id != "456":
            return None
        return TwitchAccount(
            twitch_user_id="456",
            login="example_streamer",
            display_name="Example Streamer",
        )


class FakeSuspensionService:
    def __init__(self) -> None:
        self.suspend_calls = []
        self.restore_calls = []

    async def suspend(self, request_id, **kwargs):
        self.suspend_calls.append((request_id, kwargs))

    async def restore(self, request_id, **kwargs):
        self.restore_calls.append((request_id, kwargs))


class FakePanelController:
    def __init__(self) -> None:
        self.refresh_calls = []

    async def refresh_stored_panel(self, client, twitch_user_id):
        self.refresh_calls.append((client, twitch_user_id))
        return True


class DiscordSuspensionTests(
    unittest.IsolatedAsyncioTestCase
):
    def create_controller(
        self,
        status: BroadcasterRequestStatus = (
            BroadcasterRequestStatus.ACTIVE
        ),
    ):
        request = BroadcasterRequest(
            request_id=7,
            twitch_user_id="456",
            discord_user_id="123",
            status=status,
        )
        service = FakeSuspensionService()
        panel_controller = FakePanelController()
        repository = FakeRequestRepository(request)
        controller = DiscordBroadcasterSuspensionController(
            suspension_service=service,
            request_repository=repository,
            identity_repository=FakeIdentityRepository(),
            panel_controller=panel_controller,
            developer_discord_user_id=999,
        )
        return controller, service, panel_controller, repository

    async def test_autocomplete_uses_login_label_and_id_value(
        self,
    ) -> None:
        controller, _, _, repository = (
            self.create_controller()
        )

        choices = await controller.autocomplete(
            FakeInteraction(),
            "example",
            status=BroadcasterRequestStatus.ACTIVE,
        )

        self.assertEqual(len(choices), 1)
        self.assertEqual(
            choices[0].name,
            "example_streamer (456)",
        )
        self.assertEqual(choices[0].value, "456")
        self.assertEqual(
            repository.listed_statuses,
            [(BroadcasterRequestStatus.ACTIVE,)],
        )

    def test_command_group_contains_suspend_and_restore(
        self,
    ) -> None:
        controller, _, _, _ = self.create_controller()

        group = controller.create_command_group()
        names = {
            command.name
            for command in group.commands
        }

        self.assertEqual(names, {"suspend", "restore"})
        self.assertTrue(
            group.default_permissions.administrator
        )

    async def test_autocomplete_is_empty_for_non_developer(
        self,
    ) -> None:
        controller, _, _, repository = (
            self.create_controller()
        )

        choices = await controller.autocomplete(
            FakeInteraction(user_id=123),
            "",
            status=BroadcasterRequestStatus.ACTIVE,
        )

        self.assertEqual(choices, [])
        self.assertEqual(repository.listed_statuses, [])

    async def test_suspend_command_requires_developer(
        self,
    ) -> None:
        controller, _, _, _ = self.create_controller()
        interaction = FakeInteraction(user_id=123)

        await controller.prepare_suspend(
            interaction,
            twitch_user_id="456",
            internal_reason="Internal test.",
        )

        self.assertEqual(len(interaction.response.messages), 1)
        self.assertIn(
            "Only the ChimeBuddy developer",
            interaction.response.messages[0][0][0],
        )

    async def test_suspend_command_asks_for_confirmation(
        self,
    ) -> None:
        controller, _, _, _ = self.create_controller()
        interaction = FakeInteraction()

        await controller.prepare_suspend(
            interaction,
            twitch_user_id="456",
            internal_reason="Internal test.",
        )

        _, kwargs = interaction.response.messages[0]
        self.assertIsInstance(
            kwargs["view"],
            SuspensionConfirmationView,
        )
        self.assertTrue(kwargs["ephemeral"])

    async def test_confirmed_suspension_updates_panel(
        self,
    ) -> None:
        controller, service, panel, _ = (
            self.create_controller()
        )
        interaction = FakeInteraction()

        await controller.execute(
            interaction,
            twitch_user_id="456",
            twitch_login="example_streamer",
            internal_reason="Internal test.",
            restore=False,
        )

        self.assertEqual(service.suspend_calls[0][0], 7)
        self.assertEqual(
            service.suspend_calls[0][1]["internal_reason"],
            "Internal test.",
        )
        self.assertEqual(panel.refresh_calls[0][1], "456")
        self.assertIn("was suspended", interaction.edits[0]["content"])

    async def test_restore_autocomplete_only_lists_suspended(
        self,
    ) -> None:
        controller, _, _, _ = self.create_controller(
            BroadcasterRequestStatus.SUSPENDED
        )

        choices = await controller.autocomplete(
            FakeInteraction(),
            "",
            status=BroadcasterRequestStatus.SUSPENDED,
        )

        self.assertEqual([choice.value for choice in choices], ["456"])


if __name__ == "__main__":
    unittest.main()
