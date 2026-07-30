import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chimebuddy.database import Database
from chimebuddy.discord_admin.review import (
    DiscordReviewController,
    RETRY_PROVISIONING_BUTTON_CUSTOM_ID,
    RetryProvisioningView,
    build_review_embed,
)
from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AppSettingsRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)
from chimebuddy.services import (
    ReviewDecisionService,
)


class FakeChannel:
    def __init__(self) -> None:
        self.id = 2000
        self.guild = SimpleNamespace(id=1000)
        self.sent_messages = []
        self.message = FakeMessage()

    async def send(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(id=3000)

    async def fetch_message(self, message_id):
        return self.message


class FakeClient:
    def __init__(self, channel) -> None:
        self.channel = channel
        self.added_views = []

    def get_channel(self, channel_id):
        if channel_id == self.channel.id:
            return self.channel

        return None

    def add_view(self, view, *, message_id):
        self.added_views.append(
            (view, message_id)
        )


class FakeMessage:
    def __init__(self) -> None:
        self.edits = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeUser:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))


class FakeInteractionResponse:
    def __init__(self) -> None:
        self.deferred = None
        self.messages = []

    async def defer(self, **kwargs) -> None:
        self.deferred = kwargs

    async def send_message(
        self,
        *args,
        **kwargs,
    ) -> None:
        self.messages.append((args, kwargs))


class FakeInteraction:
    def __init__(self, user_id=999) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeInteractionResponse()
        self.message = FakeMessage()
        self.notified_user = FakeUser()
        self.client = SimpleNamespace(
            get_user=lambda user_id: self.notified_user
        )
        self.edits = []

    async def edit_original_response(
        self,
        **kwargs,
    ) -> None:
        self.edits.append(kwargs)


class FakeProvisioningService:
    def __init__(self, request_repository) -> None:
        self.request_repository = request_repository
        self.calls = []

    async def provision(
        self,
        request_id,
        *,
        actor_discord_user_id,
    ):
        self.calls.append(
            (request_id, actor_discord_user_id)
        )

        await self.request_repository.transition(
            request_id,
            expected_statuses=(
                BroadcasterRequestStatus
                .PROVISIONING_FAILED,
            ),
            new_status=BroadcasterRequestStatus.ACTIVE,
            event_type="test_retry_completed",
            actor_discord_user_id=(
                actor_discord_user_id
            ),
        )

        return SimpleNamespace(
            discord_channel_id="2000"
        )


class DiscordReviewTests(
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
        self.request_repository = (
            BroadcasterRequestRepository(
                self.database
            )
        )
        self.settings_repository = (
            AppSettingsRepository(
                self.database
            )
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

        self.request = (
            await self.request_repository.create(
                BroadcasterRequest(
                    twitch_user_id="456",
                    discord_user_id="123",
                    requester_message="Please add me.",
                )
            )
        )

        self.controller = DiscordReviewController(
            settings_repository=(
                self.settings_repository
            ),
            request_repository=(
                self.request_repository
            ),
            identity_repository=(
                self.identity_repository
            ),
            decision_service=(
                ReviewDecisionService(
                    self.request_repository
                )
            ),
            developer_discord_user_id=999,
        )

    async def test_embed_contains_identity_details(
        self,
    ) -> None:
        twitch_account = (
            await self.identity_repository
            .get_twitch_account("456")
        )
        discord_account = (
            await self.identity_repository
            .get_discord_account("123")
        )

        embed = build_review_embed(
            self.request,
            twitch_account,
            discord_account,
        )

        rendered_fields = " ".join(
            str(field.value)
            for field in embed.fields
        )

        self.assertIn(
            "example_streamer",
            rendered_fields,
        )
        self.assertIn(
            "123",
            rendered_fields,
        )

    async def test_publish_saves_message_location(
        self,
    ) -> None:
        await self.settings_repository.set(
            "discord.review_channel_id",
            "2000",
        )

        channel = FakeChannel()
        client = FakeClient(channel)

        posted = await self.controller.publish_request(
            client,
            self.request,
        )

        updated = await self.request_repository.get(
            self.request.request_id
        )

        self.assertTrue(posted)
        self.assertEqual(
            len(channel.sent_messages),
            1,
        )
        self.assertIsNotNone(
            channel.sent_messages[0]["view"]
        )
        self.assertEqual(
            updated.review_guild_id,
            "1000",
        )
        self.assertEqual(
            updated.review_channel_id,
            "2000",
        )
        self.assertEqual(
            updated.review_message_id,
            "3000",
        )

    async def test_failed_request_has_retry_view(
        self,
    ) -> None:
        await self.request_repository.transition(
            self.request.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus
                .PROVISIONING_FAILED
            ),
            event_type="test_provisioning_failed",
        )

        failed_request = (
            await self.request_repository.get(
                self.request.request_id
            )
        )
        view = self.controller.create_view_for_request(
            failed_request
        )

        self.assertIsInstance(
            view,
            RetryProvisioningView,
        )
        custom_ids = {
            child.custom_id
            for child in view.children
        }
        self.assertIn(
            RETRY_PROVISIONING_BUTTON_CUSTOM_ID,
            custom_ids,
        )
        self.assertIsNone(view.timeout)

    async def test_retry_updates_request_and_review_message(
        self,
    ) -> None:
        await self.request_repository.transition(
            self.request.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus
                .PROVISIONING_FAILED
            ),
            event_type="test_provisioning_failed",
        )

        provisioning_service = FakeProvisioningService(
            self.request_repository
        )
        self.controller.provisioning_service = (
            provisioning_service
        )
        interaction = FakeInteraction()

        await self.controller.handle_retry_provisioning(
            interaction,
            self.request.request_id,
        )

        updated = await self.request_repository.get(
            self.request.request_id
        )

        self.assertEqual(
            updated.status,
            BroadcasterRequestStatus.ACTIVE,
        )
        self.assertEqual(
            provisioning_service.calls,
            [(self.request.request_id, "999")],
        )
        self.assertIsNone(
            interaction.message.edits[-1]["view"]
        )
        self.assertIn(
            "now active",
            interaction.edits[-1]["content"],
        )

    async def test_retry_is_developer_only(
        self,
    ) -> None:
        view = RetryProvisioningView(
            self.controller,
            self.request.request_id,
        )
        interaction = FakeInteraction(user_id=123)

        allowed = await view.interaction_check(
            interaction
        )

        self.assertFalse(allowed)
        self.assertTrue(
            interaction.response.messages[-1][1][
                "ephemeral"
            ]
        )

    async def test_retry_view_is_restored_after_restart(
        self,
    ) -> None:
        await self.request_repository.set_review_message(
            self.request.request_id,
            guild_id="1000",
            channel_id="2000",
            message_id="3000",
        )
        await self.request_repository.transition(
            self.request.request_id,
            expected_statuses=(
                BroadcasterRequestStatus.PENDING,
            ),
            new_status=(
                BroadcasterRequestStatus
                .PROVISIONING_FAILED
            ),
            event_type="test_provisioning_failed",
        )

        channel = FakeChannel()
        client = FakeClient(channel)

        restored = (
            await self.controller
            .restore_review_messages(client)
        )

        self.assertEqual(restored, 1)
        self.assertEqual(len(client.added_views), 1)
        self.assertIsInstance(
            client.added_views[0][0],
            RetryProvisioningView,
        )
        self.assertEqual(
            client.added_views[0][1],
            3000,
        )


if __name__ == "__main__":
    unittest.main()
