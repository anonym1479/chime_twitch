from chimebuddy.models import (
    CustomCommand,
    CustomCommandPermission,
)
from chimebuddy.repositories import (
    CustomCommandLimitError,
    CustomCommandRepository,
    DuplicateCustomCommandNameError,
    IdentityRepository,
)
from chimebuddy.services.twitch_command_router import (
    CORE_TWITCH_COMMAND_NAMES,
)


DEFAULT_MAX_CUSTOM_COMMANDS = 50
MAX_CUSTOM_COMMAND_NAME_LENGTH = 25
MAX_CUSTOM_COMMAND_RESPONSE_LENGTH = 450
MIN_CUSTOM_COMMAND_COOLDOWN_SECONDS = 5
MAX_CUSTOM_COMMAND_COOLDOWN_SECONDS = 3600


class CustomCommandManagementError(RuntimeError):
    """Base error for custom-command management."""


class ManagedCustomCommandNotFoundError(
    CustomCommandManagementError
):
    """Raised when an owned custom command is unavailable."""


class CustomCommandLimitReachedError(
    CustomCommandManagementError
):
    """Raised when a broadcaster has too many commands."""


class CustomCommandValidationError(
    CustomCommandManagementError
):
    """Raised when custom-command input is invalid."""


class CustomCommandNameConflictError(
    CustomCommandManagementError
):
    """Raised when an owned command name is duplicated."""


class ReservedCustomCommandNameError(
    CustomCommandValidationError
):
    """Raised when a protected core command name is used."""


class ManagedCustomCommandBroadcasterNotFoundError(
    CustomCommandManagementError
):
    """Raised when command management has no broadcaster."""


