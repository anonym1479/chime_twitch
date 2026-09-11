from dataclasses import dataclass

from chimebuddy.database import Database


@dataclass(frozen=True, slots=True)
class BanOrVipUserSettings:
    broadcaster_twitch_user_id: str
    user_twitch_user_id: str
    vip_chance: float


class BanOrVipUserSettingsRepository:
    """Stores per-user Ban or VIP odds."""

    DEFAULT_VIP_CHANCE = 50.0

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
    ) -> float:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT vip_chance
                FROM ban_or_vip_user_settings
                WHERE broadcaster_twitch_user_id = ?
                  AND user_twitch_user_id = ?
                """,
                (
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                ),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return self.DEFAULT_VIP_CHANCE

        return float(row["vip_chance"])

    async def set(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
        vip_chance: float,
    ) -> None:
        vip_chance = float(vip_chance)

        if not 0.0 <= vip_chance <= 100.0:
            raise ValueError(
                "vip_chance must be between 0.0 and 100.0."
            )

        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO ban_or_vip_user_settings (
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                    vip_chance
                )
                VALUES (?, ?, ?)
                ON CONFLICT(
                    broadcaster_twitch_user_id,
                    user_twitch_user_id
                ) DO UPDATE SET
                    vip_chance = excluded.vip_chance,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                    vip_chance,
                ),
            )

            await connection.commit()

    async def delete(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
    ) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM ban_or_vip_user_settings
                WHERE broadcaster_twitch_user_id = ?
                  AND user_twitch_user_id = ?
                """,
                (
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                ),
            )

            deleted = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return deleted