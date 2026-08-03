import asyncio
import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    CustomCommand,
    CustomCommandPermission,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    CustomCommandLimitError,
    CustomCommandRepository,
    DuplicateCustomCommandNameError,
    IdentityRepository,
)


class CustomCommandRepositoryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database = Database(
            Path(self.temp_directory.name) / "test.db"
        )
        await self.database.initialize()

        identity_repository = IdentityRepository(
            self.database
        )

        for twitch_id, discord_id, login in (
            ("100", "200", "streamer_one"),
            ("300", "400", "streamer_two"),
        ):
            await identity_repository.save_twitch_account(
                TwitchAccount(
                    twitch_user_id=twitch_id,
                    login=login,
                    display_name=login,
                )
            )
            await identity_repository.save_discord_account(
                DiscordAccount(
                    discord_user_id=discord_id,
                    username=f"user_{discord_id}",
                    display_name=f"User {discord_id}",
                )
            )
            await identity_repository.save_account_link(
                AccountLink(
                    twitch_user_id=twitch_id,
                    discord_user_id=discord_id,
                    status=AccountLinkStatus.VERIFIED,
                    verification_method="test",
                )
            )
            await identity_repository.save_broadcaster(
                Broadcaster(
                    twitch_user_id=twitch_id,
                    owner_discord_user_id=discord_id,
                )
            )

        self.repository = CustomCommandRepository(
            self.database
        )

    def command(
        self,
        name: str = "discord",
        *,
        broadcaster_id: str = "100",
        enabled: bool = True,
    ) -> CustomCommand:
        return CustomCommand(
            broadcaster_twitch_user_id=broadcaster_id,
            name=name,
            response_message="Join our Discord server.",
            permission=CustomCommandPermission.SUBSCRIBER,
            cooldown_seconds=45,
            enabled=enabled,
        )

    async def test_create_list_and_lookup_enabled(
        self,
    ) -> None:
        created = await self.repository.create(
            self.command("Discord"),
            max_commands=5,
        )

        listed = await self.repository.list_commands("100")
        loaded = await self.repository.get_enabled_by_name(
            "100",
            "DISCORD",
        )

        self.assertIsNotNone(created.command_id)
        self.assertEqual(created.name, "discord")
        self.assertEqual(
            created.permission,
            CustomCommandPermission.SUBSCRIBER,
        )
        self.assertEqual(created.cooldown_seconds, 45)
        self.assertIsNotNone(created.created_at)
        self.assertEqual(listed, [created])
        self.assertEqual(loaded, created)

    async def test_duplicate_name_is_case_insensitive(
        self,
    ) -> None:
        await self.repository.create(
            self.command("discord"),
            max_commands=5,
        )

        with self.assertRaises(
            DuplicateCustomCommandNameError
        ):
            await self.repository.create(
                self.command("DISCORD"),
                max_commands=5,
            )

    async def test_limit_is_atomic_under_concurrency(
        self,
    ) -> None:
        results = await asyncio.gather(
            self.repository.create(
                self.command("first"),
                max_commands=1,
            ),
            self.repository.create(
                self.command("second"),
                max_commands=1,
            ),
            return_exceptions=True,
        )

        created_count = sum(
            isinstance(result, CustomCommand)
            for result in results
        )
        limit_errors = sum(
            isinstance(result, CustomCommandLimitError)
            for result in results
        )

        self.assertEqual(created_count, 1)
        self.assertEqual(limit_errors, 1)
        self.assertEqual(
            len(
                await self.repository.list_commands("100")
            ),
            1,
        )

    async def test_update_requires_matching_owner(
        self,
    ) -> None:
        created = await self.repository.create(
            self.command(),
            max_commands=5,
        )
        replacement = CustomCommand(
            command_id=created.command_id,
            broadcaster_twitch_user_id="300",
            name="edited",
            response_message="Edited response.",
            cooldown_seconds=30,
        )

        changed = await self.repository.update(replacement)
        loaded = await self.repository.get(
            created.command_id
        )

        self.assertFalse(changed)
        self.assertEqual(loaded.name, "discord")

    async def test_enable_and_delete_require_owner(
        self,
    ) -> None:
        created = await self.repository.create(
            self.command(enabled=False),
            max_commands=5,
        )

        self.assertIsNone(
            await self.repository.get_enabled_by_name(
                "100",
                "discord",
            )
        )
        self.assertFalse(
            await self.repository.set_enabled(
                created.command_id,
                "300",
                True,
            )
        )
        self.assertTrue(
            await self.repository.set_enabled(
                created.command_id,
                "100",
                True,
            )
        )
        self.assertFalse(
            await self.repository.delete(
                created.command_id,
                "300",
            )
        )
        self.assertTrue(
            await self.repository.delete(
                created.command_id,
                "100",
            )
        )
        self.assertIsNone(
            await self.repository.get(created.command_id)
        )


if __name__ == "__main__":
    unittest.main()
