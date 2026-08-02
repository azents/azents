"""Provider-neutral external conversation foundation contracts."""

import datetime
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelDiscordThreadObservationStatus,
)


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


@dataclass(frozen=True, repr=False)
class ExternalChannelParticipationScope:
    """One provider parent-channel participation coordination identity."""

    connection_id: str
    provider_parent_channel_id: str

    def __post_init__(self) -> None:
        """Reject incomplete participation identities."""
        if not self.connection_id or not self.provider_parent_channel_id:
            raise ValueError("External Channel participation scope must be complete.")

    def __repr__(self) -> str:
        """Return only a bounded coordination digest."""
        encoded = "\0".join(
            (self.connection_id, self.provider_parent_channel_id)
        ).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return f"ExternalChannelParticipationScope(lock_digest={digest!r})"


class ExternalChannelParticipationLock(Protocol):
    """Ephemeral lock for one selected-Agent parent-channel configuration."""

    def acquire(
        self,
        *,
        scope: ExternalChannelParticipationScope,
        deadline: ExternalChannelOperationDeadline,
    ) -> AbstractAsyncContextManager[ExternalChannelConversationLockLease]:
        """Acquire an owned participation lease within the operation deadline."""
        ...


@dataclass(frozen=True)
class DiscordObservedThread:
    """One complete credential-free Discord root-thread observation."""

    channel_id: str
    guild_id: str
    parent_channel_id: str
    root_message_id: str
    owner_id: str
    name: str
    created_at: datetime.datetime

    def __post_init__(self) -> None:
        """Reject incomplete or ambiguous provider ownership evidence."""
        if not all(
            (
                self.channel_id,
                self.guild_id,
                self.parent_channel_id,
                self.root_message_id,
                self.owner_id,
                self.name,
            )
        ):
            raise ValueError("Discord observed thread evidence must be complete.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError(
                "Discord observed thread timestamp must be timezone-aware."
            )


@dataclass(frozen=True)
class DiscordRootThreadObservation:
    """One exact-root Discord thread observation with fail-closed status."""

    status: ExternalChannelDiscordThreadObservationStatus
    guild_id: str
    parent_channel_id: str
    root_message_id: str
    trigger_provider_message_key: str
    observed_at: datetime.datetime
    root_has_thread: bool | None
    thread: DiscordObservedThread | None

    def __post_init__(self) -> None:
        """Enforce exact-root absence and presence proof invariants."""
        if not all(
            (
                self.guild_id,
                self.parent_channel_id,
                self.root_message_id,
                self.trigger_provider_message_key,
            )
        ):
            raise ValueError(
                "Discord root-thread observation identity must be complete."
            )
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError(
                "Discord root-thread observation timestamp must be timezone-aware."
            )
        match self.status:
            case ExternalChannelDiscordThreadObservationStatus.THREAD_ABSENT:
                if self.root_has_thread is not False or self.thread is not None:
                    raise ValueError(
                        "Discord thread absence requires an exact no-thread "
                        "observation."
                    )
            case ExternalChannelDiscordThreadObservationStatus.THREAD_PRESENT:
                if self.root_has_thread is not True or self.thread is None:
                    raise ValueError(
                        "Discord thread presence requires complete thread evidence."
                    )
                if (
                    self.thread.guild_id != self.guild_id
                    or self.thread.parent_channel_id != self.parent_channel_id
                    or self.thread.root_message_id != self.root_message_id
                ):
                    raise ValueError(
                        "Discord observed thread must match the exact root identity."
                    )
            case ExternalChannelDiscordThreadObservationStatus.UNKNOWN:
                if self.thread is not None:
                    raise ValueError(
                        "Unknown Discord root-thread observations cannot carry proof."
                    )


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
    discord_root_thread_observation: DiscordRootThreadObservation | None

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
