import tempfile
import unittest
from pathlib import Path

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    CustomCommandPermission,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories import (
    CustomCommandRepository,
    IdentityRepository,
)
from chimebuddy.services import (
    CustomCommandLimitReachedError,
    CustomCommandManagementService,
    CustomCommandNameConflictError,
    CustomCommandValidationError,
    ManagedCustomCommandBroadcasterNotFoundError,
    ManagedCustomCommandNotFoundError,
    ReservedCustomCommandNameError,
)


class CustomCommandManagementServiceTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database = Database(
            Path(self.temp_directory.name) / "test.db"
        )
        await self.database.initialize()

        self.identity_repository = IdentityRepository(
            self.database
        )

        for twitch_id, discord_id, login in (
            ("100", "200", "streamer_one"),
            ("300", "400", "streamer_two"),
        ):
            await self.identity_repository.save_twitch_account(
                TwitchAccount(
                    twitch_user_id=twitch_id,
                    login=login,
                    display_name=login,
                )
            )
            await self.identity_repository.save_discord_account(
                DiscordAccount(
                    discord_user_id=discord_id,
                    username=f"user_{discord_id}",
                    display_name=f"User {discord_id}",
                )
            )
            await self.identity_repository.save_account_link(
                AccountLink(
                    twitch_user_id=twitch_id,
                    discord_user_id=discord_id,
                    status=AccountLinkStatus.VERIFIED,
                    verification_method="test",
                )
            )
            await self.identity_repository.save_broadcaster(
                Broadcaster(
                    twitch_user_id=twitch_id,
                    owner_discord_user_id=discord_id,
                )
            )

        self.repository = CustomCommandRepository(
            self.database
        )
        self.service = CustomCommandManagementService(
            command_repository=self.repository,
            identity_repository=self.identity_repository,
        )

    async def create_command(self, name="discord"):
        return await self.service.create_command(
            "100",
            name=name,
            response_message="Join our Discord server.",
            permission=CustomCommandPermission.SUBSCRIBER,
            cooldown_seconds=45,
        )

    async def test_creates_normalized_command(
        self,
    ) -> None:
        created = await self.service.create_command(
            "100",
            name="  Discord  ",
            response_message="  Join us!  ",
            permission=CustomCommandPermission.VIP,
            cooldown_seconds=60,
        )

        self.assertEqual(created.name, "discord")
        self.assertEqual(created.response_message, "Join us!")
        self.assertEqual(
            created.permission,
            CustomCommandPermission.VIP,
        )
        self.assertEqual(created.cooldown_seconds, 60)

    async def test_rejects_reserved_core_name(
        self,
    ) -> None:
        with self.assertRaises(
            ReservedCustomCommandNameError
        ):
            await self.create_command("V2PING")

    async def test_rejects_prefix_invalid_name_and_response(
        self,
    ) -> None:
        invalid_names = (
            "_discord",
            "two words",
            "árvíz",
            "!discord",
        )

        for name in invalid_names:
            with self.subTest(name=name), self.assertRaises(
                CustomCommandValidationError
            ):
                await self.create_command(name)

        with self.assertRaises(
            CustomCommandValidationError
        ):
            await self.service.create_command(
                "100",
                name="discord",
                response_message="Line one\nLine two",
            )

    async def test_validates_permission_and_cooldown(
        self,
    ) -> None:
        with self.assertRaises(
            CustomCommandValidationError
        ):
            await self.service.create_command(
                "100",
                name="discord",
                response_message="Join us!",
                permission="owner",
            )

        for cooldown in (4, 3601, "not-a-number"):
            with self.subTest(cooldown=cooldown), self.assertRaises(
                CustomCommandValidationError
            ):
                await self.service.create_command(
                    "100",
                    name="discord",
                    response_message="Join us!",
                    cooldown_seconds=cooldown,
                )

    async def test_duplicate_name_is_translated(
        self,
    ) -> None:
        await self.create_command()

        with self.assertRaises(
            CustomCommandNameConflictError
        ):
            await self.create_command("DISCORD")

    async def test_limit_is_translated(self) -> None:
        limited = CustomCommandManagementService(
            command_repository=self.repository,
            identity_repository=self.identity_repository,
            max_commands=1,
        )
        await limited.create_command(
            "100",
            name="first",
            response_message="First response.",
        )

        with self.assertRaises(
            CustomCommandLimitReachedError
        ):
            await limited.create_command(
                "100",
                name="second",
                response_message="Second response.",
            )

    async def test_update_enable_and_delete(self) -> None:
        created = await self.create_command()
        updated = await self.service.update_command(
            "100",
            created.command_id,
            name="community",
            response_message="Community link.",
            permission=CustomCommandPermission.MODERATOR,
            cooldown_seconds=120,
            enabled=False,
        )

        self.assertEqual(updated.name, "community")
        self.assertFalse(updated.enabled)
        self.assertEqual(
            updated.permission,
            CustomCommandPermission.MODERATOR,
        )

        enabled = await self.service.set_enabled(
            "100",
            created.command_id,
            True,
        )
        self.assertTrue(enabled.enabled)

        await self.service.delete_command(
            "100",
            created.command_id,
        )
        self.assertIsNone(
            await self.repository.get(created.command_id)
        )

    async def test_other_broadcaster_cannot_manage_command(
        self,
    ) -> None:
        created = await self.create_command()

        with self.assertRaises(
            ManagedCustomCommandNotFoundError
        ):
            await self.service.set_enabled(
                "300",
                created.command_id,
                False,
            )

        loaded = await self.repository.get(
            created.command_id
        )
        self.assertTrue(loaded.enabled)

    async def test_unknown_broadcaster_cannot_create(
        self,
    ) -> None:
        with self.assertRaises(
            ManagedCustomCommandBroadcasterNotFoundError
        ):
            await self.service.create_command(
                "unknown",
                name="discord",
                response_message="Join us!",
            )


if __name__ == "__main__":
    unittest.main()
