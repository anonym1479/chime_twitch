from dataclasses import dataclass
from datetime import datetime, timezone

from chimebuddy.database import Database


@dataclass(frozen=True, slots=True)
class RewardActionLog:
    redemption_id: str
    broadcaster_twitch_user_id: str
    user_login: str
    outcome: str
    action: str
    occurred_at: str


class RewardActionLogRepository:
    """SQLite outbox: only completed Twitch actions are queued for Discord."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_success(self, *, redemption_id: str, broadcaster_twitch_user_id: str,
                             user_login: str, outcome: str, action: str) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """INSERT INTO reward_action_logs (
                    redemption_id, broadcaster_twitch_user_id, user_login,
                    outcome, action, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (redemption_id, broadcaster_twitch_user_id, user_login,
                 outcome, action, datetime.now(timezone.utc).isoformat()),
            )
            await connection.commit()

    async def list_undelivered(self) -> list[RewardActionLog]:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """SELECT redemption_id, broadcaster_twitch_user_id, user_login,
                outcome, action, occurred_at FROM reward_action_logs
                WHERE delivered_at IS NULL ORDER BY log_id"""
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [RewardActionLog(**dict(row)) for row in rows]

    async def mark_delivered(self, redemption_id: str) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                "UPDATE reward_action_logs SET delivered_at = CURRENT_TIMESTAMP WHERE redemption_id = ?",
                (redemption_id,),
            )
            await connection.commit()

    async def get_thread_id(self, broadcaster_twitch_user_id: str) -> str | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                "SELECT discord_thread_id FROM reward_discord_threads WHERE broadcaster_twitch_user_id = ?",
                (broadcaster_twitch_user_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return None if row is None else str(row["discord_thread_id"])

    async def save_thread_id(self, broadcaster_twitch_user_id: str, thread_id: str) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """INSERT INTO reward_discord_threads (broadcaster_twitch_user_id, discord_thread_id)
                VALUES (?, ?) ON CONFLICT(broadcaster_twitch_user_id) DO UPDATE SET
                discord_thread_id = excluded.discord_thread_id""",
                (broadcaster_twitch_user_id, thread_id),
            )
            await connection.commit()
