from dataclasses import dataclass

from chimebuddy.database import Database


@dataclass(frozen=True, slots=True)
class BanOrVipCustomOdds:
    broadcaster_twitch_user_id: str
    user_twitch_user_id: str
    vip_probability: int


class BanOrVipOddsRepository:
    """Stores per-user Ban or VIP odds per broadcaster."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
    ) -> int | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT vip_probability
                FROM ban_or_vip_custom_odds
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
            return None

        return int(row["vip_probability"])

    async def set(
        self,
        broadcaster_twitch_user_id: str,
        user_twitch_user_id: str,
        vip_probability: int,
    ) -> None:
        if not 0 <= vip_probability <= 100:
            raise ValueError(
                "vip_probability must be between 0 and 100."
            )

        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO ban_or_vip_custom_odds (
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                    vip_probability
                )
                VALUES (?, ?, ?)
                ON CONFLICT(
                    broadcaster_twitch_user_id,
                    user_twitch_user_id
                ) DO UPDATE SET
                    vip_probability = excluded.vip_probability,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                    vip_probability,
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
                DELETE FROM ban_or_vip_custom_odds
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

    async def list_for_broadcaster(
        self,
        broadcaster_twitch_user_id: str,
    ) -> list[BanOrVipCustomOdds]:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT
                    broadcaster_twitch_user_id,
                    user_twitch_user_id,
                    vip_probability
                FROM ban_or_vip_custom_odds
                WHERE broadcaster_twitch_user_id = ?
                ORDER BY user_twitch_user_id
                """,
                (broadcaster_twitch_user_id,),
            )

            rows = await cursor.fetchall()
            await cursor.close()

        return [
            BanOrVipCustomOdds(
                broadcaster_twitch_user_id=str(
                    row["broadcaster_twitch_user_id"]
                ),
                user_twitch_user_id=str(
                    row["user_twitch_user_id"]
                ),
                vip_probability=int(row["vip_probability"]),
            )
            for row in rows
        ]