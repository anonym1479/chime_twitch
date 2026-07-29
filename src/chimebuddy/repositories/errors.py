class RepositoryError(RuntimeError):
    """Base error for repository operations."""


class AccountLinkNotVerifiedError(RepositoryError):
    """Raised when broadcaster ownership is not verified."""

class DuplicateTriggerNameError(RepositoryError):
    """Raised when a broadcaster already has this trigger name."""

class RepositoryError(RuntimeError):
    """Base error for repository operations."""


class AccountLinkNotVerifiedError(RepositoryError):
    """Raised when broadcaster ownership is not verified."""


class DuplicateTriggerNameError(RepositoryError):
    """Raised when a broadcaster already has this trigger name."""


class PendingAccountLinkSessionError(RepositoryError):
    """Raised when a Discord user already has a pending link session."""