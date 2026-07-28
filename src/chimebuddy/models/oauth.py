import time
from dataclasses import dataclass, field
from enum import StrEnum


def _clean_secret(value: str, field_name: str) -> str:
    cleaned = str(value).strip()

    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty.")

    return cleaned


class OAuthCredentialKind(StrEnum):
    BOT = "bot"
    BROADCASTER = "broadcaster"


@dataclass(frozen=True, slots=True)
class OAuthCredential:
    twitch_user_id: str
    credential_kind: OAuthCredentialKind
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    scopes: tuple[str, ...]
    expires_at: int

    def __post_init__(self) -> None:
        twitch_user_id = str(
            self.twitch_user_id
        ).strip()

        if not twitch_user_id:
            raise ValueError(
                "twitch_user_id cannot be empty."
            )

        object.__setattr__(
            self,
            "twitch_user_id",
            twitch_user_id,
        )

        object.__setattr__(
            self,
            "access_token",
            _clean_secret(
                self.access_token,
                "access_token",
            ),
        )

        object.__setattr__(
            self,
            "refresh_token",
            _clean_secret(
                self.refresh_token,
                "refresh_token",
            ),
        )

        normalized_scopes = tuple(
            sorted(
                {
                    str(scope).strip()
                    for scope in self.scopes
                    if str(scope).strip()
                }
            )
        )

        object.__setattr__(
            self,
            "scopes",
            normalized_scopes,
        )

        if self.expires_at <= 0:
            raise ValueError(
                "expires_at must be greater than zero."
            )

    def expires_within(
        self,
        seconds: int,
        *,
        now: int | None = None,
    ) -> bool:
        if seconds < 0:
            raise ValueError(
                "seconds cannot be negative."
            )

        current_time = (
            int(time.time())
            if now is None
            else int(now)
        )

        return self.expires_at <= current_time + seconds