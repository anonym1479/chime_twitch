import time
import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLinkSession,
    AccountLinkSessionStatus,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    AccountLinkSessionRepository,
    IdentityRepository,
    PendingAccountLinkSessionError,
)


class AccountLinkSessionRepositoryTests(
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

        identity_repository = IdentityRepository(
            self.database
        )

        await identity_repository.save_discord_account(
            DiscordAccount(
                discord_user_id="123",
                username="example_user",
                display_name="Example User",
            )
        )

        await identity_repository.save_twitch_account(
            TwitchAccount(
                twitch_user_id="456",
                login="example_streamer",
                display_name="Example Streamer",
            )
        )

        self.repository = (
            AccountLinkSessionRepository(
                self.database
            )
        )

    def make_session(
        self,
        session_id: str = "session-1",
        *,
        expires_at: int | None = None,
    ) -> AccountLinkSession:
        return AccountLinkSession(
            session_id=session_id,
            discord_user_id="123",
            requested_scopes=("channel:bot",),
            expires_at=(
                expires_at
                if expires_at is not None
                else int(time.time()) + 300
            ),
        )

    async def test_creates_and_loads_session(
        self,
    ) -> None:
        await self.repository.create(
            self.make_session()
        )

        loaded = await self.repository.get(
            "session-1"
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(
            loaded.discord_user_id,
            "123",
        )
        self.assertEqual(
            loaded.requested_scopes,
            ("channel:bot",),
        )
        self.assertEqual(
            loaded.status,
            AccountLinkSessionStatus.PENDING,
        )

    async def test_rejects_second_pending_session(
        self,
    ) -> None:
        await self.repository.create(
            self.make_session("session-1")
        )

        with self.assertRaises(
            PendingAccountLinkSessionError
        ):
            await self.repository.create(
                self.make_session("session-2")
            )

    async def test_authorizes_only_once(
        self,
    ) -> None:
        await self.repository.create(
            self.make_session()
        )

        first_result = await self.repository.authorize(
            "session-1",
            "456",
        )

        second_result = await self.repository.authorize(
            "session-1",
            "456",
        )

        loaded = await self.repository.get(
            "session-1"
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(
            loaded.status,
            AccountLinkSessionStatus.AUTHORIZED,
        )
        self.assertEqual(
            loaded.twitch_user_id,
            "456",
        )
        self.assertIsNotNone(
            loaded.completed_at
        )

    async def test_failed_session_cannot_change_twice(
        self,
    ) -> None:
        await self.repository.create(
            self.make_session()
        )

        first_result = await self.repository.fail(
            "session-1",
            "Test authorization failure.",
        )

        second_result = await self.repository.cancel(
            "session-1"
        )

        loaded = await self.repository.get(
            "session-1"
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(
            loaded.status,
            AccountLinkSessionStatus.FAILED,
        )
        self.assertEqual(
            loaded.last_error,
            "Test authorization failure.",
        )

    async def test_cancel_session(
        self,
    ) -> None:
        await self.repository.create(
            self.make_session()
        )

        changed = await self.repository.cancel(
            "session-1"
        )

        loaded = await self.repository.get(
            "session-1"
        )

        self.assertTrue(changed)
        self.assertEqual(
            loaded.status,
            AccountLinkSessionStatus.CANCELLED,
        )

    async def test_expire_due_sessions(
        self,
    ) -> None:
        current_time = int(time.time())

        await self.repository.create(
            self.make_session(
                expires_at=current_time + 10
            )
        )

        changed = await self.repository.expire_due(
            now=current_time + 10
        )

        loaded = await self.repository.get(
            "session-1"
        )

        self.assertEqual(changed, 1)
        self.assertEqual(
            loaded.status,
            AccountLinkSessionStatus.EXPIRED,
        )

    async def test_expired_session_allows_retry(
        self,
    ) -> None:
        current_time = int(time.time())

        await self.repository.create(
            self.make_session(
                "session-1",
                expires_at=current_time + 1,
            )
        )

        await self.repository.expire_due(
            now=current_time + 1
        )

        await self.repository.create(
            self.make_session(
                "session-2",
                expires_at=current_time + 300,
            )
        )

        pending = (
            await self.repository
            .get_pending_for_discord("123")
        )

        self.assertIsNotNone(pending)
        self.assertEqual(
            pending.session_id,
            "session-2",
        )


if __name__ == "__main__":
    unittest.main()