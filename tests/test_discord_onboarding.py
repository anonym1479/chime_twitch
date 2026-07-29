import time
import unittest

from chimebuddy.discord_admin.onboarding import (
    CONNECT_BUTTON_CUSTOM_ID,
    DiscordOnboardingController,
    OnboardingView,
    build_onboarding_embed,
    render_challenge,
)
from chimebuddy.services import AccountLinkChallenge
from chimebuddy.twitch.device_authorization import (
    DeviceAuthorization,
)


class FakeAccountLinkingService:
    pass


class DiscordOnboardingTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_view_is_persistent(self):
        controller = DiscordOnboardingController(
            FakeAccountLinkingService()
        )

        view = OnboardingView(controller)

        self.assertIsNone(view.timeout)
        self.assertEqual(len(view.children), 1)
        self.assertEqual(
            view.children[0].custom_id,
            CONNECT_BUTTON_CUSTOM_ID,
        )

    async def test_panel_has_expected_title(self):
        embed = build_onboarding_embed()

        self.assertEqual(
            embed.title,
            "Connect Twitch & Request ChimeBuddy",
        )
        self.assertIn(
            "channel:bot",
            embed.description,
        )

    async def test_challenge_hides_device_secret(self):
        expires_at = int(time.time()) + 300

        challenge = AccountLinkChallenge(
            session_id="session-1",
            discord_user_id="123",
            user_code="PUBLIC123",
            verification_uri=(
                "https://www.twitch.tv/activate"
            ),
            expires_at=expires_at,
            requested_scopes=("channel:bot",),
            authorization=DeviceAuthorization(
                device_code="secret-device-code",
                user_code="PUBLIC123",
                verification_uri=(
                    "https://www.twitch.tv/activate"
                ),
                expires_in=300,
                interval=5,
            ),
        )

        rendered = render_challenge(challenge)

        self.assertIn("PUBLIC123", rendered)
        self.assertIn(
            "https://www.twitch.tv/activate",
            rendered,
        )
        self.assertNotIn(
            "secret-device-code",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()