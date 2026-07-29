import json
import time

from chimebuddy.database import Database
from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
    TwitchAccount,
)
from chimebuddy.repositories.errors import (
    AccountLinkIdentityConflictError,
)


class AccountLinkCompletionRepository:
    """Completes a verified account link in one transaction."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def complete(
        self,
        session_id: str,
        *,
        twitch_account: TwitchAccount,
        credential: OAuthCredential,
        now: int | None = None,
    ) -> bool:
        session_key = str(session_id).strip()

        if not session_key:
            raise ValueError(
                "session_id cannot be empty."
            )

        if (
            credential.credential_kind
            is not OAuthCredentialKind.BROADCASTER
        ):
            raise ValueError(
                "Account linking requires a broadcaster "
                "credential."
            )

        if (
            credential.twitch_user_id
            != twitch_account.twitch_user_id
        ):
            raise ValueError(
                "The credential and Twitch account "
                "belong to different users."
            )

        current_time = (
            int(time.time())
            if now is None
            else int(now)
        )

        scopes_json = json.dumps(
            credential.scopes,
            separators=(",", ":"),
        )

        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                cursor = await connection.execute(
                    """
                    SELECT *
                    FROM account_link_sessions
                    WHERE session_id = ?
                    """,
                    (session_key,),
                )

                session_row = await cursor.fetchone()
                await cursor.close()

                if session_row is None:
                    await connection.rollback()
                    return False

                if session_row["status"] != "pending":
                    await connection.rollback()
                    return False

                if session_row["expires_at"] <= current_time:
                    await connection.execute(
                        """
                        UPDATE account_link_sessions
                        SET
                            status = 'expired',
                            completed_at = CURRENT_TIMESTAMP
                        WHERE session_id = ?
                          AND status = 'pending'
                        """,
                        (session_key,),
                    )

                    await connection.commit()
                    return False

                raw_requested_scopes = json.loads(
                    session_row[
                        "requested_scopes_json"
                    ]
                )

                if not isinstance(
                    raw_requested_scopes,
                    list,
                ):
                    raise ValueError(
                        "Stored requested scopes must "
                        "be a JSON list."
                    )

                requested_scopes = {
                    str(scope).strip()
                    for scope in raw_requested_scopes
                    if str(scope).strip()
                }

                missing_scopes = (
                    requested_scopes
                    - set(credential.scopes)
                )

                if missing_scopes:
                    scope_text = ", ".join(
                        sorted(missing_scopes)
                    )

                    raise ValueError(
                        "The broadcaster credential is "
                        f"missing scopes: {scope_text}"
                    )

                discord_user_id = session_row[
                    "discord_user_id"
                ]
                twitch_user_id = (
                    twitch_account.twitch_user_id
                )

                cursor = await connection.execute(
                    """
                    SELECT discord_user_id
                    FROM account_links
                    WHERE twitch_user_id = ?
                    """,
                    (twitch_user_id,),
                )

                twitch_link = await cursor.fetchone()
                await cursor.close()

                if (
                    twitch_link is not None
                    and twitch_link["discord_user_id"]
                    != discord_user_id
                ):
                    raise AccountLinkIdentityConflictError(
                        "This Twitch account is already "
                        "linked to another Discord account."
                    )

                cursor = await connection.execute(
                    """
                    SELECT twitch_user_id
                    FROM account_links
                    WHERE discord_user_id = ?
                    """,
                    (discord_user_id,),
                )

                discord_link = await cursor.fetchone()
                await cursor.close()

                if (
                    discord_link is not None
                    and discord_link["twitch_user_id"]
                    != twitch_user_id
                ):
                    raise AccountLinkIdentityConflictError(
                        "This Discord account is already "
                        "linked to another Twitch account."
                    )

                await connection.execute(
                    """
                    INSERT INTO twitch_accounts (
                        twitch_user_id,
                        login,
                        display_name
                    )
                    VALUES (?, ?, ?)
                    ON CONFLICT(twitch_user_id)
                    DO UPDATE SET
                        login = excluded.login,
                        display_name =
                            excluded.display_name,
                        updated_at =
                            CURRENT_TIMESTAMP
                    """,
                    (
                        twitch_account.twitch_user_id,
                        twitch_account.login,
                        twitch_account.display_name,
                    ),
                )

                await connection.execute(
                    """
                    INSERT INTO oauth_credentials (
                        twitch_user_id,
                        credential_kind,
                        access_token,
                        refresh_token,
                        scopes_json,
                        expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        twitch_user_id,
                        credential_kind
                    )
                    DO UPDATE SET
                        access_token =
                            excluded.access_token,
                        refresh_token =
                            excluded.refresh_token,
                        scopes_json =
                            excluded.scopes_json,
                        expires_at =
                            excluded.expires_at,
                        updated_at =
                            CURRENT_TIMESTAMP
                    """,
                    (
                        credential.twitch_user_id,
                        credential.credential_kind.value,
                        credential.access_token,
                        credential.refresh_token,
                        scopes_json,
                        credential.expires_at,
                    ),
                )

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
                        'verified',
                        'twitch_device_code',
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    ON CONFLICT(twitch_user_id)
                    DO UPDATE SET
                        status = 'verified',
                        verification_method =
                            'twitch_device_code',
                        verified_at =
                            CURRENT_TIMESTAMP,
                        revoked_at = NULL
                    """,
                    (
                        twitch_user_id,
                        discord_user_id,
                    ),
                )

                cursor = await connection.execute(
                    """
                    UPDATE account_link_sessions
                    SET
                        twitch_user_id = ?,
                        status = 'authorized',
                        completed_at =
                            CURRENT_TIMESTAMP,
                        last_error = NULL
                    WHERE session_id = ?
                      AND status = 'pending'
                    """,
                    (
                        twitch_user_id,
                        session_key,
                    ),
                )

                completed = cursor.rowcount == 1
                await cursor.close()

                if not completed:
                    await connection.rollback()
                    return False

                await connection.commit()
                return True

            except Exception:
                await connection.rollback()
                raise