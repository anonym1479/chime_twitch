import aiosqlite

from chimebuddy.database import Database
from chimebuddy.models import BroadcasterPanel
from chimebuddy.repositories.errors import (
    BroadcasterPanelExistsError,
)


class BroadcasterPanelRepository:
    """Stores private Discord channel locations for broadcasters."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        panel: BroadcasterPanel,
    ) -> BroadcasterPanel:
        if (
            panel.created_at is not None
            or panel.updated_at is not None
        ):
            raise ValueError(
                "A new broadcaster panel cannot already "
                "contain database timestamps."
            )

        async with self.database.connect() as connection:
            try:
                await connection.execute(
                    """
                    INSERT INTO broadcaster_panels (
                        twitch_user_id,
                        request_id,
                        discord_guild_id,
                        discord_channel_id,
                        opening_message_id
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        panel.twitch_user_id,
                        panel.request_id,
                        panel.discord_guild_id,
                        panel.discord_channel_id,
                        panel.opening_message_id,
                    ),
                )

                row = await self._fetch_by_twitch_id(
                    connection,
                    panel.twitch_user_id,
                )

                await connection.commit()

            except aiosqlite.IntegrityError as exc:
                await connection.rollback()

                error_text = str(exc)

                if (
                    "broadcaster_panels.twitch_user_id"
                    in error_text
                    or
                    "broadcaster_panels.request_id"
                    in error_text
                    or
                    "broadcaster_panels.discord_channel_id"
                    in error_text
                ):
                    raise BroadcasterPanelExistsError(
                        "This broadcaster, request, or Discord "
                        "channel already has a stored panel."
                    ) from exc

                raise

        if row is None:
            raise RuntimeError(
                "The created broadcaster panel "
                "could not be loaded."
            )

        return self._from_row(row)

    async def get_for_broadcaster(
        self,
        twitch_user_id: str,
    ) -> BroadcasterPanel | None:
        async with self.database.connect() as connection:
            row = await self._fetch_by_twitch_id(
                connection,
                str(twitch_user_id).strip(),
            )

        if row is None:
            return None

        return self._from_row(row)

    async def get_for_channel(
        self,
        discord_channel_id: str,
    ) -> BroadcasterPanel | None:
        channel_id = str(
            discord_channel_id
        ).strip()

        if not channel_id:
            raise ValueError(
                "discord_channel_id cannot be empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM broadcaster_panels
                WHERE discord_channel_id = ?
                """,
                (channel_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._from_row(row)

    async def set_opening_message(
        self,
        twitch_user_id: str,
        opening_message_id: str,
    ) -> bool:
        twitch_id = str(twitch_user_id).strip()
        message_id = str(
            opening_message_id
        ).strip()

        if not twitch_id:
            raise ValueError(
                "twitch_user_id cannot be empty."
            )

        if not message_id:
            raise ValueError(
                "opening_message_id cannot be empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE broadcaster_panels
                SET
                    opening_message_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE twitch_user_id = ?
                """,
                (
                    message_id,
                    twitch_id,
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    async def delete(
        self,
        twitch_user_id: str,
    ) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM broadcaster_panels
                WHERE twitch_user_id = ?
                """,
                (str(twitch_user_id).strip(),),
            )

            deleted = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return deleted

    @staticmethod
    async def _fetch_by_twitch_id(
        connection,
        twitch_user_id: str,
    ):
        cursor = await connection.execute(
            """
            SELECT *
            FROM broadcaster_panels
            WHERE twitch_user_id = ?
            """,
            (twitch_user_id,),
        )

        row = await cursor.fetchone()
        await cursor.close()
        return row

    @staticmethod
    def _from_row(row) -> BroadcasterPanel:
        return BroadcasterPanel(
            twitch_user_id=row["twitch_user_id"],
            request_id=row["request_id"],
            discord_guild_id=row["discord_guild_id"],
            discord_channel_id=(
                row["discord_channel_id"]
            ),
            opening_message_id=(
                row["opening_message_id"]
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )