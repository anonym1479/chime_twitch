import unittest

from chimebuddy.twitch import (
    OAuthResponseError,
    TwitchOAuthClient,
)


class TwitchOAuthClientTests(unittest.TestCase):
    def test_parse_validation(self) -> None:
        validation = (
            TwitchOAuthClient.parse_validation(
                {
                    "client_id": "client-123",
                    "user_id": "1522303489",
                    "login": "ChimeBuddy",
                    "scopes": [
                        "user:write:chat",
                        "user:read:chat",
                    ],
                    "expires_in": 3600,
                }
            )
        )

        self.assertEqual(
            validation.client_id,
            "client-123",
        )
        self.assertEqual(
            validation.user_id,
            "1522303489",
        )
        self.assertEqual(
            validation.login,
            "chimebuddy",
        )
        self.assertEqual(
            validation.scopes,
            (
                "user:read:chat",
                "user:write:chat",
            ),
        )
        self.assertEqual(
            validation.expires_in,
            3600,
        )

    def test_parse_refresh_with_scope_list(
        self,
    ) -> None:
        tokens = TwitchOAuthClient.parse_refresh(
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "scope": [
                    "user:write:chat",
                    "user:read:chat",
                ],
                "expires_in": 7200,
                "token_type": "bearer",
            }
        )

        self.assertEqual(
            tokens.scopes,
            (
                "user:read:chat",
                "user:write:chat",
            ),
        )

    def test_parse_refresh_with_scope_string(
        self,
    ) -> None:
        tokens = TwitchOAuthClient.parse_refresh(
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "scope": (
                    "user:read:chat user:write:chat"
                ),
                "expires_in": 7200,
                "token_type": "bearer",
            }
        )

        self.assertEqual(
            tokens.scopes,
            (
                "user:read:chat",
                "user:write:chat",
            ),
        )

    def test_tokens_are_hidden_from_repr(
        self,
    ) -> None:
        tokens = TwitchOAuthClient.parse_refresh(
            {
                "access_token": "secret-access-token",
                "refresh_token": "secret-refresh-token",
                "scope": [],
                "expires_in": 7200,
                "token_type": "bearer",
            }
        )

        representation = repr(tokens)

        self.assertNotIn(
            "secret-access-token",
            representation,
        )
        self.assertNotIn(
            "secret-refresh-token",
            representation,
        )

    def test_invalid_validation_response_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(OAuthResponseError):
            TwitchOAuthClient.parse_validation(
                {
                    "expires_in": 3600,
                    "scopes": [],
                }
            )

    def test_invalid_expiry_is_rejected(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            OAuthResponseError,
            "expires_in",
        ):
            TwitchOAuthClient.parse_refresh(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "scope": [],
                    "expires_in": 0,
                }
            )


if __name__ == "__main__":
    unittest.main()