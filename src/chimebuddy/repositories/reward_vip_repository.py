from chimebuddy.database import Database
from chimebuddy.models.ban_or_vip import RewardVipGrant


class RewardVipRepository:
    """Tracks only VIP grants created by Ban or VIP."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, grant: RewardVipGrant) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO reward_vip_grants (
                    redemption_id, broadcaster_twitch_user_id,
                    user_twitch_user_id, expires_at, active
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    grant.redemption_id,
                    grant.broadcaster_twitch_user_id,
                    grant.user_twitch_user_id,
                    grant.expires_at,
                    int(grant.active),
                ),
            )
            await connection.commit()

    async def list_expired_active(self, now: int) -> list[RewardVipGrant]:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM reward_vip_grants
                WHERE active = 1 AND expires_at <= ?
                ORDER BY expires_at, redemption_id
                """,
                (now,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._from_row(row) for row in rows]

    async def deactivate(self, redemption_id: str) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE reward_vip_grants
                SET active = 0, removed_at = CURRENT_TIMESTAMP
                WHERE redemption_id = ? AND active = 1
                """,
                (str(redemption_id).strip(),),
            )
            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()
        return changed

    @staticmethod
    def _from_row(row) -> RewardVipGrant:
        return RewardVipGrant(
            redemption_id=row["redemption_id"],
            broadcaster_twitch_user_id=row["broadcaster_twitch_user_id"],
            user_twitch_user_id=row["user_twitch_user_id"],
            expires_at=int(row["expires_at"]),
            active=bool(row["active"]),
        )