class CustomCommandManagementService:
    """Safely manages broadcaster custom Twitch commands."""

    def __init__(
        self,
        *,
        command_repository: CustomCommandRepository,
        identity_repository: IdentityRepository,
        max_commands: int = DEFAULT_MAX_CUSTOM_COMMANDS,
        reserved_names: frozenset[str] = (
            CORE_TWITCH_COMMAND_NAMES
        ),
    ) -> None:
        parsed_max_commands = int(max_commands)

        if parsed_max_commands <= 0:
            raise ValueError(
                "max_commands must be positive."
            )

        self.command_repository = command_repository
        self.identity_repository = identity_repository
        self.max_commands = parsed_max_commands
        self.reserved_names = frozenset(
            CustomCommand.normalize_name(name)
            for name in reserved_names
        )

    async def list_commands(
        self,
        broadcaster_twitch_user_id: str,
    ) -> list[CustomCommand]:
        broadcaster_id = await self._require_broadcaster(
            broadcaster_twitch_user_id
        )

        return await self.command_repository.list_commands(
            broadcaster_id
        )

    async def create_command(
        self,
        broadcaster_twitch_user_id: str,
        *,
        name: str,
        response_message: str,
        permission: CustomCommandPermission = (
            CustomCommandPermission.EVERYONE
        ),
        cooldown_seconds: int = 30,
        enabled: bool = True,
    ) -> CustomCommand:
        broadcaster_id = await self._require_broadcaster(
            broadcaster_twitch_user_id
        )
        command = self._build_command(
            broadcaster_id,
            name=name,
            response_message=response_message,
            permission=permission,
            cooldown_seconds=cooldown_seconds,
            enabled=enabled,
        )

        try:
            return await self.command_repository.create(
                command,
                max_commands=self.max_commands,
            )
        except DuplicateCustomCommandNameError as exc:
            raise CustomCommandNameConflictError(
                "A custom command with this name already "
                "exists."
            ) from exc
        except CustomCommandLimitError as exc:
            raise CustomCommandLimitReachedError(
                "This broadcaster has reached the limit "
                f"of {self.max_commands} custom commands."
            ) from exc

    async def update_command(
        self,
        broadcaster_twitch_user_id: str,
        command_id: int,
        *,
        name: str,
        response_message: str,
        permission: CustomCommandPermission,
        cooldown_seconds: int,
        enabled: bool,
    ) -> CustomCommand:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )
        current = await self._get_owned_command(
            broadcaster_id,
            command_id,
        )
        replacement = self._build_command(
            broadcaster_id,
            command_id=current.command_id,
            name=name,
            response_message=response_message,
            permission=permission,
            cooldown_seconds=cooldown_seconds,
            enabled=enabled,
        )

        try:
            changed = await self.command_repository.update(
                replacement
            )
        except DuplicateCustomCommandNameError as exc:
            raise CustomCommandNameConflictError(
                "A custom command with this name already "
                "exists."
            ) from exc

        if not changed:
            raise ManagedCustomCommandNotFoundError(
                "The custom command does not exist."
            )

        updated = await self.command_repository.get(
            current.command_id
        )

        if updated is None:
            raise ManagedCustomCommandNotFoundError(
                "The updated custom command could not be "
                "found."
            )

        return updated

    async def set_enabled(
        self,
        broadcaster_twitch_user_id: str,
        command_id: int,
        enabled: bool,
    ) -> CustomCommand:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )
        current = await self._get_owned_command(
            broadcaster_id,
            command_id,
        )
        desired = bool(enabled)

        if current.enabled is desired:
            return current

        changed = await self.command_repository.set_enabled(
            current.command_id,
            broadcaster_id,
            desired,
        )

        if not changed:
            raise ManagedCustomCommandNotFoundError(
                "The custom command could not be updated."
            )

        updated = await self.command_repository.get(
            current.command_id
        )

        if updated is None:
            raise ManagedCustomCommandNotFoundError(
                "The updated custom command could not be "
                "found."
            )

        return updated

    async def delete_command(
        self,
        broadcaster_twitch_user_id: str,
        command_id: int,
    ) -> None:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )
        command = await self._get_owned_command(
            broadcaster_id,
            command_id,
        )
        deleted = await self.command_repository.delete(
            command.command_id,
            broadcaster_id,
        )

        if not deleted:
            raise ManagedCustomCommandNotFoundError(
                "The custom command does not exist."
            )

    async def _require_broadcaster(
        self,
        broadcaster_twitch_user_id: str,
    ) -> str:
        broadcaster_id = self._required_id(
            broadcaster_twitch_user_id
        )
        broadcaster = (
            await self.identity_repository.get_broadcaster(
                broadcaster_id
            )
        )

        if broadcaster is None:
            raise ManagedCustomCommandBroadcasterNotFoundError(
                "The broadcaster does not exist."
            )

        return broadcaster_id

    async def _get_owned_command(
        self,
        broadcaster_twitch_user_id: str,
        command_id: int,
    ) -> CustomCommand:
        try:
            parsed_command_id = int(command_id)
        except (TypeError, ValueError) as exc:
            raise CustomCommandValidationError(
                "command_id must be an integer."
            ) from exc

        if parsed_command_id <= 0:
            raise CustomCommandValidationError(
                "command_id must be greater than zero."
            )

        command = await self.command_repository.get(
            parsed_command_id
        )

        if (
            command is None
            or command.broadcaster_twitch_user_id
            != broadcaster_twitch_user_id
        ):
            # Do not reveal another broadcaster's commands.
            raise ManagedCustomCommandNotFoundError(
                "The custom command does not exist."
            )

        return command

    def _build_command(
        self,
        broadcaster_twitch_user_id: str,
        *,
        name: str,
        response_message: str,
        permission: CustomCommandPermission,
        cooldown_seconds: int,
        enabled: bool,
        command_id: int | None = None,
    ) -> CustomCommand:
        cleaned_name = str(name).strip()

        if cleaned_name.startswith("_"):
            raise CustomCommandValidationError(
                "Enter the command name without the _ "
                "prefix."
            )

        if len(cleaned_name) > MAX_CUSTOM_COMMAND_NAME_LENGTH:
            raise CustomCommandValidationError(
                "name cannot exceed "
                f"{MAX_CUSTOM_COMMAND_NAME_LENGTH} "
                "characters."
            )

        cleaned_response = str(response_message).strip()

        if not cleaned_response:
            raise CustomCommandValidationError(
                "response_message cannot be empty."
            )

        if (
            len(cleaned_response)
            > MAX_CUSTOM_COMMAND_RESPONSE_LENGTH
        ):
            raise CustomCommandValidationError(
                "response_message cannot exceed "
                f"{MAX_CUSTOM_COMMAND_RESPONSE_LENGTH} "
                "characters."
            )

        if any(
            ord(character) < 32 or ord(character) == 127
            for character in cleaned_response
        ):
            raise CustomCommandValidationError(
                "response_message cannot contain control "
                "characters or line breaks."
            )

        try:
            normalized_permission = (
                CustomCommandPermission(permission)
            )
        except ValueError as exc:
            raise CustomCommandValidationError(
                "permission must be everyone, subscriber, "
                "vip, moderator, or broadcaster."
            ) from exc

        try:
            normalized_cooldown = int(cooldown_seconds)
        except (TypeError, ValueError) as exc:
            raise CustomCommandValidationError(
                "cooldown_seconds must be an integer."
            ) from exc

        if not (
            MIN_CUSTOM_COMMAND_COOLDOWN_SECONDS
            <= normalized_cooldown
            <= MAX_CUSTOM_COMMAND_COOLDOWN_SECONDS
        ):
            raise CustomCommandValidationError(
                "cooldown_seconds must be between "
                f"{MIN_CUSTOM_COMMAND_COOLDOWN_SECONDS} "
                "and "
                f"{MAX_CUSTOM_COMMAND_COOLDOWN_SECONDS}."
            )

        try:
            command = CustomCommand(
                command_id=command_id,
                broadcaster_twitch_user_id=(
                    broadcaster_twitch_user_id
                ),
                name=cleaned_name,
                response_message=cleaned_response,
                permission=normalized_permission,
                cooldown_seconds=normalized_cooldown,
                enabled=bool(enabled),
            )
        except (TypeError, ValueError) as exc:
            raise CustomCommandValidationError(
                str(exc)
            ) from exc

        if command.name in self.reserved_names:
            raise ReservedCustomCommandNameError(
                "This name belongs to a protected "
                "ChimeBuddy core command."
            )

        return command

    @staticmethod
    def _required_id(
        broadcaster_twitch_user_id: str,
    ) -> str:
        broadcaster_id = str(
            broadcaster_twitch_user_id
        ).strip()

        if not broadcaster_id:
            raise CustomCommandValidationError(
                "broadcaster_twitch_user_id cannot be "
                "empty."
            )

        return broadcaster_id
