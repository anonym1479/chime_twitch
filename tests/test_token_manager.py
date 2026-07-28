import time
import unittest

from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
)
from chimebuddy.twitch import (
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    MissingScopesError,
    ReauthorizationRequiredError,
    RefreshedTokens,
    TokenIdentityMismatchError,
    TokenValidation,
    TwitchTokenManager,
)


USER_ID = "1522303489"
CLIENT_ID = "test-client-id"

REQUIRED_SCOPES = (
    "user:bot",
    "user:read:chat",
    "user:write:chat",
)


class FakeCredentialRepository:
    def __init__(
        self,
        credential: OAuthCredential | None,
    ) -> None:
        self.credential = credential
        self.save_count = 0

    async def get(
        self,
        twitch_user_id,
        credential_kind,
    ):
        if self.credential is None:
            return None

        if (
            self.credential.twitch_user_id
            != twitch_user_id
        ):
            return None

        if (
            self.credential.credential_kind
            != credential_kind
        ):
            return None

        return self.credential

    async def save(
        self,
        credential: OAuthCredential,
    ) -> None:
        self.credential = credential
        self.save_count += 1


class FakeOAuthClient:
    def __init__(self) -> None:
        self.client_id = CLIENT_ID
        self.validation_results = {}
        self.refresh_results = {}
        self.validate_calls = []
        self.refresh_calls = []

    async def validate(self, access_token):
        self.validate_calls.append(access_token)

        result = self.validation_results[
            access_token
        ]

        if isinstance(result, Exception):
            raise result

        return result

    async def refresh(self, refresh_token):
        self.refresh_calls.append(refresh_token)

        result = self.refresh_results[
            refresh_token
        ]

        if isinstance(result, Exception):
            raise result

        return result


def make_credential(
    *,
    access_token="access-old",
    refresh_token="refresh-old",
    expires_in=7200,
    scopes=REQUIRED_SCOPES,
):
    return OAuthCredential(
        twitch_user_id=USER_ID,
        credential_kind=OAuthCredentialKind.BOT,
        access_token=access_token,
        refresh_token=refresh_token,
        scopes=scopes,
        expires_at=int(time.time()) + expires_in,
    )


def make_validation(
    *,
    user_id=USER_ID,
    scopes=REQUIRED_SCOPES,
):
    return TokenValidation(
        client_id=CLIENT_ID,
        user_id=user_id,
        login="chimebuddy",
        scopes=tuple(scopes),
        expires_in=7200,
    )


class TwitchTokenManagerTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_validates_then_reuses_token(self):
        repository = FakeCredentialRepository(
            make_credential()
        )
        oauth_client = FakeOAuthClient()

        oauth_client.validation_results[
            "access-old"
        ] = make_validation()

        manager = TwitchTokenManager(
            oauth_client,
            repository,
        )

        first = await manager.get_access_token(
            USER_ID,
            OAuthCredentialKind.BOT,
            REQUIRED_SCOPES,
        )
        second = await manager.get_access_token(
            USER_ID,
            OAuthCredentialKind.BOT,
            REQUIRED_SCOPES,
        )

        self.assertEqual(first, "access-old")
        self.assertEqual(second, "access-old")
        self.assertEqual(
            oauth_client.validate_calls,
            ["access-old"],
        )

    async def test_refreshes_invalid_access_token(self):
        repository = FakeCredentialRepository(
            make_credential()
        )
        oauth_client = FakeOAuthClient()

        oauth_client.validation_results[
            "access-old"
        ] = InvalidAccessTokenError()

        oauth_client.refresh_results[
            "refresh-old"
        ] = RefreshedTokens(
            access_token="access-new",
            refresh_token="refresh-new",
            scopes=REQUIRED_SCOPES,
            expires_in=7200,
            token_type="bearer",
        )

        oauth_client.validation_results[
            "access-new"
        ] = make_validation()

        manager = TwitchTokenManager(
            oauth_client,
            repository,
        )

        token = await manager.get_access_token(
            USER_ID,
            OAuthCredentialKind.BOT,
            REQUIRED_SCOPES,
        )

        self.assertEqual(token, "access-new")
        self.assertEqual(
            repository.credential.access_token,
            "access-new",
        )
        self.assertEqual(
            repository.credential.refresh_token,
            "refresh-new",
        )

    async def test_rejects_missing_scopes(self):
        repository = FakeCredentialRepository(
            make_credential()
        )
        oauth_client = FakeOAuthClient()

        oauth_client.validation_results[
            "access-old"
        ] = make_validation(
            scopes=("user:bot",)
        )

        manager = TwitchTokenManager(
            oauth_client,
            repository,
        )

        with self.assertRaises(
            MissingScopesError
        ) as context:
            await manager.get_access_token(
                USER_ID,
                OAuthCredentialKind.BOT,
                REQUIRED_SCOPES,
            )

        self.assertEqual(
            context.exception.missing_scopes,
            (
                "user:read:chat",
                "user:write:chat",
            ),
        )

    async def test_rejects_wrong_twitch_user(self):
        repository = FakeCredentialRepository(
            make_credential()
        )
        oauth_client = FakeOAuthClient()

        oauth_client.validation_results[
            "access-old"
        ] = make_validation(
            user_id="different-user"
        )

        manager = TwitchTokenManager(
            oauth_client,
            repository,
        )

        with self.assertRaises(
            TokenIdentityMismatchError
        ):
            await manager.get_access_token(
                USER_ID,
                OAuthCredentialKind.BOT,
                REQUIRED_SCOPES,
            )

    async def test_invalid_refresh_requires_auth(self):
        repository = FakeCredentialRepository(
            make_credential(expires_in=10)
        )
        oauth_client = FakeOAuthClient()

        oauth_client.refresh_results[
            "refresh-old"
        ] = InvalidRefreshTokenError()

        manager = TwitchTokenManager(
            oauth_client,
            repository,
        )

        with self.assertRaises(
            ReauthorizationRequiredError
        ):
            await manager.get_access_token(
                USER_ID,
                OAuthCredentialKind.BOT,
                REQUIRED_SCOPES,
            )

    async def test_unauthorized_reuses_newer_token(self):
        repository = FakeCredentialRepository(
            make_credential(
                access_token="access-new",
                refresh_token="refresh-new",
            )
        )
        oauth_client = FakeOAuthClient()

        manager = TwitchTokenManager(
            oauth_client,
            repository,
        )

        token = (
            await manager.recover_after_unauthorized(
                USER_ID,
                OAuthCredentialKind.BOT,
                rejected_access_token="access-old",
                required_scopes=REQUIRED_SCOPES,
            )
        )

        self.assertEqual(token, "access-new")
        self.assertEqual(
            oauth_client.refresh_calls,
            [],
        )


if __name__ == "__main__":
    unittest.main()