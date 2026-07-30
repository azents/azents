"""Provider-neutral external conversation foundation contracts."""

import datetime
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from azents.core.enums import ExternalChannelConversationScopeKind


@dataclass(frozen=True, repr=False)
class ExternalChannelConversationScope:
    """Canonical provider conversation identity.

    Raw provider identifiers are retained only for provider and persistence
    boundaries. Coordination keys and representations use a bounded digest.
    """

    connection_id: str
    kind: ExternalChannelConversationScopeKind
    provider_channel_id: str
    provider_thread_key: str | None

    def __post_init__(self) -> None:
        """Validate the closed parent-channel and thread identity shapes."""
        if not self.connection_id:
            raise ValueError("External Channel connection ID must not be blank.")
        if not self.provider_channel_id:
            raise ValueError("External Channel provider channel ID must not be blank.")
        if self.kind is ExternalChannelConversationScopeKind.PARENT_CHANNEL:
            if self.provider_thread_key is not None:
                raise ValueError("A parent-channel scope cannot have a thread key.")
        elif self.provider_thread_key is None or not self.provider_thread_key:
            raise ValueError("A thread scope requires a provider thread key.")

    @property
    def lock_digest(self) -> str:
        """Return a deterministic coordination digest without raw identifiers."""
        encoded = "\0".join(
            (
                self.connection_id,
                self.kind.value,
                self.provider_channel_id,
                self.provider_thread_key or "",
            )
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def __repr__(self) -> str:
        """Return a content-free representation safe for diagnostics."""
        return (
            "ExternalChannelConversationScope("
            f"kind={self.kind.value!r}, lock_digest={self.lock_digest!r})"
        )


@dataclass(frozen=True)
class ExternalChannelOperationDeadline:
    """Timezone-aware absolute deadline shared across one ingress operation."""

    expires_at: datetime.datetime

    def __post_init__(self) -> None:
        """Reject naive deadline values."""
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError(
                "External Channel operation deadline must be timezone-aware."
            )

    def remaining_seconds(
        self,
        *,
        now: datetime.datetime | None = None,
    ) -> float:
        """Return the non-negative remaining wall-clock budget."""
        current = now or datetime.datetime.now(datetime.UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("External Channel deadline clock must be timezone-aware.")
        return max(0.0, (self.expires_at - current).total_seconds())


class ExternalChannelConversationLockError(RuntimeError):
    """Base class for controlled conversation-lock failures."""


class ExternalChannelConversationLockUnavailable(ExternalChannelConversationLockError):
    """The configured coordination backend is unavailable."""


class ExternalChannelConversationLockTimeout(ExternalChannelConversationLockError):
    """The conversation lock could not be acquired before the deadline."""


class ExternalChannelConversationLockOwnershipLost(
    ExternalChannelConversationLockError
):
    """The current owner can no longer prove lock ownership."""


class ExternalChannelConversationLockLease(Protocol):
    """Owned ephemeral conversation lock."""

    async def assert_owned(self) -> None:
        """Raise when the lease is no longer owned."""
        ...


class ExternalChannelConversationLock(Protocol):
    """Ephemeral coordination contract for one canonical conversation."""

    def acquire(
        self,
        *,
        scope: ExternalChannelConversationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        """Acquire an owned lease within the absolute operation deadline."""
        ...


@dataclass(frozen=True)
class ExternalChannelHistoryRange[MessageT]:
    """One complete bounded provider-history range."""

    messages: tuple[MessageT, ...]
    trigger: MessageT
    context_omitted: bool
    range_start_position: str | None
    trigger_position: str
    provider_request_count: int
    scanned_message_count: int
    elapsed_seconds: float

    def __post_init__(self) -> None:
        """Validate bounded, sanitized range metadata."""
        if self.trigger not in self.messages:
            raise ValueError("External Channel history must contain its exact trigger.")
        if not self.trigger_position:
            raise ValueError("External Channel trigger position must not be blank.")
        if self.provider_request_count < 1:
            raise ValueError("External Channel history requires a provider request.")
        if self.scanned_message_count < len(self.messages):
            raise ValueError(
                "External Channel scanned count cannot be smaller than retained "
                "history."
            )
        if self.elapsed_seconds < 0:
            raise ValueError(
                "External Channel history elapsed time cannot be negative."
            )


class ExternalChannelHistoryError(RuntimeError):
    """Base class for controlled provider-history failures."""


class ExternalChannelHistoryCredentialsInvalid(ExternalChannelHistoryError):
    """The provider rejected the configured credential."""


class ExternalChannelHistoryPermissionDenied(ExternalChannelHistoryError):
    """The provider denied access to the requested conversation."""


class ExternalChannelHistoryResourceUnavailable(ExternalChannelHistoryError):
    """The provider conversation is unavailable."""


class ExternalChannelHistoryRateLimited(ExternalChannelHistoryError):
    """The provider deferred history retrieval."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("External Channel history is rate limited.")
        self.retry_after_seconds = max(1, retry_after_seconds)


class ExternalChannelHistoryTemporaryFailure(ExternalChannelHistoryError):
    """The provider did not produce a complete temporary response."""


class ExternalChannelHistoryMalformed(ExternalChannelHistoryError):
    """The provider response violated the bounded history contract."""


class ExternalChannelHistoryDeadlineExceeded(ExternalChannelHistoryError):
    """History retrieval exhausted the absolute operation deadline."""


class ExternalChannelHistoryTriggerMissing(ExternalChannelHistoryError):
    """The exact trigger could not be established in provider history."""


class ExternalChannelHistoryRangeIncomplete(ExternalChannelHistoryError):
    """The provider range or omission boundary could not be established."""


class ExternalChannelHistoryPositionInvalid(ExternalChannelHistoryError):
    """A provider position could not be deterministically encoded."""


class ExternalChannelHistoryAdapter[TriggerT, MessageT](Protocol):
    """Provider-neutral bounded history range adapter."""

    async def read_range(
        self,
        *,
        trigger: TriggerT,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[MessageT]:
        """Read an exclusive-start, inclusive-trigger provider range."""
        ...


type ExternalChannelDeadlineClock = Callable[[], datetime.datetime]
