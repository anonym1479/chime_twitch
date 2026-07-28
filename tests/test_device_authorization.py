import unittest

from chimebuddy.twitch import (
    OAuthResponseError,
    TwitchDeviceAuthorizationClient,
)


class DeviceAuthorizationTests(
    unittest.TestCase
):
    def test_parses_device_authorization(self):
        authorization = (
            TwitchDeviceAuthorizationClient
            .parse_authorization(
                {
                    "device_code": "secret-code",
                    "user_code": "ABCDEFGH",
                    "verification_uri": (
                        "https://www.twitch.tv/activate"
                    ),
                    "expires_in": 1800,
                    "interval": 5,
                }
            )
        )

        self.assertEqual(
            authorization.user_code,
            "ABCDEFGH",
        )
        self.assertEqual(
            authorization.expires_in,
            1800,
        )
        self.assertNotIn(
            "secret-code",
            repr(authorization),
        )

    def test_missing_device_code_fails(self):
        with self.assertRaises(
            OAuthResponseError
        ):
            (
                TwitchDeviceAuthorizationClient
                .parse_authorization(
                    {
                        "user_code": "ABCDEFGH",
                        "verification_uri": (
                            "https://www.twitch.tv/"
                            "activate"
                        ),
                        "expires_in": 1800,
                        "interval": 5,
                    }
                )
            )

    def test_requires_at_least_one_scope(self):
        with self.assertRaises(ValueError):
            (
                TwitchDeviceAuthorizationClient
                ._scope_text(())
            )


if __name__ == "__main__":
    unittest.main()