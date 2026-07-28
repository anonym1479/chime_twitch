import time
import unittest

from chimebuddy.models import (
    OAuthCredentialKind,
)
from chimebuddy.tools.authorize_broadcaster import (
    save_broadcaster_authorization,
)
from chimebuddy.twitch import (
    RefreshedTokens,
    TokenValidation,
)


class FakeIdentityRepository:
    def __init__(self, events):
        self.events = events
        self.account = None

    async def save_twitch_account(
        self,
        account,
    ):
        self.events.append("identity")
        self.account = account


class FakeCredentialRepository:
    def __init__(self, events):
        self.events = events
        self.credential = None

    async def save(self, credential):
        self.events.append("credential")
        self.credential = credential


class AuthorizeBroadcasterTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_saves_identity_before_credential(
        self,
    ):
        events = []

        identity_repository = (
            FakeIdentityRepository(events)
        )
        credential_repository = (
            FakeCredentialRepository(events)
        )

        validation = TokenValidation(
            client_id="client-id",
            user_id="211164044",
            login="example_streamer",
            scopes=("channel:bot",),
            expires_in=7200,
        )

        tokens = RefreshedTokens(
            access_token="access-token",
            refresh_token="refresh-token",
            scopes=("channel:bot",),
            expires_in=7200,
            token_type="bearer",
        )

        await save_broadcaster_authorization(
            identity_repository,
            credential_repository,
            validation,
            tokens,
        )

        self.assertEqual(
            events,
            ["identity", "credential"],
        )
        self.assertEqual(
            (
                credential_repository
                .credential
                .credential_kind
            ),
            OAuthCredentialKind.BROADCASTER,
        )
        self.assertGreater(
            (
                credential_repository
                .credential
                .expires_at
            ),
            int(time.time()),
        )


if __name__ == "__main__":
    unittest.main()