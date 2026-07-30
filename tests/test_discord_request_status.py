import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.request_status import (
    DiscordRequestStatusController,
    build_request_status_embed,
)
from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    TwitchAccount,
)


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = None

    async def defer(self, **kwargs) -> None:
        self.deferred = kwargs


class FakeInteraction:
    def __init__(self, user_id: int) -> None:
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeResponse()
        self.edits = []

    async def edit_original_response(
        self,
        **kwargs,
    ) -> None:
        self.edits.append(kwargs)


class FakeRequestRepository:
    def __init__(self, request) -> None:
        self.request = request
        self.requested_discord_ids = []

    async def get_latest_for_discord(
        self,
        discord_user_id,
    ):
        self.requested_discord_ids.append(
            discord_user_id
        )
        return self.request


class FakeIdentityRepository:
    def __init__(self, account) -> None:
        self.account = account

    async def get_twitch_account(
        self,
        twitch_user_id,
    ):
        return self.account


class FakePanelRepository:
    def __init__(self, panel=None) -> None:
        self.panel = panel

    async def get_for_broadcaster(
        self,
        twitch_user_id,
    ):
        return self.panel


def make_request(
    status: BroadcasterRequestStatus,
    *,
    decision_reason: str | None = None,
) -> BroadcasterRequest:
    return BroadcasterRequest(
        request_id=7,
        twitch_user_id="456",
        discord_user_id="123",
        status=status,
        requester_message="Please add my channel.",
        decision_reason=decision_reason,
        created_at="2026-07-30 12:00:00",
    )


class DiscordRequestStatusTests(
    unittest.IsolatedAsyncioTestCase
):
    def test_reauthorization_embed_has_safe_action(
        self,
    ) -> None:
        embed = build_request_status_embed(
            make_request(
                BroadcasterRequestStatus
                .REAUTHORIZATION_REQUIRED
            ),
            TwitchAccount(
                twitch_user_id="456",
                login="example_streamer",
                display_name="Example Streamer",
            ),
            panel_channel_id="999",
        )

        rendered = " ".join(
            str(field.value)
            for field in embed.fields
        )

        self.assertIn("Reconnect Twitch", rendered)
        self.assertIn("<#999>", rendered)
        self.assertIn("example_streamer", rendered)

    def test_rejection_embed_shows_requester_message(
        self,
    ) -> None:
        embed = build_request_status_embed(
            make_request(
                BroadcasterRequestStatus.REJECTED,
                decision_reason=(
                    "Testing capacity is currently full."
                ),
            ),
            None,
        )

        rendered = " ".join(
            str(field.value)
            for field in embed.fields
        )

        self.assertIn(
            "Testing capacity is currently full.",
            rendered,
        )

    async def test_controller_uses_interaction_user_id(
        self,
    ) -> None:
        request = make_request(
            BroadcasterRequestStatus.ACTIVE
        )
        request_repository = FakeRequestRepository(
            request
        )
        controller = DiscordRequestStatusController(
            request_repository=request_repository,
            identity_repository=(
                FakeIdentityRepository(
                    TwitchAccount(
                        twitch_user_id="456",
                        login="example_streamer",
                        display_name="Example Streamer",
                    )
                )
            ),
            panel_repository=FakePanelRepository(
                SimpleNamespace(
                    discord_channel_id="999"
                )
            ),
        )
        interaction = FakeInteraction(user_id=123)

        await controller.handle_status(interaction)

        self.assertEqual(
            request_repository.requested_discord_ids,
            ["123"],
        )
        self.assertTrue(
            interaction.response.deferred["ephemeral"]
        )
        self.assertIsNotNone(
            interaction.edits[-1]["embed"]
        )

    async def test_controller_handles_no_request(
        self,
    ) -> None:
        controller = DiscordRequestStatusController(
            request_repository=FakeRequestRepository(None),
            identity_repository=FakeIdentityRepository(
                None
            ),
            panel_repository=FakePanelRepository(),
        )
        interaction = FakeInteraction(user_id=123)

        await controller.handle_status(interaction)

        self.assertIn(
            "do not have",
            interaction.edits[-1]["content"],
        )


if __name__ == "__main__":
    unittest.main()
