import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chimebuddy.database import Database
from chimebuddy.discord_admin.review import (
    DiscordReviewController,
    build_review_embed,
)
from chimebuddy.models import (
    BroadcasterRequest,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AppSettingsRepository,
    BroadcasterRequestRepository,
    IdentityRepository,
)


class FakeChannel:
    def __init__(self) -> None:
        self.id = 2000
        self.guild = SimpleNamespace(id=1000)
        self.sent_messages = []

    async def send(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(id=3000)


class FakeClient:
    def __init__(self, channel) -> None:
        self.channel = channel

    def get_channel(self, channel_id):
        if channel_id == self.channel.id:
            return self.channel

        return None


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


if __name__ == "__main__":
    unittest.main()