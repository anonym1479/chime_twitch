from dataclasses import dataclass

from chimebuddy.models import (
    Trigger,
    TriggerMatchType,
    TriggerSource,
)


@dataclass(frozen=True, slots=True)
class TriggerEvaluation:
    title: str
    matched_triggers: tuple[Trigger, ...]

    @property
    def selected_trigger(self) -> Trigger | None:
        """Return the highest-priority matching trigger."""

        if not self.matched_triggers:
            return None

        return self.matched_triggers[0]

    @property
    def has_match(self) -> bool:
        return self.selected_trigger is not None


class TitleTriggerMatcher:
    """Evaluates stream-title triggers without external services."""

    def evaluate(
        self,
        title: str,
        triggers: list[Trigger],
    ) -> TriggerEvaluation:
        normalized_title = self._normalize(title)

        matching_triggers = [
            trigger
            for trigger in triggers
            if self._matches(normalized_title, trigger)
        ]

        matching_triggers.sort(
            key=self._sort_key
        )

        return TriggerEvaluation(
            title=str(title),
            matched_triggers=tuple(matching_triggers),
        )

    def _matches(
        self,
        normalized_title: str,
        trigger: Trigger,
    ) -> bool:
        if not trigger.enabled:
            return False

        if trigger.source is not TriggerSource.STREAM_TITLE:
            return False

        normalized_expression = self._normalize(
            trigger.expression
        )

        if trigger.match_type is TriggerMatchType.CONTAINS:
            return normalized_expression in normalized_title

        if trigger.match_type is TriggerMatchType.EXACT:
            return normalized_expression == normalized_title

        return False

    @staticmethod
    def _normalize(value: str) -> str:
        """Normalize case and surrounding whitespace."""

        return str(value).strip().casefold()

    @staticmethod
    def _sort_key(
        trigger: Trigger,
    ) -> tuple[int, int, str]:
        # Stored triggers have an ID. Unsaved triggers are placed after
        # stored triggers when their priorities are identical.
        trigger_id = (
            trigger.trigger_id
            if trigger.trigger_id is not None
            else 2**63 - 1
        )

        return (
            trigger.priority,
            trigger_id,
            trigger.name.casefold(),
        )