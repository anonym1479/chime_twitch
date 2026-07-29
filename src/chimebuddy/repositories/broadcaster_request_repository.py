import json
from collections.abc import Iterable
from typing import Any

import aiosqlite

from chimebuddy.database import Database
from chimebuddy.models import (
    BroadcasterRequest,
    BroadcasterRequestStatus,
    OnboardingRequestEvent,
)
from chimebuddy.repositories.errors import (
    OpenBroadcasterRequestError,
)


class BroadcasterRequestRepository:
    """Stores broadcaster applications and their audit history."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(
        self,
        request: BroadcasterRequest,
    ) -> BroadcasterRequest:
        if request.request_id is not None:
            raise ValueError(
                "A new broadcaster request cannot already "
                "have a request_id."
            )

        if (
            request.status
            is not BroadcasterRequestStatus.PENDING
        ):
            raise ValueError(
                "A new broadcaster request must be pending."
            )

        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                cursor = await connection.execute(
                    """
                    INSERT INTO broadcaster_requests (
                        twitch_user_id,
                        discord_user_id,
                        status,
                        review_guild_id,
                        review_channel_id,
                        review_message_id,
                        requester_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.twitch_user_id,
                        request.discord_user_id,
                        request.status.value,
                        request.review_guild_id,
                        request.review_channel_id,
                        request.review_message_id,
                        request.requester_message,
                    ),
                )

                request_id = cursor.lastrowid
                await cursor.close()

                if request_id is None:
                    raise RuntimeError(
                        "SQLite did not return a request ID."
                    )

                await self._insert_event(
                    connection,
                    request_id=int(request_id),
                    event_type="request_created",
                    from_status=None,
                    to_status=(
                        BroadcasterRequestStatus.PENDING
                    ),
                    actor_discord_user_id=(
                        request.discord_user_id
                    ),
                    details_json="{}",
                )

                row = await self._fetch_request_row(
                    connection,
                    int(request_id),
                )

                await connection.commit()

            except aiosqlite.IntegrityError as exc:
                await connection.rollback()

                error_text = str(exc)

                if (
                    "broadcaster_requests.twitch_user_id"
                    in error_text
                    or
                    "broadcaster_requests.discord_user_id"
                    in error_text
                    or
                    "broadcaster_requests_open_twitch_idx"
                    in error_text
                    or
                    "broadcaster_requests_open_discord_idx"
                    in error_text
                ):
                    raise OpenBroadcasterRequestError(
                        "This Twitch or Discord account "
                        "already has an open broadcaster "
                        "request."
                    ) from exc

                raise

            except Exception:
                await connection.rollback()
                raise

        if row is None:
            raise RuntimeError(
                "The created broadcaster request "
                "could not be loaded."
            )

        return self._request_from_row(row)

    async def get(
        self,
        request_id: int,
    ) -> BroadcasterRequest | None:
        async with self.database.connect() as connection:
            row = await self._fetch_request_row(
                connection,
                int(request_id),
            )

        if row is None:
            return None

        return self._request_from_row(row)

    async def get_open_for_discord(
        self,
        discord_user_id: str,
    ) -> BroadcasterRequest | None:
        discord_id = str(discord_user_id).strip()

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM broadcaster_requests
                WHERE discord_user_id = ?
                  AND status IN (
                      'pending',
                      'approving',
                      'provisioning',
                      'active',
                      'provisioning_failed',
                      'suspended',
                      'reauthorization_required'
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (discord_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._request_from_row(row)

    async def list_by_status(
        self,
        statuses: Iterable[
            BroadcasterRequestStatus
        ],
    ) -> list[BroadcasterRequest]:
        normalized_statuses = tuple(
            sorted(
                {
                    BroadcasterRequestStatus(
                        status
                    ).value
                    for status in statuses
                }
            )
        )

        if not normalized_statuses:
            return []

        placeholders = ", ".join(
            "?"
            for _ in normalized_statuses
        )

        query = f"""
            SELECT *
            FROM broadcaster_requests
            WHERE status IN ({placeholders})
            ORDER BY created_at, request_id
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                query,
                normalized_statuses,
            )

            rows = await cursor.fetchall()
            await cursor.close()

        return [
            self._request_from_row(row)
            for row in rows
        ]

    async def set_review_message(
        self,
        request_id: int,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
    ) -> bool:
        guild = self._required_text(
            guild_id,
            "guild_id",
        )
        channel = self._required_text(
            channel_id,
            "channel_id",
        )
        message = self._required_text(
            message_id,
            "message_id",
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE broadcaster_requests
                SET
                    review_guild_id = ?,
                    review_channel_id = ?,
                    review_message_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE request_id = ?
                """,
                (
                    guild,
                    channel,
                    message,
                    int(request_id),
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    async def transition(
        self,
        request_id: int,
        *,
        expected_statuses: Iterable[
            BroadcasterRequestStatus
        ],
        new_status: BroadcasterRequestStatus,
        event_type: str,
        actor_discord_user_id: str | None = None,
        decision_reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        expected = {
            BroadcasterRequestStatus(status)
            for status in expected_statuses
        }

        if not expected:
            raise ValueError(
                "expected_statuses cannot be empty."
            )

        target_status = BroadcasterRequestStatus(
            new_status
        )

        event_name = self._required_text(
            event_type,
            "event_type",
        )

        actor_id = self._optional_text(
            actor_discord_user_id
        )
        reason = self._optional_text(
            decision_reason
        )

        event_details = (
            {}
            if details is None
            else details
        )

        if not isinstance(event_details, dict):
            raise ValueError(
                "details must be a dictionary."
            )

        details_json = json.dumps(
            event_details,
            sort_keys=True,
            separators=(",", ":"),
        )

        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                row = await self._fetch_request_row(
                    connection,
                    int(request_id),
                )

                if row is None:
                    await connection.rollback()
                    return False

                current_status = (
                    BroadcasterRequestStatus(
                        row["status"]
                    )
                )

                if (
                    current_status not in expected
                    or current_status is target_status
                ):
                    await connection.rollback()
                    return False

                update_parts = [
                    "status = ?",
                    "updated_at = CURRENT_TIMESTAMP",
                ]

                parameters: list[Any] = [
                    target_status.value
                ]

                if reason is not None:
                    update_parts.append(
                        "decision_reason = ?"
                    )
                    parameters.append(reason)

                if (
                    actor_id is not None
                    and target_status
                    in {
                        BroadcasterRequestStatus.APPROVING,
                        BroadcasterRequestStatus.REJECTED,
                        BroadcasterRequestStatus.BLACKLISTED,
                    }
                ):
                    update_parts.append(
                        "decided_by_discord_user_id = ?"
                    )
                    parameters.append(actor_id)

                if target_status in {
                    BroadcasterRequestStatus.REJECTED,
                    BroadcasterRequestStatus.BLACKLISTED,
                }:
                    update_parts.append(
                        "decided_at = CURRENT_TIMESTAMP"
                    )

                if (
                    target_status
                    is BroadcasterRequestStatus.ACTIVE
                ):
                    update_parts.append(
                        "provisioned_at = CURRENT_TIMESTAMP"
                    )

                parameters.extend(
                    [
                        int(request_id),
                        current_status.value,
                    ]
                )

                update_query = f"""
                    UPDATE broadcaster_requests
                    SET {", ".join(update_parts)}
                    WHERE request_id = ?
                      AND status = ?
                """

                cursor = await connection.execute(
                    update_query,
                    parameters,
                )

                changed = cursor.rowcount == 1
                await cursor.close()

                if not changed:
                    await connection.rollback()
                    return False

                await self._insert_event(
                    connection,
                    request_id=int(request_id),
                    event_type=event_name,
                    from_status=current_status,
                    to_status=target_status,
                    actor_discord_user_id=actor_id,
                    details_json=details_json,
                )

                await connection.commit()
                return True

            except Exception:
                await connection.rollback()
                raise

    async def list_events(
        self,
        request_id: int,
    ) -> list[OnboardingRequestEvent]:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM onboarding_request_events
                WHERE request_id = ?
                ORDER BY event_id
                """,
                (int(request_id),),
            )

            rows = await cursor.fetchall()
            await cursor.close()

        return [
            self._event_from_row(row)
            for row in rows
        ]

    @staticmethod
    async def _fetch_request_row(
        connection,
        request_id: int,
    ):
        cursor = await connection.execute(
            """
            SELECT *
            FROM broadcaster_requests
            WHERE request_id = ?
            """,
            (request_id,),
        )

        row = await cursor.fetchone()
        await cursor.close()
        return row

    @staticmethod
    async def _insert_event(
        connection,
        *,
        request_id: int,
        event_type: str,
        from_status: (
            BroadcasterRequestStatus | None
        ),
        to_status: (
            BroadcasterRequestStatus | None
        ),
        actor_discord_user_id: str | None,
        details_json: str,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO onboarding_request_events (
                request_id,
                event_type,
                from_status,
                to_status,
                actor_discord_user_id,
                details_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                event_type,
                (
                    from_status.value
                    if from_status is not None
                    else None
                ),
                (
                    to_status.value
                    if to_status is not None
                    else None
                ),
                actor_discord_user_id,
                details_json,
            ),
        )

    @staticmethod
    def _request_from_row(
        row,
    ) -> BroadcasterRequest:
        return BroadcasterRequest(
            request_id=row["request_id"],
            twitch_user_id=row["twitch_user_id"],
            discord_user_id=row["discord_user_id"],
            status=BroadcasterRequestStatus(
                row["status"]
            ),
            review_guild_id=row["review_guild_id"],
            review_channel_id=(
                row["review_channel_id"]
            ),
            review_message_id=(
                row["review_message_id"]
            ),
            decision_reason=row["decision_reason"],
            requester_message=(
                row["requester_message"]
            ),
            decided_by_discord_user_id=(
                row["decided_by_discord_user_id"]
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            decided_at=row["decided_at"],
            provisioned_at=row["provisioned_at"],
        )

    @staticmethod
    def _event_from_row(
        row,
    ) -> OnboardingRequestEvent:
        return OnboardingRequestEvent(
            event_id=row["event_id"],
            request_id=row["request_id"],
            event_type=row["event_type"],
            from_status=row["from_status"],
            to_status=row["to_status"],
            actor_discord_user_id=(
                row["actor_discord_user_id"]
            ),
            details_json=row["details_json"],
            created_at=row["created_at"],
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