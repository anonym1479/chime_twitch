import unittest
from dataclasses import replace

from chimebuddy.models import (
    AccountLinkStatus,
    BroadcasterProfile,
)
from chimebuddy.services import (
    BroadcasterLifecycleService,
    BroadcasterNotFoundError,
    BroadcasterResumeBlockedError,
)


def make_profile(
    *,
    enabled: bool = True,
) -> BroadcasterProfile:
    return BroadcasterProfile(
        twitch_user_id="456",
        twitch_login="example_streamer",
        twitch_display_name="Example Streamer",
        owner_discord_user_id="123",
        owner_discord_username="example_user",
        owner_discord_display_name="Example User",
        enabled=enabled,
        link_status=AccountLinkStatus.VERIFIED,
    )


class FakeIdentityRepository:
    def __init__(
        self,
        profile: BroadcasterProfile | None,
    ) -> None:
        self.profile = profile
        self.set_calls: list[tuple[str, bool]] = []

    async def get_broadcaster(
        self,
        twitch_user_id: str,
    ) -> BroadcasterProfile | None:
        if (
            self.profile is None
            or self.profile.twitch_user_id
            != twitch_user_id
        ):
            return None

        return self.profile

    async def set_broadcaster_enabled(
        self,
        twitch_user_id: str,
        enabled: bool,
    ) -> bool:
        self.set_calls.append(
            (twitch_user_id, enabled)
        )

        if (
            self.profile is None
            or self.profile.twitch_user_id
            != twitch_user_id
        ):
            return False

        self.profile = replace(
            self.profile,
            enabled=enabled,
        )
        return True


class FakeCredentialRepository:
    def __init__(
        self,
        *,
        credential_exists: bool = True,
    ) -> None:
        self.credential_exists = credential_exists

    async def get(
        self,
        twitch_user_id,
        credential_kind,
    ):
        if not self.credential_exists:
            return None

        return object()


class BroadcasterLifecycleServiceTests(
    unittest.IsolatedAsyncioTestCase
):
    def create_service(
        self,
        *,
        enabled: bool = True,
        credential_exists: bool = True,
    ):
        identity_repository = (
            FakeIdentityRepository(
                make_profile(enabled=enabled)
            )
        )

        service = BroadcasterLifecycleService(
            identity_repository=(
                identity_repository
            ),
            credential_repository=(
                FakeCredentialRepository(
                    credential_exists=(
                        credential_exists
                    )
                )
            ),
        )

        return service, identity_repository

    async def test_pauses_broadcaster(self) -> None:
        service, repository = self.create_service()

        result = await service.pause("456")

        self.assertFalse(result.enabled)
        self.assertEqual(
            repository.set_calls,
            [("456", False)],
        )

    async def test_resumes_broadcaster(self) -> None:
        service, repository = self.create_service(
            enabled=False
        )

        result = await service.resume("456")

        self.assertTrue(result.enabled)
        self.assertEqual(
            repository.set_calls,
            [("456", True)],
        )

    async def test_repeated_pause_is_idempotent(
        self,
    ) -> None:
        service, repository = self.create_service(
            enabled=False
        )

        result = await service.pause("456")

        self.assertFalse(result.enabled)
        self.assertEqual(
            repository.set_calls,
            [],
        )

    async def test_resume_requires_authorization(
        self,
    ) -> None:
        service, repository = self.create_service(
            enabled=False,
            credential_exists=False,
        )

        with self.assertRaises(
            BroadcasterResumeBlockedError
        ):
            await service.resume("456")

        self.assertEqual(
            repository.set_calls,
            [],
        )

    async def test_unknown_broadcaster_is_rejected(
        self,
    ) -> None:
        service = BroadcasterLifecycleService(
            identity_repository=(
                FakeIdentityRepository(None)
            ),
            credential_repository=(
                FakeCredentialRepository()
            ),
        )

        with self.assertRaises(
            BroadcasterNotFoundError
        ):
            await service.pause("unknown")


if __name__ == "__main__":
    unittest.main()