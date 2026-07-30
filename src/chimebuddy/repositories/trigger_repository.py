from dataclasses import replace

from chimebuddy.database import Database
from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
    TriggerRuntimeState,
    TriggerRuntimeStatus,
    TriggerSource,
)
from chimebuddy.repositories.errors import (
    DuplicateTriggerNameError,
)


class TriggerRepository:
    """Stores title triggers and their runtime state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_trigger(
        self,
        trigger: Trigger,
    ) -> Trigger:
        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                cursor = await connection.execute(
                    """
                    SELECT trigger_id
                    FROM triggers
                    WHERE broadcaster_twitch_user_id = ?
                      AND name = ? COLLATE NOCASE
                    """,
                    (
                        trigger.broadcaster_twitch_user_id,
                        trigger.name,
                    ),
                )

                existing = await cursor.fetchone()
                await cursor.close()

                if existing is not None:
                    raise DuplicateTriggerNameError(
                        f"A trigger named '{trigger.name}' "
                        "already exists for this broadcaster."
                    )

                cursor = await connection.execute(
                    """
                    INSERT INTO triggers (
                        broadcaster_twitch_user_id,
                        name,
                        source,
                        match_type,
                        expression,
                        response_message,
                        pin_message,
                        priority,
                        enabled
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trigger.broadcaster_twitch_user_id,
                        trigger.name,
                        trigger.source.value,
                        trigger.match_type.value,
                        trigger.expression,
                        trigger.response_message,
                        int(trigger.pin_message),
                        trigger.priority,
                        int(trigger.enabled),
                    ),
                )

                trigger_id = int(cursor.lastrowid)
                await cursor.close()

                await connection.execute(
                    """
                    INSERT INTO trigger_runtime_state (
                        trigger_id
                    )
                    VALUES (?)
                    """,
                    (trigger_id,),
                )

                await connection.commit()

                return replace(
                    trigger,
                    trigger_id=trigger_id,
                )

            except Exception:
                if connection.in_transaction:
                    await connection.rollback()
                raise

    async def get_trigger(
        self,
        trigger_id: int,
    ) -> Trigger | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM triggers
                WHERE trigger_id = ?
                """,
                (trigger_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return self._trigger_from_row(row)

    async def list_triggers(
        self,
        broadcaster_twitch_user_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[Trigger]:
        enabled_filter = (
            "AND enabled = 1"
            if enabled_only
            else ""
        )

        query = f"""
            SELECT *
            FROM triggers
            WHERE broadcaster_twitch_user_id = ?
            {enabled_filter}
            ORDER BY priority ASC, trigger_id ASC
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                query,
                (str(broadcaster_twitch_user_id),),
            )

            rows = await cursor.fetchall()
            await cursor.close()

        return [
            self._trigger_from_row(row)
            for row in rows
        ]

    async def update_inactive_trigger(
        self,
        trigger: Trigger,
    ) -> bool:
        """
        Update a trigger only while its runtime state is
        inactive.

        The broadcaster ID is part of the ownership check.
        """

        if trigger.trigger_id is None:
            raise ValueError(
                "A stored trigger ID is required."
            )

        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                cursor = await connection.execute(
                    """
                    SELECT
                        triggers.broadcaster_twitch_user_id,
                        trigger_runtime_state.status
                    FROM triggers
                    JOIN trigger_runtime_state
                        ON trigger_runtime_state.trigger_id =
                           triggers.trigger_id
                    WHERE triggers.trigger_id = ?
                    """,
                    (trigger.trigger_id,),
                )

                current = await cursor.fetchone()
                await cursor.close()

                if (
                    current is None
                    or current[
                        "broadcaster_twitch_user_id"
                    ]
                    != trigger.broadcaster_twitch_user_id
                    or current["status"] != "inactive"
                ):
                    await connection.rollback()
                    return False

                cursor = await connection.execute(
                    """
                    SELECT trigger_id
                    FROM triggers
                    WHERE broadcaster_twitch_user_id = ?
                      AND name = ? COLLATE NOCASE
                      AND trigger_id != ?
                    """,
                    (
                        trigger.broadcaster_twitch_user_id,
                        trigger.name,
                        trigger.trigger_id,
                    ),
                )

                duplicate = await cursor.fetchone()
                await cursor.close()

                if duplicate is not None:
                    raise DuplicateTriggerNameError(
                        f"A trigger named '{trigger.name}' "
                        "already exists for this "
                        "broadcaster."
                    )

                cursor = await connection.execute(
                    """
                    UPDATE triggers
                    SET
                        name = ?,
                        source = ?,
                        match_type = ?,
                        expression = ?,
                        response_message = ?,
                        pin_message = ?,
                        priority = ?,
                        enabled = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE trigger_id = ?
                      AND broadcaster_twitch_user_id = ?
                    """,
                    (
                        trigger.name,
                        trigger.source.value,
                        trigger.match_type.value,
                        trigger.expression,
                        trigger.response_message,
                        int(trigger.pin_message),
                        trigger.priority,
                        int(trigger.enabled),
                        trigger.trigger_id,
                        trigger.broadcaster_twitch_user_id,
                    ),
                )

                changed = cursor.rowcount == 1
                await cursor.close()

                if not changed:
                    await connection.rollback()
                    return False

                await connection.commit()
                return True

            except Exception:
                if connection.in_transaction:
                    await connection.rollback()
                raise

    async def set_trigger_enabled_for_broadcaster(
        self,
        trigger_id: int,
        broadcaster_twitch_user_id: str,
        enabled: bool,
    ) -> bool:
        """Change enabled state with an ownership check."""

        broadcaster_id = str(
            broadcaster_twitch_user_id
        ).strip()

        if not broadcaster_id:
            raise ValueError(
                "broadcaster_twitch_user_id cannot be "
                "empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE triggers
                SET
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE trigger_id = ?
                  AND broadcaster_twitch_user_id = ?
                """,
                (
                    int(enabled),
                    int(trigger_id),
                    broadcaster_id,
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    async def delete_inactive_trigger(
        self,
        trigger_id: int,
        broadcaster_twitch_user_id: str,
    ) -> bool:
        """
        Delete only an owned trigger whose runtime state
        has completed cleanup.
        """

        broadcaster_id = str(
            broadcaster_twitch_user_id
        ).strip()

        if not broadcaster_id:
            raise ValueError(
                "broadcaster_twitch_user_id cannot be "
                "empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM triggers
                WHERE trigger_id = ?
                  AND broadcaster_twitch_user_id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM trigger_runtime_state
                      WHERE
                          trigger_runtime_state.trigger_id =
                              triggers.trigger_id
                          AND
                          trigger_runtime_state.status =
                              'inactive'
                  )
                """,
                (
                    int(trigger_id),
                    broadcaster_id,
                ),
            )

            deleted = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return deleted

    async def set_trigger_enabled(
        self,
        trigger_id: int,
        enabled: bool,
    ) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE triggers
                SET
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE trigger_id = ?
                """,
                (
                    int(enabled),
                    trigger_id,
                ),
            )

            changed = cursor.rowcount > 0
            await cursor.close()
            await connection.commit()

        return changed

    async def delete_trigger(
        self,
        trigger_id: int,
    ) -> bool:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM triggers
                WHERE trigger_id = ?
                """,
                (trigger_id,),
            )

            changed = cursor.rowcount > 0
            await cursor.close()
            await connection.commit()

        return changed

    async def get_runtime_state(
        self,
        trigger_id: int,
    ) -> TriggerRuntimeState | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM trigger_runtime_state
                WHERE trigger_id = ?
                """,
                (trigger_id,),
            )

            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return TriggerRuntimeState(
            trigger_id=row["trigger_id"],
            status=TriggerRuntimeStatus(row["status"]),
            last_title=row["last_title"],
            message_id=row["message_id"],
            is_pinned=bool(row["is_pinned"]),
            activated_at=row["activated_at"],
            operation_started_at=(
                row["operation_started_at"]
            ),
            updated_at=row["updated_at"],
            last_error=row["last_error"],
        )

    async def claim_activation(
        self,
        trigger_id: int,
        title: str,
    ) -> bool:
        """
        Atomically change an inactive trigger to activating.

        Only one simultaneous caller can succeed.
        """

        cleaned_title = str(title).strip()

        if not cleaned_title:
            raise ValueError(
                "The matched stream title cannot be empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE trigger_runtime_state
                SET
                    status = 'activating',
                    last_title = ?,
                    operation_started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE trigger_id = ?
                  AND status = 'inactive'
                """,
                (
                    cleaned_title,
                    trigger_id,
                ),
            )

            claimed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return claimed

    async def complete_activation(
        self,
        trigger_id: int,
        message_id: str,
        *,
        is_pinned: bool,
    ) -> bool:
        """Record a successfully sent trigger message."""

        cleaned_message_id = str(message_id).strip()

        if not cleaned_message_id:
            raise ValueError(
                "message_id cannot be empty."
            )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE trigger_runtime_state
                SET
                    status = 'active',
                    message_id = ?,
                    is_pinned = ?,
                    activated_at = CURRENT_TIMESTAMP,
                    operation_started_at = NULL,
                    updated_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE trigger_id = ?
                  AND status = 'activating'
                """,
                (
                    cleaned_message_id,
                    int(is_pinned),
                    trigger_id,
                ),
            )

            completed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return completed

    async def claim_deactivation(
        self,
        trigger_id: int,
    ) -> bool:
        """
        Atomically claim cleanup of an active or failed trigger.
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE trigger_runtime_state
                SET
                    status = 'deactivating',
                    operation_started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE trigger_id = ?
                  AND status IN ('active', 'error')
                """,
                (trigger_id,),
            )

            claimed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return claimed

    async def complete_deactivation(
        self,
        trigger_id: int,
    ) -> bool:
        """Return a cleaned-up trigger to its inactive state."""

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE trigger_runtime_state
                SET
                    status = 'inactive',
                    last_title = NULL,
                    message_id = NULL,
                    is_pinned = 0,
                    activated_at = NULL,
                    operation_started_at = NULL,
                    updated_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE trigger_id = ?
                  AND status = 'deactivating'
                """,
                (trigger_id,),
            )

            completed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return completed

    async def mark_operation_error(
        self,
        trigger_id: int,
        error_message: str,
        *,
        message_id: str | None = None,
        is_pinned: bool | None = None,
    ) -> bool:
        """Record a sanitized trigger-operation error."""

        cleaned_error = (
            str(error_message).strip()
            or "Unknown trigger operation error."
        )

        # Prevent unexpectedly large database entries.
        cleaned_error = cleaned_error[:1000]

        cleaned_message_id = (
            str(message_id).strip()
            if message_id is not None
            else None
        )

        pinned_value = (
            int(is_pinned)
            if is_pinned is not None
            else None
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE trigger_runtime_state
                SET
                    status = 'error',
                    message_id = CASE
                        WHEN ? IS NULL
                        THEN message_id
                        ELSE ?
                    END,
                    is_pinned = CASE
                        WHEN ? IS NULL
                        THEN is_pinned
                        ELSE ?
                    END,
                    operation_started_at = NULL,
                    updated_at = CURRENT_TIMESTAMP,
                    last_error = ?
                WHERE trigger_id = ?
                """,
                (
                    cleaned_message_id,
                    cleaned_message_id,
                    pinned_value,
                    pinned_value,
                    cleaned_error,
                    trigger_id,
                ),
            )

            changed = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return changed

    async def reset_error(
        self,
        trigger_id: int,
    ) -> bool:
        """
        Reset an error only when no sent message needs cleanup.
        """

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE trigger_runtime_state
                SET
                    status = 'inactive',
                    last_title = NULL,
                    is_pinned = 0,
                    activated_at = NULL,
                    operation_started_at = NULL,
                    updated_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE trigger_id = ?
                  AND status = 'error'
                  AND message_id IS NULL
                """,
                (trigger_id,),
            )

            reset = cursor.rowcount == 1
            await cursor.close()
            await connection.commit()

        return reset

    @staticmethod
    def _trigger_from_row(row) -> Trigger:
        return Trigger(
            trigger_id=row["trigger_id"],
            broadcaster_twitch_user_id=(
                row["broadcaster_twitch_user_id"]
            ),
            name=row["name"],
            source=TriggerSource(row["source"]),
            match_type=TriggerMatchType(
                row["match_type"]
            ),
            expression=row["expression"],
            response_message=row["response_message"],
            pin_message=bool(row["pin_message"]),
            priority=row["priority"],
            enabled=bool(row["enabled"]),
        )