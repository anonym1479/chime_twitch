from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLink,
    AccountLinkStatus,
    Broadcaster,
    BroadcasterProfile,
    DiscordAccount,
    TwitchAccount,
)
from chimebuddy.repositories.errors import (
    AccountLinkNotVerifiedError,
)


class IdentityRepository:
    """Stores identities, verified links and broadcasters."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def save_twitch_account(
        self,
        account: TwitchAccount,
    ) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO twitch_accounts (
                    twitch_user_id,
                    login,
                    display_name
                )
                VALUES (?, ?, ?)
                ON CONFLICT(twitch_user_id) DO UPDATE SET
                    login = excluded.login,
                    display_name = excluded.display_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    account.twitch_user_id,
                    account.login,
                    account.display_name,
                ),
            )
            await connection.commit()

    async def save_discord_account(
        self,
        account: DiscordAccount,
    ) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO discord_accounts (
                    discord_user_id,
                    username,
                    display_name
                )
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    account.discord_user_id,
                    account.username,
                    account.display_name,
                ),
            )
            await connection.commit()

    async def save_account_link(
        self,
        link: AccountLink,
    ) -> None:
        async with self.database.connect() as connection:
            await connection.execute(
                """
                INSERT INTO account_links (
                    twitch_user_id,
                    discord_user_id,
                    status,
                    verification_method,
                    verified_at,
                    revoked_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    CASE
                        WHEN ? = 'verified'
                        THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END,
                    CASE
                        WHEN ? = 'revoked'
                        THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END
                )
                ON CONFLICT(twitch_user_id) DO UPDATE SET
                    discord_user_id = excluded.discord_user_id,
                    status = excluded.status,
                    verification_method =
                        excluded.verification_method,
                    verified_at = CASE
                        WHEN excluded.status = 'verified'
                        THEN COALESCE(
                            account_links.verified_at,
                            CURRENT_TIMESTAMP
                        )
                        ELSE NULL
                    END,
                    revoked_at = CASE
                        WHEN excluded.status = 'revoked'
                        THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END
                """,
                (
                    link.twitch_user_id,
                    link.discord_user_id,
                    link.status.value,
                    link.verification_method,
                    link.status.value,
                    link.status.value,
                ),
            )
            await connection.commit()

    async def get_account_link(
        self,
        twitch_user_id: str,
    ) -> AccountLink | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT
                    twitch_user_id,
                    discord_user_id,
                    status,
                    verification_method
                FROM account_links
                WHERE twitch_user_id = ?
                """,
                (str(twitch_user_id).strip(),),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return AccountLink(
            twitch_user_id=row["twitch_user_id"],
            discord_user_id=row["discord_user_id"],
            status=AccountLinkStatus(
                row["status"]
            ),
            verification_method=(
                row["verification_method"]
            ),
        )

    async def save_broadcaster(
        self,
        broadcaster: Broadcaster,
    ) -> None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT status
                FROM account_links
                WHERE twitch_user_id = ?
                  AND discord_user_id = ?
                """,
                (
                    broadcaster.twitch_user_id,
                    broadcaster.owner_discord_user_id,
                ),
            )

            link_row = await cursor.fetchone()
            await cursor.close()

            if (
                link_row is None
                or link_row["status"]
                != AccountLinkStatus.VERIFIED.value
            ):
                raise AccountLinkNotVerifiedError(
                    "The Twitch and Discord accounts must be "
                    "verified before creating a broadcaster."
                )

            await connection.execute(
                """
                INSERT INTO broadcasters (
                    twitch_user_id,
                    owner_discord_user_id,
                    enabled
                )
                VALUES (?, ?, ?)
                ON CONFLICT(twitch_user_id) DO UPDATE SET
                    owner_discord_user_id =
                        excluded.owner_discord_user_id,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    broadcaster.twitch_user_id,
                    broadcaster.owner_discord_user_id,
                    int(broadcaster.enabled),
                ),
            )

            await connection.commit()

    async def get_broadcaster(
        self,
        twitch_user_id: str,
    ) -> BroadcasterProfile | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT
                    broadcasters.twitch_user_id,
                    broadcasters.owner_discord_user_id,
                    broadcasters.enabled,
                    twitch_accounts.login AS twitch_login,
                    twitch_accounts.display_name
                        AS twitch_display_name,
                    discord_accounts.username
                        AS owner_discord_username,
                    discord_accounts.display_name
                        AS owner_discord_display_name,
                    account_links.status AS link_status
                FROM broadcasters
                JOIN twitch_accounts
                    ON twitch_accounts.twitch_user_id =
                       broadcasters.twitch_user_id
                JOIN discord_accounts
                    ON discord_accounts.discord_user_id =
                       broadcasters.owner_discord_user_id
                JOIN account_links
                    ON account_links.twitch_user_id =
                       broadcasters.twitch_user_id
                   AND account_links.discord_user_id =
                       broadcasters.owner_discord_user_id
                WHERE broadcasters.twitch_user_id = ?
                """,
                (str(twitch_user_id),),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._profile_from_row(row)

    async def list_broadcasters(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[BroadcasterProfile]:
        where_clause = (
            "WHERE broadcasters.enabled = 1"
            if enabled_only
            else ""
        )

        query = f"""
            SELECT
                broadcasters.twitch_user_id,
                broadcasters.owner_discord_user_id,
                broadcasters.enabled,
                twitch_accounts.login AS twitch_login,
                twitch_accounts.display_name
                    AS twitch_display_name,
                discord_accounts.username
                    AS owner_discord_username,
                discord_accounts.display_name
                    AS owner_discord_display_name,
                account_links.status AS link_status
            FROM broadcasters
            JOIN twitch_accounts
                ON twitch_accounts.twitch_user_id =
                   broadcasters.twitch_user_id
            JOIN discord_accounts
                ON discord_accounts.discord_user_id =
                   broadcasters.owner_discord_user_id
            JOIN account_links
                ON account_links.twitch_user_id =
                   broadcasters.twitch_user_id
               AND account_links.discord_user_id =
                   broadcasters.owner_discord_user_id
            {where_clause}
            ORDER BY twitch_accounts.login COLLATE NOCASE
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(query)
            rows = await cursor.fetchall()
            await cursor.close()

        return [
            self._profile_from_row(row)
            for row in rows
        ]

    async def set_broadcaster_enabled(
        self,
        twitch_user_id: str,
        enabled: bool,
    ) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE broadcasters
                SET
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE twitch_user_id = ?
                """,
                (
                    int(enabled),
                    str(twitch_user_id),
                ),
            )

            changed = cursor.rowcount > 0
            await cursor.close()
            await connection.commit()

        return changed

    @staticmethod
    def _profile_from_row(row) -> BroadcasterProfile:
        return BroadcasterProfile(
            twitch_user_id=row["twitch_user_id"],
            twitch_login=row["twitch_login"],
            twitch_display_name=row["twitch_display_name"],
            owner_discord_user_id=(
                row["owner_discord_user_id"]
            ),
            owner_discord_username=(
                row["owner_discord_username"]
            ),
            owner_discord_display_name=(
                row["owner_discord_display_name"]
            ),
            enabled=bool(row["enabled"]),
            link_status=AccountLinkStatus(
                row["link_status"]
            ),
        )