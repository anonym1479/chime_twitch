import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.repositories import (
    RuntimeHealthRepository,
)


class RuntimeHealthRepositoryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database = Database(
            Path(self.temp_directory.name) / "test.db"
        )
        await self.database.initialize()
        self.repository = RuntimeHealthRepository(
            self.database
        )

    async def test_success_and_failure_are_persisted(
        self,
    ) -> None:
        await self.repository.mark_success(
            "token_validation",
            "456",
        )
        await self.repository.mark_failure(
            "token_validation",
            "456",
            error_code="oauth_temporarily_unavailable",
            safe_message=(
                "Twitch authorization could not be "
                "checked."
            ),
        )

        snapshot = await self.repository.get(
            "token_validation",
            "456",
        )
        errors = await self.repository.list_recent_errors(
            "456"
        )

        self.assertEqual(snapshot.status, "error")
        self.assertIsNotNone(snapshot.last_success_at)
        self.assertIsNotNone(snapshot.last_failure_at)
        self.assertEqual(
            errors[0].error_code,
            "oauth_temporarily_unavailable",
        )

    async def test_status_change_is_not_a_failure(
        self,
    ) -> None:
        await self.repository.set_status(
            "eventsub",
            "456",
            status="waiting",
        )

        snapshot = await self.repository.get(
            "eventsub",
            "456",
        )
        errors = await self.repository.list_recent_errors(
            "456"
        )

        self.assertEqual(snapshot.status, "waiting")
        self.assertIsNone(snapshot.last_failure_at)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
