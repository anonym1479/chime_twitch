import time
import unittest

from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
)
from chimebuddy.twitch import (
    BotCredentialNotFoundError,
    MultipleBotCredentialsError,
    select_single_bot_credential,
)


def make_credential(
    twitch_user_id: str,
) -> OAuthCredential:
    return OAuthCredential(
        twitch_user_id=twitch_user_id,
        credential_kind=OAuthCredentialKind.BOT,
        access_token=f"access-{twitch_user_id}",
        refresh_token=f"refresh-{twitch_user_id}",
        scopes=("user:bot",),
        expires_at=int(time.time()) + 3600,
    )


class TwitchRuntimeTests(unittest.TestCase):
    def test_selects_single_bot_credential(self):
        credential = make_credential("100")

        selected = select_single_bot_credential(
            [credential]
        )

        self.assertIs(selected, credential)

    def test_rejects_missing_bot_credential(self):
        with self.assertRaises(
            BotCredentialNotFoundError
        ):
            select_single_bot_credential([])

    def test_rejects_multiple_bot_credentials(self):
        with self.assertRaises(
            MultipleBotCredentialsError
        ):
            select_single_bot_credential(
                [
                    make_credential("100"),
                    make_credential("200"),
                ]
            )


if __name__ == "__main__":
    unittest.main()