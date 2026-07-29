import unittest

from chimebuddy.discord_admin.provisioning import (
    build_broadcaster_panel_embed,
    normalize_channel_name,
    opening_panel_marker,
)
from chimebuddy.models import BroadcasterRequest


class DiscordProvisioningTests(
    unittest.TestCase
):
    def test_normalizes_twitch_login(
        self,
    ) -> None:
        self.assertEqual(
            normalize_channel_name(
                "Example_Streamer"
            ),
            "example-streamer",
        )

    def test_empty_name_has_fallback(
        self,
    ) -> None:
        self.assertEqual(
            normalize_channel_name("___"),
            "twitch-channel",
        )

    def test_panel_contains_request_identity(
        self,
    ) -> None:
        request = BroadcasterRequest(
            request_id=7,
            twitch_user_id="456",
            discord_user_id="123",
        )

        embed = build_broadcaster_panel_embed(
            request,
            "example_streamer",
        )

        rendered = " ".join(
            str(field.value)
            for field in embed.fields
        )

        self.assertIn(
            "example_streamer",
            rendered,
        )
        self.assertIn("123", rendered)
        self.assertEqual(
            embed.footer.text,
            opening_panel_marker(7),
        )


if __name__ == "__main__":
    unittest.main()