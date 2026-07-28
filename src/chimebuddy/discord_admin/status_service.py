from dataclasses import dataclass

from chimebuddy.repositories import IdentityRepository


@dataclass(frozen=True, slots=True)
class DiscordAdminStatus:
    total_broadcasters: int
    enabled_broadcasters: int

    @property
    def disabled_broadcasters(self) -> int:
        return (
            self.total_broadcasters
            - self.enabled_broadcasters
        )

    def render(self) -> str:
        return (
            "**ChimeBuddy V2 status**\n"
            "Discord administration bot: online\n"
            "Database: connected\n"
            f"Broadcasters: {self.total_broadcasters}\n"
            f"Enabled: {self.enabled_broadcasters}\n"
            f"Disabled: {self.disabled_broadcasters}"
        )


class DiscordAdminStatusService:
    """Reads safe status information from SQLite."""

    def __init__(
        self,
        identity_repository: IdentityRepository,
    ) -> None:
        self.identity_repository = identity_repository

    async def get_status(
        self,
    ) -> DiscordAdminStatus:
        broadcasters = (
            await self.identity_repository
            .list_broadcasters()
        )

        enabled_count = sum(
            1
            for broadcaster in broadcasters
            if broadcaster.enabled
        )

        return DiscordAdminStatus(
            total_broadcasters=len(broadcasters),
            enabled_broadcasters=enabled_count,
        )