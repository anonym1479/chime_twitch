import asyncio
import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    CustomCommand,
    CustomCommandPermission,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.models.chat import (
    TwitchChatBadge,
    TwitchChatMessage,
)
from chimebuddy.repositories import (
    CustomCommandRepository,
    IdentityRepository,
)
from chimebuddy.services import CustomCommandRuntime


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeChatGateway:
    def __init__(self) -> None:
        self.messages = []
        self.fail = False

    async def send_message(
        self,
        broadcaster_twitch_user_id,
        message,
    ):
        if self.fail:
            raise RuntimeError("Simulated send failure.")

        # Yield so concurrent tests exercise the runtime lock.
        await asyncio.sleep(0)
        self.messages.append(
            (broadcaster_twitch_user_id, message)
        )
        return f"message-{len(self.messages)}"


def make_message(
    text: str,
    *,
    broadcaster_id: str = "100",
    chatter_id: str = "500",
    badges=(),
) -> TwitchChatMessage:
    return TwitchChatMessage(
        broadcaster_twitch_user_id=broadcaster_id,
        broadcaster_login=f"streamer_{broadcaster_id}",
        broadcaster_display_name="Streamer",
        chatter_twitch_user_id=chatter_id,
        chatter_login="viewer",
        chatter_display_name="Viewer",
        message_id="message-incoming",
        text=text,
        message_type="text",
        badges=tuple(badges),
    )


class CustomCommandRuntimeTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database = Database(
            Path(self.temp_directory.name) / "test.db"
        )
        await self.database.initialize()

        identity_repository = IdentityRepository(
            self.database
        )

        for twitch_id, discord_id in (
            ("100", "200"),
            ("300", "400"),
        ):
            await identity_repository.save_twitch_account(
                TwitchAccount(
                    twitch_user_id=twitch_id,
                    login=f"streamer_{twitch_id}",
                    display_name=f"Streamer {twitch_id}",
                )
            )
            await identity_repository.save_discord_account(
                DiscordAccount(
                    discord_user_id=discord_id,
                    username=f"user_{discord_id}",
                    display_name=f"User {discord_id}",
                )
            )
            await identity_repository.save_account_link(
                AccountLink(
                    twitch_user_id=twitch_id,
                    discord_user_id=discord_id,
                    status=AccountLinkStatus.VERIFIED,
                    verification_method="test",
                )
            )
            await identity_repository.save_broadcaster(
                Broadcaster(
                    twitch_user_id=twitch_id,
                    owner_discord_user_id=discord_id,
                )
            )

        self.repository = CustomCommandRepository(
            self.database
        )
        self.gateway = FakeChatGateway()
        self.clock = FakeClock()
        self.runtime = CustomCommandRuntime(
            command_repository=self.repository,
            chat_gateway=self.gateway,
            clock=self.clock,
        )

    async def create_command(
        self,
        *,
        name="discord",
        response="Join our Discord.",
        permission=CustomCommandPermission.EVERYONE,
        cooldown=30,
        broadcaster_id="100",
        enabled=True,
    ):
        return await self.repository.create(
            CustomCommand(
                broadcaster_twitch_user_id=broadcaster_id,
                name=name,
                response_message=response,
                permission=permission,
                cooldown_seconds=cooldown,
                enabled=enabled,
            ),
            max_commands=50,
        )

    async def test_executes_enabled_command_with_arguments(
        self,
    ) -> None:
        await self.create_command()

        with self.assertLogs(
            "chimebuddy.twitch.custom_commands",
            level="INFO",
        ) as captured:
            handled = await self.runtime.route(
                make_message("_DISCORD ignored arguments")
            )

        self.assertTrue(handled)
        self.assertEqual(
            self.gateway.messages,
            [("100", "Join our Discord.")],
        )
        rendered_logs = " ".join(captured.output)
        self.assertIn("command executed", rendered_logs)
        self.assertNotIn("Join our Discord", rendered_logs)

    async def test_unknown_and_disabled_are_ignored(
        self,
    ) -> None:
        await self.create_command(enabled=False)

        self.assertFalse(
            await self.runtime.route(
                make_message("normal chat")
            )
        )
        self.assertFalse(
            await self.runtime.route(
                make_message("_unknown")
            )
        )
        self.assertFalse(
            await self.runtime.route(
                make_message("_discord")
            )
        )
        self.assertEqual(self.gateway.messages, [])

    async def test_subscriber_permission_and_hierarchy(
        self,
    ) -> None:
        await self.create_command(
            permission=CustomCommandPermission.SUBSCRIBER,
            cooldown=5,
        )

        with self.assertLogs(
            "chimebuddy.twitch.custom_commands",
            level="INFO",
        ):
            denied = await self.runtime.route(
                make_message("_discord")
            )
        self.assertFalse(denied)

        subscriber_badge = TwitchChatBadge(
            set_id="subscriber",
            badge_id="1",
        )
        self.assertTrue(
            await self.runtime.route(
                make_message(
                    "_discord",
                    badges=(subscriber_badge,),
                )
            )
        )

        self.clock.advance(5)
        vip_badge = TwitchChatBadge(
            set_id="vip",
            badge_id="1",
        )
        self.assertTrue(
            await self.runtime.route(
                make_message(
                    "_discord",
                    badges=(vip_badge,),
                )
            )
        )
        self.assertEqual(len(self.gateway.messages), 2)

    async def test_global_cooldown_and_expiry(self) -> None:
        await self.create_command(cooldown=30)

        self.assertTrue(
            await self.runtime.route(
                make_message("_discord")
            )
        )
        self.assertTrue(
            await self.runtime.route(
                make_message(
                    "_discord",
                    chatter_id="501",
                )
            )
        )
        self.assertEqual(len(self.gateway.messages), 1)

        self.clock.advance(30)
        self.assertTrue(
            await self.runtime.route(
                make_message("_discord")
            )
        )
        self.assertEqual(len(self.gateway.messages), 2)

    async def test_concurrent_burst_sends_once(self) -> None:
        await self.create_command(cooldown=30)

        results = await asyncio.gather(
            *(
                self.runtime.route(
                    make_message(
                        "_discord",
                        chatter_id=str(500 + index),
                    )
                )
                for index in range(10)
            )
        )

        self.assertTrue(all(results))
        self.assertEqual(len(self.gateway.messages), 1)

    async def test_failed_send_is_contained_and_backed_off(
        self,
    ) -> None:
        await self.create_command(
            response="Private response text.",
            cooldown=60,
        )
        self.gateway.fail = True

        with self.assertLogs(
            "chimebuddy.twitch.custom_commands",
            level="ERROR",
        ) as captured:
            first = await self.runtime.route(
                make_message("_discord")
            )

        self.gateway.fail = False
        second = await self.runtime.route(
            make_message("_discord")
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(self.gateway.messages, [])
        self.assertNotIn(
            "Private response text",
            " ".join(captured.output),
        )

        self.clock.advance(30)
        await self.runtime.route(make_message("_discord"))
        self.assertEqual(len(self.gateway.messages), 1)

    async def test_reserved_core_name_never_executes(
        self,
    ) -> None:
        await self.create_command(
            name="v2ping",
            response="Fake core response.",
        )

        self.assertFalse(
            await self.runtime.route(
                make_message("_v2ping")
            )
        )
        self.assertEqual(self.gateway.messages, [])

    async def test_same_name_is_isolated_by_broadcaster(
        self,
    ) -> None:
        await self.create_command(response="Channel one.")
        await self.create_command(
            response="Channel two.",
            broadcaster_id="300",
        )

        await self.runtime.route(
            make_message("_discord", broadcaster_id="100")
        )
        await self.runtime.route(
            make_message("_discord", broadcaster_id="300")
        )

        self.assertEqual(
            self.gateway.messages,
            [
                ("100", "Channel one."),
                ("300", "Channel two."),
            ],
        )


if __name__ == "__main__":
    unittest.main()
