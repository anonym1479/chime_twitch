from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from chimebuddy.repositories import IdentityRepository
from chimebuddy.services.trigger_coordinator import (
    TriggerCoordinator,
    TriggerRunReport,
)
from chimebuddy.twitch.helix_gateway import (
    StreamInformation,
)


logger = logging.getLogger(
    "chimebuddy.twitch.title_monitor"
)


class StreamInformationGateway(Protocol):
    async def get_stream_information(
        self,
        broadcaster_twitch_user_id: str,
    ) -> StreamInformation | None:
        """Return the current stream or None."""


@dataclass(frozen=True, slots=True)
class BroadcasterTitleCheck:
    broadcaster_twitch_user_id: str
    is_live: bool
    title: str
    trigger_report: TriggerRunReport | None
    error: str | None


@dataclass(frozen=True, slots=True)
class TitleMonitorReport:
    checks: tuple[BroadcasterTitleCheck, ...]

    @property
    def checked_count(self) -> int:
        return len(self.checks)

    @property
    def error_count(self) -> int:
        return sum(
            check.error is not None
            for check in self.checks
        )


class StreamTitleMonitor:
    """Checks live titles and evaluates title triggers."""

    def __init__(
        self,
        identity_repository: IdentityRepository,
        stream_gateway: StreamInformationGateway,
        trigger_coordinator: TriggerCoordinator,
        *,
        poll_interval_seconds: int = 60,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError(
                "poll_interval_seconds must be positive."
            )

        self.identity_repository = (
            identity_repository
        )
        self.stream_gateway = stream_gateway
        self.trigger_coordinator = (
            trigger_coordinator
        )
        self.poll_interval_seconds = (
            poll_interval_seconds
        )

    async def check_once(self) -> TitleMonitorReport:
        broadcasters = (
            await self.identity_repository
            .list_broadcasters(
                enabled_only=True
            )
        )

        checks: list[BroadcasterTitleCheck] = []

        for broadcaster in broadcasters:
            broadcaster_id = (
                broadcaster.twitch_user_id
            )

            try:
                stream = (
                    await self.stream_gateway
                    .get_stream_information(
                        broadcaster_id
                    )
                )
            except Exception as exc:
                logger.exception(
                    "Failed to read stream information "
                    "for broadcaster %s.",
                    broadcaster_id,
                )

                checks.append(
                    BroadcasterTitleCheck(
                        broadcaster_twitch_user_id=(
                            broadcaster_id
                        ),
                        is_live=False,
                        title="",
                        trigger_report=None,
                        error=(
                            "Stream information failed: "
                            f"{exc}"
                        ),
                    )
                )
                continue

            is_live = stream is not None
            title = (
                stream.title
                if stream is not None
                else ""
            )

            try:
                trigger_report = (
                    await self.trigger_coordinator
                    .process_title(
                        broadcaster_id,
                        title,
                    )
                )
            except Exception as exc:
                logger.exception(
                    "Trigger processing failed for "
                    "broadcaster %s.",
                    broadcaster_id,
                )

                checks.append(
                    BroadcasterTitleCheck(
                        broadcaster_twitch_user_id=(
                            broadcaster_id
                        ),
                        is_live=is_live,
                        title=title,
                        trigger_report=None,
                        error=(
                            "Trigger processing failed: "
                            f"{exc}"
                        ),
                    )
                )
                continue

            checks.append(
                BroadcasterTitleCheck(
                    broadcaster_twitch_user_id=(
                        broadcaster_id
                    ),
                    is_live=is_live,
                    title=title,
                    trigger_report=trigger_report,
                    error=None,
                )
            )

        return TitleMonitorReport(
            checks=tuple(checks)
        )

    async def run(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        """
        Run checks until graceful shutdown is requested.
        """

        logger.info(
            "Stream title monitor started with a "
            "%s-second interval.",
            self.poll_interval_seconds,
        )

        while not stop_event.is_set():
            report = await self.check_once()

            if report.error_count:
                logger.warning(
                    "Title check completed: %s checked, "
                    "%s errors.",
                    report.checked_count,
                    report.error_count,
                )
            else:
                logger.debug(
                    "Title check completed: %s checked, "
                    "no errors.",
                    report.checked_count,
                )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=(
                        self.poll_interval_seconds
                    ),
                )
            except TimeoutError:
                pass

        logger.info(
            "Stream title monitor stopped."
        )