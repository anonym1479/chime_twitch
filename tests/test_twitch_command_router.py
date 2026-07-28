import unittest

from chimebuddy.models.chat import (
    TwitchChatBadge,
    TwitchChatMessage,
)
from chimebuddy.services.twitch_command_router import (
    TwitchCommandPermission,
    TwitchCommandRouter,
)


def make_message(
    text: str,
    *,
    chatter_user_id: str = "200",
    badges: tuple[TwitchChatBadge, ...] = (),
) -> TwitchChatMessage:
    return TwitchChatMessage(
        broadcaster_twitch_user_id="100",
        broadcaster_login="streamer",
        broadcaster_display_name="Streamer",
        chatter_twitch_user_id=chatter_user_id,
        chatter_login="example_user",
        chatter_display_name="Example User",
        message_id="message-1",
        text=text,
        message_type="text",
        badges=badges,
    )


class TwitchCommandRouterTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_routes_command_with_arguments(
        self,
    ) -> None:
        router = TwitchCommandRouter()
        received = []

        async def handler(context):
            received.append(context)

        router.register(
            "test",
            TwitchCommandPermission.EVERYONE,
            handler,
        )

        handled = await router.route(
            make_message("_TEST one two")
        )

        self.assertTrue(handled)
        self.assertEqual(len(received), 1)
        self.assertEqual(
            received[0].command_name,
            "test",
        )
        self.assertEqual(
            received[0].arguments,
            ("one", "two"),
        )
        self.assertEqual(
            received[0].raw_arguments,
            "one two",
        )

    async def test_viewer_cannot_use_vip_command(
        self,
    ) -> None:
        router = TwitchCommandRouter()
        calls = 0

        async def handler(context):
            nonlocal calls
            calls += 1

        router.register(
            "viptest",
            TwitchCommandPermission.VIP,
            handler,
        )

        handled = await router.route(
            make_message("_viptest")
        )

        self.assertFalse(handled)
        self.assertEqual(calls, 0)

    async def test_vip_can_use_vip_command(
        self,
    ) -> None:
        router = TwitchCommandRouter()
        calls = 0

        async def handler(context):
            nonlocal calls
            calls += 1

        router.register(
            "viptest",
            TwitchCommandPermission.VIP,
            handler,
        )

        handled = await router.route(
            make_message(
                "_viptest",
                badges=(
                    TwitchChatBadge(
                        set_id="vip",
                        badge_id="1",
                    ),
                ),
            )
        )

        self.assertTrue(handled)
        self.assertEqual(calls, 1)

    async def test_moderator_can_use_vip_command(
        self,
    ) -> None:
        router = TwitchCommandRouter()
        calls = 0

        async def handler(context):
            nonlocal calls
            calls += 1

        router.register(
            "viptest",
            TwitchCommandPermission.VIP,
            handler,
        )

        handled = await router.route(
            make_message(
                "_viptest",
                badges=(
                    TwitchChatBadge(
                        set_id="moderator",
                        badge_id="1",
                    ),
                ),
            )
        )

        self.assertTrue(handled)
        self.assertEqual(calls, 1)

    async def test_broadcaster_can_use_mod_command(
        self,
    ) -> None:
        router = TwitchCommandRouter()
        calls = 0

        async def handler(context):
            nonlocal calls
            calls += 1

        router.register(
            "modtest",
            TwitchCommandPermission.MODERATOR,
            handler,
        )

        handled = await router.route(
            make_message(
                "_modtest",
                chatter_user_id="100",
            )
        )

        self.assertTrue(handled)
        self.assertEqual(calls, 1)

    async def test_unknown_command_is_ignored(
        self,
    ) -> None:
        router = TwitchCommandRouter()

        handled = await router.route(
            make_message("_doesnotexist")
        )

        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()