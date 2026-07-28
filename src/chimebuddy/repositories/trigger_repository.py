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