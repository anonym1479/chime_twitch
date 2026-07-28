import unittest
from types import SimpleNamespace

from chimebuddy.discord_admin.client import (
    is_developer,
)
from chimebuddy.discord_admin.status_service import (
    DiscordAdminStatusService,
)


class FakeIdentityRepository:
    def __init__(self, broadcasters) -> None:
        self.broadcasters = broadcasters

    async def list_broadcasters(
        self,
        *,
        enabled_only: bool = False,
    ):
        if not enabled_only:
            return self.broadcasters

        return [
            broadcaster
            for broadcaster in self.broadcasters
            if broadcaster.enabled
        ]


class DiscordAdminStatusTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_counts_broadcasters(
        self,
    ) -> None:
        repository = FakeIdentityRepository(
            [
                SimpleNamespace(enabled=True),
                SimpleNamespace(enabled=True),
                SimpleNamespace(enabled=False),
            ]
        )

        service = DiscordAdminStatusService(
            repository
        )

        status = await service.get_status()

        self.assertEqual(
            status.total_broadcasters,
            3,
        )
        self.assertEqual(
            status.enabled_broadcasters,
            2,
        )
        self.assertEqual(
            status.disabled_broadcasters,
            1,
        )

    async def test_render_contains_status(
        self,
    ) -> None:
        service = DiscordAdminStatusService(
            FakeIdentityRepository(
                [
                    SimpleNamespace(enabled=True),
                ]
            )
        )

        status = await service.get_status()
        rendered = status.render()

        self.assertIn(
            "Discord administration bot: online",
            rendered,
        )
        self.assertIn(
            "Broadcasters: 1",
            rendered,
        )

    async def test_developer_identity_check(
        self,
    ) -> None:
        self.assertTrue(
            is_developer(123, 123)
        )
        self.assertFalse(
            is_developer(123, 456)
        )


if __name__ == "__main__":
    unittest.main()