import os
import unittest
from unittest.mock import patch

from chimebuddy.config import ConfigurationError, load_settings


VALID_ENVIRONMENT = {
    "CHIMEBUDDY_ENV": "test",
    "CHIMEBUDDY_DATABASE_PATH": "var/test.db",
    "CHIMEBUDDY_LOG_LEVEL": "DEBUG",
    "TWITCH_CLIENT_ID": "test-client-id",
    "TWITCH_CLIENT_SECRET": "test-client-secret",
    "DISCORD_TOKEN": "test-discord-token",
    "DEVELOPER_DISCORD_USER_ID": "123456789",
}


class ConfigurationTests(unittest.TestCase):
    @patch.dict(os.environ, VALID_ENVIRONMENT, clear=True)
    def test_valid_configuration(self) -> None:
        settings = load_settings(env_file=None)

        settings.validate_for_twitch()
        settings.validate_for_discord()

        self.assertEqual(settings.environment, "test")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(
            settings.developer_discord_user_id,
            123456789,
        )

    @patch.dict(
        os.environ,
        {
            key: value
            for key, value in VALID_ENVIRONMENT.items()
            if key != "TWITCH_CLIENT_SECRET"
        },
        clear=True,
    )
    def test_missing_twitch_secret_is_rejected(self) -> None:
        settings = load_settings(env_file=None)

        with self.assertRaisesRegex(
            ConfigurationError,
            "TWITCH_CLIENT_SECRET",
        ):
            settings.validate_for_twitch()

    @patch.dict(os.environ, VALID_ENVIRONMENT, clear=True)
    def test_secrets_are_hidden_from_representation(self) -> None:
        settings = load_settings(env_file=None)
        representation = repr(settings)

        self.assertNotIn("test-client-secret", representation)
        self.assertNotIn("test-discord-token", representation)

    @patch.dict(
        os.environ,
        {
            **VALID_ENVIRONMENT,
            "DEVELOPER_DISCORD_USER_ID": "not-a-number",
        },
        clear=True,
    )
    def test_invalid_developer_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigurationError,
            "must contain a numeric ID",
        ):
            load_settings(env_file=None)


if __name__ == "__main__":
    unittest.main()