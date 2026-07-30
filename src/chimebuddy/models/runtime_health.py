from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    component: str
    subject_id: str
    status: str
    details_json: str
    last_success_at: str | None
    last_failure_at: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class RuntimeErrorEvent:
    event_id: int
    component: str
    subject_id: str
    error_code: str
    safe_message: str
    created_at: str
