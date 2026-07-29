import time
import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkSession,
    AccountLinkSessionStatus,
    AccountLinkStatus,
    DiscordAccount,
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AccountLinkCompletionRepository,
    AccountLinkIdentityConflictError,
    AccountLinkSessionRepository,
    IdentityRepository,
    OAuthCredentialRepository,
)


class AccountLinkCompletionRepositoryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.addCleanup(
            self.temp_directory.cleanup
        )

        database_path = (
            Path(self.temp_directory.name)
            / "test.db"
        )

        self.database = Database(database_path)
        await self.database.initialize()

        self.identity_repository = IdentityRepository(
            self.database
        )
        self.credential_repository = (
            OAuthCredentialRepository(
                self.database
            )
        )
        self.session_repository = (
            AccountLinkSessionRepository(
                self.database
            )
        )
        self.completion_repository = (
            AccountLinkCompletionRepository(
                self.database
            )
        )

        await self.identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123",
                username="example_user",
                display_name="Example User",
            )
        )

        self.current_time = int(time.time())

        await self.session_repository.create(
            AccountLinkSession(
                session_id="session-1",
                discord_user_id="123",
                requested_scopes=("channel:bot",),
                expires_at=self.current_time + 300,
            )
        )

    def make_twitch_account(
        self,
        twitch_user_id: str = "456",
    ) -> TwitchAccount:
        return TwitchAccount(
            twitch_user_id=twitch_user_id,
            login="example_streamer",
            display_name="Example Streamer",
        )

    def make_credential(
        self,
        twitch_user_id: str = "456",
    ) -> OAuthCredential:
        return OAuthCredential(
            twitch_user_id=twitch_user_id,
            credential_kind=(
                OAuthCredentialKind.BROADCASTER
            ),
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            scopes=("channel:bot",),
            expires_at=self.current_time + 3600,
        )

    async def test_completes_all_link_data(
        self,
    ) -> None:
        completed = (
            await self.completion_repository.complete(
                "session-1",
                twitch_account=(
                    self.make_twitch_account()
                ),
                credential=self.make_credential(),
                now=self.current_time,
            )
        )

        session = await self.session_repository.get(
            "session-1"
        )
        link = (
            await self.identity_repository
            .get_account_link("456")
        )
        credential = (
            await self.credential_repository.get(
                "456",
                OAuthCredentialKind.BROADCASTER,
            )
        )

        self.assertTrue(completed)
        self.assertEqual(
            session.status,
            AccountLinkSessionStatus.AUTHORIZED,
        )
        self.assertEqual(
            session.twitch_user_id,
            "456",
        )
        self.assertEqual(
            link.discord_user_id,
            "123",
        )
        self.assertEqual(
            link.status,
            AccountLinkStatus.VERIFIED,
        )
        self.assertIsNotNone(credential)

    async def test_completion_is_one_time(
        self,
    ) -> None:
        first_result = (
            await self.completion_repository.complete(
                "session-1",
                twitch_account=(
                    self.make_twitch_account()
                ),
                credential=self.make_credential(),
                now=self.current_time,
            )
        )

        second_result = (
            await self.completion_repository.complete(
                "session-1",
                twitch_account=(
                    self.make_twitch_account()
                ),
                credential=self.make_credential(),
                now=self.current_time,
            )
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)

    async def test_rejects_identity_conflict_atomically(
        self,
    ) -> None:
        await self.identity_repository.save_twitch_account(
            self.make_twitch_account("999")
        )

        await self.identity_repository.save_account_link(
            AccountLink(
                twitch_user_id="999",
                discord_user_id="123",
                status=AccountLinkStatus.VERIFIED,
                verification_method="test",
            )
        )

        with self.assertRaises(
            AccountLinkIdentityConflictError
        ):
            await self.completion_repository.complete(
                "session-1",
                twitch_account=(
                    self.make_twitch_account("456")
                ),
                credential=(
                    self.make_credential("456")
                ),
                now=self.current_time,
            )

        session = await self.session_repository.get(
            "session-1"
        )
        credential = (
            await self.credential_repository.get(
                "456",
                OAuthCredentialKind.BROADCASTER,
            )
        )

        self.assertEqual(
            session.status,
            AccountLinkSessionStatus.PENDING,
        )
        self.assertIsNone(credential)


if __name__ == "__main__":
    unittest.main()