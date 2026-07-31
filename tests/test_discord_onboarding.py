import time
import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.onboarding import (
    AccountConfirmationView,
    CONNECT_BUTTON_CUSTOM_ID,
    DiscordOnboardingController,
    OnboardingView,
    build_onboarding_embed,
    render_challenge,
)
from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.services import (
    AccountLinkAuthorization,
    AccountLinkChallenge,
)
from chimebuddy.twitch.device_authorization import (
    DeviceAuthorization,
)


class FakeAccountLinkingService:
    pass


class FakeResponse:
    def __init__(self) -> None:
        self.modals = []
        self.messages = []

    async def send_modal(self, modal) -> None:
        self.modals.append(modal)

    async def send_message(self, *args, **kwargs) -> None:
        self.messages.append((args, kwargs))


class FakeInteraction:
    def __init__(self) -> None:
        self.user = SimpleNamespace(id=123)
        self.response = FakeResponse()


def make_authorization() -> AccountLinkAuthorization:
    return AccountLinkAuthorization(
        session_id="session-1",
        discord_user_id="123",
        twitch_user_id="456",
        twitch_login="example_streamer",
        confirmation_expires_at=int(time.time()) + 600,
        twitch_account=TwitchAccount(
            twitch_user_id="456",
            login="example_streamer",
            display_name="Example Streamer",
        ),
        credential=OAuthCredential(
            twitch_user_id="456",
            credential_kind=(
                OAuthCredentialKind.BROADCASTER
            ),
            access_token="access-token",
            refresh_token="refresh-token",
            scopes=("channel:bot",),
            expires_at=int(time.time()) + 3600,
        ),
    )


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

    async def test_opening_request_modal_does_not_claim(
        self,
    ) -> None:
        controller = DiscordOnboardingController(
            FakeAccountLinkingService()
        )
        view = AccountConfirmationView(
            controller=controller,
            authorization=make_authorization(),
        )
        first_interaction = FakeInteraction()
        second_interaction = FakeInteraction()

        await view.continue_button.callback(
            first_interaction
        )
        await view.continue_button.callback(
            second_interaction
        )

        self.assertEqual(
            len(first_interaction.response.modals),
            1,
        )
        self.assertEqual(
            len(second_interaction.response.modals),
            1,
        )
        self.assertEqual(
            second_interaction.response.messages,
            [],
        )

    async def test_confirmation_claim_is_one_time(self):
        controller = DiscordOnboardingController(
            FakeAccountLinkingService()
        )
        view = AccountConfirmationView(
            controller=controller,
            authorization=make_authorization(),
        )

        self.assertTrue(view.claim())
        self.assertFalse(view.claim())
        view.release()
        self.assertTrue(view.claim())


if __name__ == "__main__":
    unittest.main()
