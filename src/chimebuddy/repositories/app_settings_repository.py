from chimebuddy.database import Database


class AppSettingsRepository:
    """Stores small persistent application settings."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def set(
        self,
        key: str,
        value: str,
    ) -> None:
        setting_key = self._required_text(
            key,
            "key",
        )
        setting_value = self._required_text(
            value,
            "value",
        )

        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO app_settings (
                    key,
                    value
                )
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    setting_key,
                    setting_value,
                ),
            )

            await connection.commit()

    async def get(
        self,
        key: str,
    ) -> str | None:
        setting_key = self._required_text(
            key,
            "key",
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT value
                FROM app_settings
                WHERE key = ?
                """,
                (setting_key,),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return row["value"]

    async def get_positive_int(
        self,
        key: str,
    ) -> int | None:
        value = await self.get(key)

        if value is None:
            return None

        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(
                f"Stored setting {key!r} must be "
                "a numeric ID."
            ) from exc

        if parsed <= 0:
            raise ValueError(
                f"Stored setting {key!r} must be "
                "greater than zero."
            )

        return parsed

    async def delete(
        self,
        key: str,
    ) -> bool:
        setting_key = self._required_text(
            key,
            "key",
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM app_settings
                WHERE key = ?
                """,
                (setting_key,),
            )

            deleted = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return deleted

    @staticmethod
    def _required_text(
        value: str,
        field_name: str,
    ) -> str:
        cleaned = str(value).strip()

        if not cleaned:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        return cleaned