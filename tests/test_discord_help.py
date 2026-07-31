import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.help import (
    DiscordHelpController,
    HelpLanguage,
    HelpLanguageSelect,
    build_help_embed,
    preferred_help_language,
)
from chimebuddy.discord_admin.client import (
    ChimeBuddyDiscordClient,
)


class FakeResponse:
    def __init__(self) -> None:
        self.messages = []
        self.edits = []

    async def send_message(self, **kwargs) -> None:
        self.messages.append(kwargs)

    async def edit_message(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeInteraction:
    def __init__(
        self,
        *,
        locale: str = "en-US",
        user_id: int = 123,
    ) -> None:
        self.locale = locale
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeResponse()


class DiscordHelpTests(
    unittest.IsolatedAsyncioTestCase
):
    def test_hungarian_locale_is_selected(self) -> None:
        self.assertEqual(
            preferred_help_language("hu"),
            HelpLanguage.HUNGARIAN,
        )
        self.assertEqual(
            preferred_help_language("en-US"),
            HelpLanguage.ENGLISH,
        )

    def test_both_help_embeds_contain_core_guidance(
        self,
    ) -> None:
        english = build_help_embed(HelpLanguage.ENGLISH)
        hungarian = build_help_embed(
            HelpLanguage.HUNGARIAN
        )

        self.assertEqual(english.title, "Welcome to ChimeBuddy")
        self.assertEqual(hungarian.title, "Üdvözöl a ChimeBuddy!")
        self.assertIn(
            "Title triggers",
            " ".join(field.name for field in english.fields),
        )
        self.assertIn(
            "Címaktiválók",
            " ".join(field.name for field in hungarian.fields),
        )

        for embed in (english, hungarian):
            total_length = (
                len(embed.title or "")
                + len(embed.description or "")
                + sum(
                    len(field.name) + len(field.value)
                    for field in embed.fields
                )
                + len(embed.footer.text or "")
            )
            self.assertLessEqual(total_length, 6000)

    async def test_help_uses_interaction_locale_and_is_private(
        self,
    ) -> None:
        controller = DiscordHelpController()
        interaction = FakeInteraction(locale="hu")

        await controller.show_help(interaction)

        message = interaction.response.messages[0]
        self.assertTrue(message["ephemeral"])
        self.assertEqual(
            message["embed"].title,
            "Üdvözöl a ChimeBuddy!",
        )
        select = next(
            child
            for child in message["view"].children
            if isinstance(child, HelpLanguageSelect)
        )
        defaults = {
            option.value: option.default
            for option in select.options
        }
        self.assertEqual(
            defaults,
            {"en": False, "hu": True},
        )

    async def test_language_change_rebuilds_embed_and_view(
        self,
    ) -> None:
        controller = DiscordHelpController()
        interaction = FakeInteraction(locale="en-US")

        await controller.change_language(
            interaction,
            HelpLanguage.HUNGARIAN,
            requested_by_user_id=123,
        )

        edit = interaction.response.edits[0]
        self.assertEqual(
            edit["embed"].title,
            "Üdvözöl a ChimeBuddy!",
        )

    async def test_help_command_is_registered(self) -> None:
        client = ChimeBuddyDiscordClient(
            developer_discord_user_id=999,
            discord_guild_id=1000,
            status_service=SimpleNamespace(),
            help_controller=DiscordHelpController(),
        )

        try:
            names = {
                command.name
                for command in client.command_tree.get_commands(
                    guild=client.guild_object
                )
            }
            self.assertIn("help", names)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
