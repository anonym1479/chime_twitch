import aiosqlite

from chimebuddy.database import Database
from chimebuddy.models import (
    CustomCommand,
    CustomCommandPermission,
)
from chimebuddy.repositories.errors import (
    CustomCommandLimitError,
    DuplicateCustomCommandNameError,
)


class CustomCommandRepository:
    """Stores broadcaster-owned custom Twitch commands."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        command: CustomCommand,
        *,
        max_commands: int,
    ) -> CustomCommand:
        if command.command_id is not None:
            raise ValueError(
                "A new custom command cannot already "
                "have a command_id."
            )

        if (
            command.created_at is not None
            or command.updated_at is not None
        ):
            raise ValueError(
                "A new custom command cannot already "
                "contain database timestamps."
            )

        parsed_limit = int(max_commands)

        if parsed_limit <= 0:
            raise ValueError(
                "max_commands must be positive."
            )

        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                cursor = await connection.execute(
                    """
                    SELECT COUNT(*) AS command_count
                    FROM custom_commands
                    WHERE broadcaster_twitch_user_id = ?
                    """,
                    (
                        command.broadcaster_twitch_user_id,
                    ),
                )
                count_row = await cursor.fetchone()
                await cursor.close()

                if int(count_row["command_count"]) >= parsed_limit:
                    raise CustomCommandLimitError(
                        "This broadcaster has reached its "
                        "custom-command limit."
                    )

                cursor = await connection.execute(
                    """
                    INSERT INTO custom_commands (
                        broadcaster_twitch_user_id,
                        name,
                        response_message,
                        permission,
                        cooldown_seconds,
                        enabled
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        command.broadcaster_twitch_user_id,
                        command.name,
                        command.response_message,
                        command.permission.value,
                        command.cooldown_seconds,
                        int(command.enabled),
                    ),
                )
                command_id = cursor.lastrowid
                await cursor.close()

                if command_id is None:
                    raise RuntimeError(
                        "SQLite did not return a custom "
                        "command ID."
                    )

                row = await self._fetch_row(
                    connection,
                    int(command_id),
                )
                await connection.commit()

            except aiosqlite.IntegrityError as exc:
                await connection.rollback()
                self._raise_integrity_error(exc)

            except Exception:
                if connection.in_transaction:
                    await connection.rollback()
                raise

        if row is None:
            raise RuntimeError(
                "The created custom command could not "
                "be loaded."
            )

        return self._from_row(row)

    async def get(
        self,
        command_id: int,
    ) -> CustomCommand | None:
        async with self.database.connect() as connection:
            row = await self._fetch_row(
                connection,
                int(command_id),
            )

        if row is None:
            return None

        return self._from_row(row)

    async def get_enabled_by_name(
        self,
        broadcaster_twitch_user_id: str,
        name: str,
    ) -> CustomCommand | None:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        normalized_name = CustomCommand.normalize_name(
            name
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM custom_commands
                WHERE broadcaster_twitch_user_id = ?
                  AND name = ? COLLATE NOCASE
                  AND enabled = 1
                """,
                (
                    broadcaster_id,
                    normalized_name,
                ),
            )
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._from_row(row)

    async def list_commands(
        self,
        broadcaster_twitch_user_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[CustomCommand]:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )
        enabled_filter = (
            "AND enabled = 1"
            if enabled_only
            else ""
        )

        query = f"""
            SELECT *
            FROM custom_commands
            WHERE broadcaster_twitch_user_id = ?
            {enabled_filter}
            ORDER BY name COLLATE NOCASE, command_id
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                query,
                (broadcaster_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()

        return [self._from_row(row) for row in rows]

    async def update(
        self,
        command: CustomCommand,
    ) -> bool:
        if command.command_id is None:
            raise ValueError(
                "A stored custom command ID is required."
            )

        async with self.database.connect() as connection:
            try:
                cursor = await connection.execute(
                    """
                    UPDATE custom_commands
                    SET
                        name = ?,
                        response_message = ?,
                        permission = ?,
                        cooldown_seconds = ?,
                        enabled = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE command_id = ?
                      AND broadcaster_twitch_user_id = ?
                    """,
                    (
                        command.name,
                        command.response_message,
                        command.permission.value,
                        command.cooldown_seconds,
                        int(command.enabled),
                        command.command_id,
                        command.broadcaster_twitch_user_id,
                    ),
                )
                changed = cursor.rowcount == 1
                await cursor.close()
                await connection.commit()
                return changed

            except aiosqlite.IntegrityError as exc:
                await connection.rollback()
                self._raise_integrity_error(exc)

            except Exception:
                if connection.in_transaction:
                    await connection.rollback()
                raise

    async def set_enabled(
        self,
        command_id: int,
        broadcaster_twitch_user_id: str,
        enabled: bool,
    ) -> bool:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE custom_commands
                SET
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE command_id = ?
                  AND broadcaster_twitch_user_id = ?
                """,
                (
                    int(enabled),
                    int(command_id),
                    broadcaster_id,
                ),
            )
            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    async def delete(
        self,
        command_id: int,
        broadcaster_twitch_user_id: str,
    ) -> bool:
        broadcaster_id = self._required_text(
            broadcaster_twitch_user_id,
            "broadcaster_twitch_user_id",
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM custom_commands
                WHERE command_id = ?
                  AND broadcaster_twitch_user_id = ?
                """,
                (
                    int(command_id),
                    broadcaster_id,
                ),
            )
            deleted = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return deleted

    @staticmethod
    async def _fetch_row(connection, command_id: int):
        cursor = await connection.execute(
            """
            SELECT *
            FROM custom_commands
            WHERE command_id = ?
            """,
            (command_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row

    @staticmethod
    def _from_row(row) -> CustomCommand:
        return CustomCommand(
            command_id=row["command_id"],
            broadcaster_twitch_user_id=(
                row["broadcaster_twitch_user_id"]
            ),
            name=row["name"],
            response_message=row["response_message"],
            permission=CustomCommandPermission(
                row["permission"]
            ),
            cooldown_seconds=row["cooldown_seconds"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _raise_integrity_error(
        error: aiosqlite.IntegrityError,
    ) -> None:
        error_text = str(error)

        if (
            "custom_commands.broadcaster_twitch_user_id"
            in error_text
            and "custom_commands.name" in error_text
        ) or (
            "custom_commands_broadcaster_name_nocase_idx"
            in error_text
        ):
            raise DuplicateCustomCommandNameError(
                "This broadcaster already has a custom "
                "command with that name."
            ) from error

        raise error

    @staticmethod
    def _required_text(
        value: object,
        field_name: str,
    ) -> str:
        cleaned = str(value).strip()

        if not cleaned:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return cleaned
