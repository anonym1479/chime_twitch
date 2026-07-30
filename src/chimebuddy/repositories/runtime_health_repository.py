import json
from typing import Any

from chimebuddy.database import Database
from chimebuddy.models.runtime_health import (
    RuntimeErrorEvent,
    RuntimeHealthSnapshot,
)


class RuntimeHealthRepository:
    """Stores sanitized operational health without secrets."""

    def __init__(
        self,
        database: Database,
        *,
        retained_error_count: int = 100,
    ) -> None:
        if retained_error_count <= 0:
            raise ValueError(
                "retained_error_count must be positive."
            )

        self.database = database
        self.retained_error_count = retained_error_count

    async def mark_success(
        self,
        component: str,
        subject_id: str = "",
        *,
        status: str = "healthy",
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._upsert(
            component,
            subject_id,
            status,
            details,
            success=True,
        )

    async def set_status(
        self,
        component: str,
        subject_id: str = "",
        *,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._upsert(
            component,
            subject_id,
            status,
            details,
            success=None,
        )

    async def mark_failure(
        self,
        component: str,
        subject_id: str = "",
        *,
        status: str = "error",
        error_code: str,
        safe_message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        component_name = self._required_text(
            component,
            "component",
        )
        subject = str(subject_id).strip()
        state = self._required_text(status, "status")
        code = self._required_text(
            error_code,
            "error_code",
        )
        message = self._required_text(
            safe_message,
            "safe_message",
        )
        details_json = self._details_json(details)

        async with self.database.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")

            try:
                await self._execute_upsert(
                    connection,
                    component_name,
                    subject,
                    state,
                    details_json,
                    success=False,
                )
                await connection.execute(
                    """
                    INSERT INTO runtime_error_events (
                        component,
                        subject_id,
                        error_code,
                        safe_message
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        component_name,
                        subject,
                        code,
                        message,
                    ),
                )
                await connection.execute(
                    """
                    DELETE FROM runtime_error_events
                    WHERE event_id NOT IN (
                        SELECT event_id
                        FROM runtime_error_events
                        ORDER BY event_id DESC
                        LIMIT ?
                    )
                    """,
                    (self.retained_error_count,),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def get(
        self,
        component: str,
        subject_id: str = "",
    ) -> RuntimeHealthSnapshot | None:
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM runtime_health
                WHERE component = ?
                  AND subject_id = ?
                """,
                (
                    self._required_text(
                        component,
                        "component",
                    ),
                    str(subject_id).strip(),
                ),
            )
            row = await cursor.fetchone()
            await cursor.close()

        return (
            None
            if row is None
            else self._snapshot_from_row(row)
        )

    async def list_recent_errors(
        self,
        subject_id: str,
        *,
        limit: int = 3,
        include_global: bool = True,
    ) -> list[RuntimeErrorEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive.")

        subject = str(subject_id).strip()
        condition = (
            "subject_id IN (?, '')"
            if include_global
            else "subject_id = ?"
        )

        async with self.database.connect() as connection:
            cursor = await connection.execute(
                f"""
                SELECT *
                FROM runtime_error_events
                WHERE {condition}
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (subject, limit),
            )
            rows = await cursor.fetchall()
            await cursor.close()

        return [
            RuntimeErrorEvent(
                event_id=row["event_id"],
                component=row["component"],
                subject_id=row["subject_id"],
                error_code=row["error_code"],
                safe_message=row["safe_message"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def _upsert(
        self,
        component: str,
        subject_id: str,
        status: str,
        details: dict[str, Any] | None,
        *,
        success: bool | None,
    ) -> None:
        async with self.database.connect() as connection:
            await self._execute_upsert(
                connection,
                self._required_text(
                    component,
                    "component",
                ),
                str(subject_id).strip(),
                self._required_text(status, "status"),
                self._details_json(details),
                success=success,
            )
            await connection.commit()

    @staticmethod
    async def _execute_upsert(
        connection,
        component: str,
        subject_id: str,
        status: str,
        details_json: str,
        *,
        success: bool | None,
    ) -> None:
        success_sql = (
            "CURRENT_TIMESTAMP"
            if success is True
            else "runtime_health.last_success_at"
        )
        failure_sql = (
            "CURRENT_TIMESTAMP"
            if success is False
            else "runtime_health.last_failure_at"
        )

        await connection.execute(
            f"""
            INSERT INTO runtime_health (
                component,
                subject_id,
                status,
                details_json,
                last_success_at,
                last_failure_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                {"CURRENT_TIMESTAMP" if success is True else "NULL"},
                {"CURRENT_TIMESTAMP" if success is False else "NULL"}
            )
            ON CONFLICT(component, subject_id) DO UPDATE SET
                status = excluded.status,
                details_json = excluded.details_json,
                last_success_at = {success_sql},
                last_failure_at = {failure_sql},
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                component,
                subject_id,
                status,
                details_json,
            ),
        )

    @staticmethod
    def _snapshot_from_row(row) -> RuntimeHealthSnapshot:
        return RuntimeHealthSnapshot(
            component=row["component"],
            subject_id=row["subject_id"],
            status=row["status"],
            details_json=row["details_json"],
            last_success_at=row["last_success_at"],
            last_failure_at=row["last_failure_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _details_json(
        details: dict[str, Any] | None,
    ) -> str:
        value = {} if details is None else details

        if not isinstance(value, dict):
            raise ValueError(
                "details must be a dictionary."
            )

        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
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
