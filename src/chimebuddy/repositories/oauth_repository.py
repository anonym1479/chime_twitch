import json

from chimebuddy.database import Database
from chimebuddy.models import (
    OAuthCredential,
    OAuthCredentialKind,
)


class OAuthCredentialRepository:
    """Stores Twitch user OAuth credentials."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(
        self,
        credential: OAuthCredential,
    ) -> None:
        scopes_json = json.dumps(
            credential.scopes,
            separators=(",", ":"),
        )

        async with self.database.connect() as connection:
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
                ) DO UPDATE SET
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

            await connection.commit()

    async def get(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
    ) -> OAuthCredential | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM oauth_credentials
                WHERE twitch_user_id = ?
                  AND credential_kind = ?
                """,
                (
                    str(twitch_user_id),
                    credential_kind.value,
                ),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._from_row(row)

    async def list_by_kind(
        self,
        credential_kind: OAuthCredentialKind,
    ) -> list[OAuthCredential]:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM oauth_credentials
                WHERE credential_kind = ?
                ORDER BY twitch_user_id
                """,
                (credential_kind.value,),
            )

            rows = await cursor.fetchall()
            await cursor.close()

        return [
            self._from_row(row)
            for row in rows
        ]

    async def delete(
        self,
        twitch_user_id: str,
        credential_kind: OAuthCredentialKind,
    ) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM oauth_credentials
                WHERE twitch_user_id = ?
                  AND credential_kind = ?
                """,
                (
                    str(twitch_user_id),
                    credential_kind.value,
                ),
            )

            deleted = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return deleted

    @staticmethod
    def _from_row(row) -> OAuthCredential:
        raw_scopes = json.loads(row["scopes_json"])

        if not isinstance(raw_scopes, list):
            raise ValueError(
                "Stored OAuth scopes must be a JSON list."
            )

        return OAuthCredential(
            twitch_user_id=row["twitch_user_id"],
            credential_kind=OAuthCredentialKind(
                row["credential_kind"]
            ),
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            scopes=tuple(raw_scopes),
            expires_at=row["expires_at"],
        )