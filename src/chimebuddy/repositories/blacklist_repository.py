import aiosqlite

from chimebuddy.database import Database
from chimebuddy.models import (
    BroadcasterBlacklistEntry,
)
from chimebuddy.repositories.errors import (
    ActiveBlacklistEntryError,
)


class BroadcasterBlacklistRepository:
    """Stores durable Discord and Twitch blacklist entries."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        entry: BroadcasterBlacklistEntry,
    ) -> BroadcasterBlacklistEntry:
        if entry.blacklist_id is not None:
            raise ValueError(
                "A new blacklist entry cannot already "
                "have a blacklist_id."
            )

        if not entry.active:
            raise ValueError(
                "A new blacklist entry must be active."
            )

        if (
            entry.revoked_at is not None
            or entry.revoked_by_discord_user_id is not None
            or entry.revocation_reason is not None
        ):
            raise ValueError(
                "A new blacklist entry cannot already "
                "contain revocation information."
            )

        async with self.database.connect() as connection:
            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO broadcaster_blacklist (
                        discord_user_id,
                        twitch_user_id,
                        internal_reason,
                        requester_message,
                        created_by_discord_user_id,
                        active
                    )
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        entry.discord_user_id,
                        entry.twitch_user_id,
                        entry.internal_reason,
                        entry.requester_message,
                        entry.created_by_discord_user_id,
                    ),
                )

                blacklist_id = cursor.lastrowid
                await cursor.close()

                if blacklist_id is None:
                    raise RuntimeError(
                        "SQLite did not return a blacklist ID."
                    )

                row = await self._fetch_row(
                    connection,
                    int(blacklist_id),
                )

                await connection.commit()

            except aiosqlite.IntegrityError as exc:
                await connection.rollback()

                error_text = str(exc)

                if (
                    "broadcaster_blacklist.discord_user_id"
                    in error_text
                    or
                    "broadcaster_blacklist.twitch_user_id"
                    in error_text
                    or
                    "broadcaster_blacklist_active_discord_idx"
                    in error_text
                    or
                    "broadcaster_blacklist_active_twitch_idx"
                    in error_text
                ):
                    raise ActiveBlacklistEntryError(
                        "This Discord or Twitch identity "
                        "is already actively blacklisted."
                    ) from exc

                raise

        if row is None:
            raise RuntimeError(
                "The created blacklist entry "
                "could not be loaded."
            )

        return self._from_row(row)

    async def get(
        self,
        blacklist_id: int,
    ) -> BroadcasterBlacklistEntry | None:
        async with self.database.connect() as connection:
            row = await self._fetch_row(
                connection,
                int(blacklist_id),
            )

        if row is None:
            return None

        return self._from_row(row)

    async def find_active(
        self,
        *,
        discord_user_id: str | None = None,
        twitch_user_id: str | None = None,
    ) -> BroadcasterBlacklistEntry | None:
        discord_id = self._optional_text(
            discord_user_id
        )
        twitch_id = self._optional_text(
            twitch_user_id
        )

        if discord_id is None and twitch_id is None:
            raise ValueError(
                "A Discord user ID, Twitch user ID, "
                "or both must be supplied."
            )

        conditions = []
        parameters = []

        if discord_id is not None:
            conditions.append("discord_user_id = ?")
            parameters.append(discord_id)

        if twitch_id is not None:
            conditions.append("twitch_user_id = ?")
            parameters.append(twitch_id)

        query = f"""
            SELECT *
            FROM broadcaster_blacklist
            WHERE active = 1
              AND ({" OR ".join(conditions)})
            ORDER BY blacklist_id
            LIMIT 1
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                query,
                parameters,
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._from_row(row)

    async def list_active(
        self,
    ) -> list[BroadcasterBlacklistEntry]:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM broadcaster_blacklist
                WHERE active = 1
                ORDER BY created_at, blacklist_id
                """
            )

            rows = await cursor.fetchall()
            await cursor.close()

        return [
            self._from_row(row)
            for row in rows
        ]

    async def revoke(
        self,
        blacklist_id: int,
        *,
        revoked_by_discord_user_id: str,
        reason: str,
    ) -> bool:
        actor_id = self._required_text(
            revoked_by_discord_user_id,
            "revoked_by_discord_user_id",
        )
        revocation_reason = self._required_text(
            reason,
            "reason",
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE broadcaster_blacklist
                SET
                    active = 0,
                    revoked_at = CURRENT_TIMESTAMP,
                    revoked_by_discord_user_id = ?,
                    revocation_reason = ?
                WHERE blacklist_id = ?
                  AND active = 1
                """,
                (
                    actor_id,
                    revocation_reason,
                    int(blacklist_id),
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    @staticmethod
    async def _fetch_row(
        connection,
        blacklist_id: int,
    ):
        cursor = await connection.execute(
            """
            SELECT *
            FROM broadcaster_blacklist
            WHERE blacklist_id = ?
            """,
            (blacklist_id,),
        )

        row = await cursor.fetchone()
        await cursor.close()
        return row

    @staticmethod
    def _from_row(
        row,
    ) -> BroadcasterBlacklistEntry:
        return BroadcasterBlacklistEntry(
            blacklist_id=row["blacklist_id"],
            discord_user_id=row["discord_user_id"],
            twitch_user_id=row["twitch_user_id"],
            internal_reason=row["internal_reason"],
            requester_message=row["requester_message"],
            created_by_discord_user_id=(
                row["created_by_discord_user_id"]
            ),
            active=bool(row["active"]),
            created_at=row["created_at"],
            revoked_at=row["revoked_at"],
            revoked_by_discord_user_id=(
                row["revoked_by_discord_user_id"]
            ),
            revocation_reason=(
                row["revocation_reason"]
            ),
        )

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

    @staticmethod
    def _optional_text(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = str(value).strip()
        return cleaned or None