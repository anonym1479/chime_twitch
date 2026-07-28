import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories import (
    IdentityRepository,
    OAuthCredentialRepository,
)


class OAuthCredentialRepositoryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        database_path = (
            Path(self.temp_directory.name) / "test.db"
        )

        self.database = Database(database_path)
        await self.database.initialize()

        identity_repository = IdentityRepository(
            self.database
        )

        await identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="1522303489",
                login="chimebuddy",
                display_name="ChimeBuddy",
            )
        )

        self.repository = OAuthCredentialRepository(
            self.database
        )

    @staticmethod
    def create_credential(
        *,
        access_token: str = "test-access-token",
        refresh_token: str = "test-refresh-token",
        expires_at: int = 2_000_000_000,
    ) -> OAuthCredential:
        return OAuthCredential(
            twitch_user_id="1522303489",
            credential_kind=OAuthCredentialKind.BOT,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=(
                "user:write:chat",
                "user:read:chat",
                "user:write:chat",
            ),
            expires_at=expires_at,
        )

    async def test_save_and_get_credential(
        self,
    ) -> None:
        credential = self.create_credential()

        await self.repository.save(credential)

        stored = await self.repository.get(
            "1522303489",
            OAuthCredentialKind.BOT,
        )

        self.assertEqual(stored, credential)
        self.assertEqual(
            stored.scopes,
            (
                "user:read:chat",
                "user:write:chat",
            ),
        )

    async def test_rotated_tokens_replace_old_tokens(
        self,
    ) -> None:
        await self.repository.save(
            self.create_credential()
        )

        await self.repository.save(
            self.create_credential(
                access_token="rotated-access-token",
                refresh_token="rotated-refresh-token",
                expires_at=2_100_000_000,
            )
        )

        stored = await self.repository.get(
            "1522303489",
            OAuthCredentialKind.BOT,
        )

        self.assertEqual(
            stored.access_token,
            "rotated-access-token",
        )
        self.assertEqual(
            stored.refresh_token,
            "rotated-refresh-token",
        )
        self.assertEqual(
            stored.expires_at,
            2_100_000_000,
        )

    async def test_tokens_are_hidden_from_repr(
        self,
    ) -> None:
        credential = self.create_credential()
        representation = repr(credential)

        self.assertNotIn(
            "test-access-token",
            representation,
        )
        self.assertNotIn(
            "test-refresh-token",
            representation,
        )

    def test_expiry_window(self) -> None:
        credential = self.create_credential(
            expires_at=1_000,
        )

        self.assertFalse(
            credential.expires_within(
                100,
                now=800,
            )
        )

        self.assertTrue(
            credential.expires_within(
                100,
                now=900,
            )
        )


if __name__ == "__main__":
    unittest.main()