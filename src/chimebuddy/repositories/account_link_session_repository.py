import json
import time

import aiosqlite

from chimebuddy.database import Database
from chimebuddy.models import (
    AccountLinkSession,
    AccountLinkSessionStatus,
)
from chimebuddy.repositories.errors import (
    PendingAccountLinkSessionError,
)


class AccountLinkSessionRepository:
    """Stores temporary Discord-to-Twitch linking sessions."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        session: AccountLinkSession,
    ) -> None:
        if (
            session.status
            is not AccountLinkSessionStatus.PENDING
        ):
            raise ValueError(
                "A new account-link session must be pending."
            )

        if session.completed_at is not None:
            raise ValueError(
                "A new account-link session cannot already "
                "be completed."
            )

        scopes_json = json.dumps(
            session.requested_scopes,
            separators=(",", ":"),
        )

        async with self.database.connect() as connection:
            # Remove an expired pending session from the unique
            # pending slot before creating a replacement.
            await connection.execute(
                """
                UPDATE account_link_sessions
                SET
                    status = 'expired',
                    completed_at = CURRENT_TIMESTAMP
                WHERE discord_user_id = ?
                  AND status = 'pending'
                  AND expires_at <= ?
                """,
                (
                    session.discord_user_id,
                    int(time.time()),
                ),
            )

            try:
                await connection.execute(
                    """
                    INSERT INTO account_link_sessions (
                        session_id,
                        discord_user_id,
                        twitch_user_id,
                        status,
                        requested_scopes_json,
                        expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.discord_user_id,
                        session.twitch_user_id,
                        session.status.value,
                        scopes_json,
                        session.expires_at,
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                await connection.rollback()

                error_text = str(exc)

                if (
                    "account_link_sessions.discord_user_id"
                    in error_text
                    or
                    "account_link_sessions_pending_discord_idx"
                    in error_text
                ):
                    raise PendingAccountLinkSessionError(
                        "This Discord account already has a "
                        "pending Twitch-link session."
                    ) from exc

                raise

            await connection.commit()

    async def get(
        self,
        session_id: str,
    ) -> AccountLinkSession | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM account_link_sessions
                WHERE session_id = ?
                """,
                (str(session_id).strip(),),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._from_row(row)

    async def get_pending_for_discord(
        self,
        discord_user_id: str,
    ) -> AccountLinkSession | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM account_link_sessions
                WHERE discord_user_id = ?
                  AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (str(discord_user_id).strip(),),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._from_row(row)

    async def authorize(
        self,
        session_id: str,
        twitch_user_id: str,
        *,
        now: int | None = None,
    ) -> bool:
        current_time = (
            int(time.time())
            if now is None
            else int(now)
        )

        twitch_id = str(twitch_user_id).strip()

        if not twitch_id:
            raise ValueError(
                "twitch_user_id cannot be empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE account_link_sessions
                SET
                    twitch_user_id = ?,
                    status = 'authorized',
                    completed_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE session_id = ?
                  AND status = 'pending'
                  AND expires_at > ?
                """,
                (
                    twitch_id,
                    str(session_id).strip(),
                    current_time,
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    async def fail(
        self,
        session_id: str,
        error: str,
    ) -> bool:
        error_message = str(error).strip()

        if not error_message:
            raise ValueError(
                "error cannot be empty."
            )

        return await self._finish_pending(
            session_id,
            AccountLinkSessionStatus.FAILED,
            last_error=error_message,
        )

    async def cancel(
        self,
        session_id: str,
    ) -> bool:
        return await self._finish_pending(
            session_id,
            AccountLinkSessionStatus.CANCELLED,
        )

    async def expire(
        self,
        session_id: str,
    ) -> bool:
        return await self._finish_pending(
            session_id,
            AccountLinkSessionStatus.EXPIRED,
            last_error=(
                "The Twitch device authorization expired."
            ),
        )

    async def expire_due(
        self,
        *,
        now: int | None = None,
    ) -> int:
        current_time = (
            int(time.time())
            if now is None
            else int(now)
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE account_link_sessions
                SET
                    status = 'expired',
                    completed_at = CURRENT_TIMESTAMP
                WHERE status = 'pending'
                  AND expires_at <= ?
                """,
                (current_time,),
            )

            changed = cursor.rowcount
            await cursor.close()
            await connection.commit()

        return changed

    async def _finish_pending(
        self,
        session_id: str,
        status: AccountLinkSessionStatus,
        *,
        last_error: str | None = None,
    ) -> bool:
        if status not in {
            AccountLinkSessionStatus.FAILED,
            AccountLinkSessionStatus.CANCELLED,
            AccountLinkSessionStatus.EXPIRED,
        }:
            raise ValueError(
                "Unsupported link-session completion status."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE account_link_sessions
                SET
                    status = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    last_error = ?
                WHERE session_id = ?
                  AND status = 'pending'
                """,
                (
                    status.value,
                    last_error,
                    str(session_id).strip(),
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    @staticmethod
    def _from_row(row) -> AccountLinkSession:
        raw_scopes = json.loads(
            row["requested_scopes_json"]
        )

        if not isinstance(raw_scopes, list):
            raise ValueError(
                "Stored requested scopes must be a JSON list."
            )

        return AccountLinkSession(
            session_id=row["session_id"],
            discord_user_id=row["discord_user_id"],
            twitch_user_id=row["twitch_user_id"],
            status=AccountLinkSessionStatus(
                row["status"]
            ),
            requested_scopes=tuple(raw_scopes),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            last_error=row["last_error"],
        )