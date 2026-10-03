"""Pure provider-neutral ingestion requests, snapshots and outcomes."""

import dataclasses
import datetime
import enum
import hashlib
from typing import Literal, Protocol

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryCredentialsInvalid,
    ExternalChannelHistoryDeadlineExceeded,
    ExternalChannelHistoryError,
    ExternalChannelHistoryMalformed,
    ExternalChannelHistoryPermissionDenied,
    ExternalChannelHistoryPositionInvalid,
    ExternalChannelHistoryRange,
    ExternalChannelHistoryRangeIncomplete,
    ExternalChannelHistoryRateLimited,
    ExternalChannelHistoryResourceUnavailable,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelHistoryTriggerMissing,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_conversation_preparation import (
    ExternalChannelConversationPreparation,
)
from azents.core.external_channel_file import MAX_EXTERNAL_CHANNEL_FILES
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelMailboxProjectionItem,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressItem,
)


class ExternalChannelIngestionOperation(enum.StrEnum):
    """Closed synchronous ingestion operation kind."""

    CURRENT_TRIGGER = "current_trigger"
    SELECTOR_CONTINUATION = "selector_continuation"
    ACCESS_ALLOW = "access_allow"
    SETUP_CONTINUATION = "setup_continuation"


class ExternalChannelIngestionOutcomeKind(enum.StrEnum):
    """Completed terminal result returned to one transport or replay caller."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    AWAITING_SELECTION = "awaiting_selection"
    AWAITING_ACCESS = "awaiting_access"
    IGNORED = "ignored"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_REJECTION = "terminal_rejection"


class ExternalChannelIngestionReason(enum.StrEnum):
    """Sanitized reason categories without provider or message identifiers."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    SELECTION_REQUIRED = "selection_required"
    SETUP_REQUIRED = "setup_required"
    ACCESS_REQUIRED = "access_required"
    NOT_AN_INVOCATION = "not_an_invocation"
    RESPONSE_MODE_NOT_TRIGGERED = "response_mode_not_triggered"
    AUTHOR_NOT_ELIGIBLE = "author_not_eligible"
    CONNECTION_UNAVAILABLE = "connection_unavailable"
    INGRESS_AUTHORITY_STALE = "ingress_authority_stale"
    CONVERSATION_UNAVAILABLE = "conversation_unavailable"
    POSITION_CHANGED = "position_changed"
    HISTORY_UNAVAILABLE = "history_unavailable"
    COORDINATION_UNAVAILABLE = "coordination_unavailable"
    WAKE_DISPATCH_PENDING = "wake_dispatch_pending"
    INVALID_REPLAY_BOUNDARY = "invalid_replay_boundary"


@dataclasses.dataclass(frozen=True, repr=False)
class ExternalChannelTriggerLocator:
    """Credential-free provider trigger identity without inbound content."""

    connection_id: str
    provider: ExternalChannelProvider
    provider_event_type: str
    provider_tenant_id: str
    provider_channel_id: str
    provider_parent_channel_id: str | None
    provider_thread_key: str | None
    delivery_thread_key: str | None
    provider_resource_key: str
    trigger_provider_message_key: str
    trigger_provider_message_id: str
    trigger_position: str
    provider_user_id: str | None
    invocation: bool
    expected_file_count: int | None

    def __post_init__(self) -> None:
        """Reject incomplete locators before provider or persistence use."""
        required = (
            self.connection_id,
            self.provider_tenant_id,
            self.provider_channel_id,
            self.provider_resource_key,
            self.trigger_provider_message_key,
            self.trigger_provider_message_id,
            self.trigger_position,
        )
        if any(not value for value in required):
            raise ValueError("External Channel trigger locator is incomplete.")
        expected_event_types = {
            ExternalChannelProvider.SLACK: {"app_mention", "message", "unknown"},
            ExternalChannelProvider.DISCORD: {
                "discord_message_create",
                "unknown",
            },
        }
        if self.provider_event_type not in expected_event_types[self.provider]:
            raise ValueError("External Channel provider event type is invalid.")
        if self.expected_file_count is not None and not (
            0 <= self.expected_file_count <= MAX_EXTERNAL_CHANNEL_FILES
        ):
            raise ValueError("External Channel expected file count is invalid.")

    @property
    def digest(self) -> str:
        """Return a content-free digest safe for diagnostics."""
        encoded = "\0".join(
            (
                self.connection_id,
                self.provider.value,
                self.provider_tenant_id,
                self.provider_channel_id,
                self.provider_parent_channel_id or "",
                self.provider_thread_key or "",
                self.delivery_thread_key or "",
                self.provider_resource_key,
                self.trigger_provider_message_key,
                self.trigger_provider_message_id,
                self.trigger_position,
                self.provider_user_id or "",
            )
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def __repr__(self) -> str:
        """Return only provider kind and a bounded identity digest."""
        return (
            "ExternalChannelTriggerLocator("
            f"provider={self.provider.value!r}, digest={self.digest!r})"
        )


@dataclasses.dataclass(frozen=True, repr=False)
class ExternalChannelIngressAuthority:
    """Content-free transport authority retained for final revalidation."""

    kind: ExternalChannelIngressAuthorityKind
    ingress_profile: ExternalChannelIngressProfile
    configuration_generation: int
    lease_owner: str | None
    lease_generation: int | None

    def __post_init__(self) -> None:
        """Validate generation and lease identity shapes."""
        if self.configuration_generation < 1:
            raise ValueError("External Channel configuration generation is invalid.")
        if self.lease_generation is not None and self.lease_generation < 1:
            raise ValueError("External Channel lease generation is invalid.")
        if self.kind is not ExternalChannelIngressAuthorityKind.LEASE and (
            self.lease_owner is not None or self.lease_generation is not None
        ):
            raise ValueError(
                "External Channel non-lease authority cannot carry lease identity."
            )
        if (
            self.kind is ExternalChannelIngressAuthorityKind.CONFIGURATION
            and self.ingress_profile is not ExternalChannelIngressProfile.SLACK_HTTP
        ):
            raise ValueError(
                "External Channel configuration authority requires Slack HTTP ingress."
            )
        if self.kind is ExternalChannelIngressAuthorityKind.LEASE and (
            self.ingress_profile
            not in {
                ExternalChannelIngressProfile.SLACK_SOCKET,
                ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
            }
        ):
            raise ValueError(
                "External Channel lease authority requires socket or gateway ingress."
            )
        if (
            self.kind is ExternalChannelIngressAuthorityKind.LEASE
            and self.ingress_profile is ExternalChannelIngressProfile.SLACK_SOCKET
            and (self.lease_owner is None or self.lease_generation is not None)
        ):
            raise ValueError(
                "External Channel Slack Socket authority requires only a lease owner."
            )
        if (
            self.kind is ExternalChannelIngressAuthorityKind.LEASE
            and self.ingress_profile
            is ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
            and (self.lease_owner is None or self.lease_generation is None)
        ):
            raise ValueError(
                "External Channel Discord Gateway authority requires a lease "
                "generation."
            )

    def __repr__(self) -> str:
        """Exclude the lease owner from diagnostic representations."""
        return (
            "ExternalChannelIngressAuthority("
            f"kind={self.kind.value!r}, "
            f"ingress_profile={self.ingress_profile.value!r}, "
            f"configuration_generation={self.configuration_generation!r}, "
            f"lease_generation={self.lease_generation!r})"
        )


@dataclasses.dataclass(frozen=True, repr=False)
class ExternalChannelReplayBoundary:
    """Immutable typed boundary retained for selector or access replay."""

    connection_id: str
    source_resource_id: str
    target_resource_id: str
    principal_id: str
    trigger_provider_message_key: str
    conversation_position_id: str
    range_start_position: str | None
    trigger_position: str

    def __post_init__(self) -> None:
        """Require complete relational and inclusive-trigger identities."""
        required = (
            self.connection_id,
            self.source_resource_id,
            self.target_resource_id,
            self.principal_id,
            self.trigger_provider_message_key,
            self.conversation_position_id,
            self.trigger_position,
        )
        if any(not value for value in required):
            raise ValueError("External Channel replay boundary is incomplete.")

    @property
    def resource_id(self) -> str:
        """Expose the source Resource through the common replay contract."""
        return self.source_resource_id

    def __repr__(self) -> str:
        """Exclude provider and durable row identifiers from diagnostics."""
        digest = hashlib.sha256(
            "\0".join(
                (
                    self.connection_id,
                    self.source_resource_id,
                    self.target_resource_id,
                    self.principal_id,
                    self.trigger_provider_message_key,
                    self.conversation_position_id,
                    self.range_start_position or "",
                    self.trigger_position,
                )
            ).encode()
        ).hexdigest()
        return f"ExternalChannelReplayBoundary(digest={digest!r})"


@dataclasses.dataclass(frozen=True, repr=False)
class ExternalChannelSetupReplayBoundary:
    """Frozen selected setup continuation and target conversation authority."""

    connection_id: str
    claim_id: str
    expected_claim_generation: int
    selected_source_revision: int
    setting_id: str
    settings_generation: int
    location: ExternalChannelConversationLocation
    source_resource_id: str
    target_resource_id: str
    principal_id: str
    trigger_provider_message_key: str
    conversation_position_id: str
    range_start_position: str | None
    trigger_position: str

    def __post_init__(self) -> None:
        """Require complete positive selected-setup identities."""
        required = (
            self.connection_id,
            self.claim_id,
            self.setting_id,
            self.source_resource_id,
            self.target_resource_id,
            self.principal_id,
            self.trigger_provider_message_key,
            self.conversation_position_id,
            self.trigger_position,
        )
        if (
            any(not value for value in required)
            or self.expected_claim_generation < 1
            or self.selected_source_revision < 1
            or self.settings_generation < 1
        ):
            raise ValueError("External Channel setup replay boundary is incomplete.")

    @property
    def resource_id(self) -> str:
        """Expose the source Resource through the common replay contract."""
        return self.source_resource_id

    def __repr__(self) -> str:
        """Exclude provider and durable row identifiers from diagnostics."""
        digest = hashlib.sha256(
            "\0".join(
                (
                    self.connection_id,
                    self.claim_id,
                    self.setting_id,
                    self.source_resource_id,
                    self.target_resource_id,
                    self.trigger_provider_message_key,
                    self.trigger_position,
                )
            ).encode()
        ).hexdigest()
        return f"ExternalChannelSetupReplayBoundary(digest={digest!r})"


ExternalChannelAnyReplayBoundary = (
    ExternalChannelReplayBoundary | ExternalChannelSetupReplayBoundary
)


@dataclasses.dataclass(frozen=True, repr=False)
class ExternalChannelIngestionRequest:
    """One synchronous current-trigger or immutable replay operation."""

    locator: ExternalChannelTriggerLocator
    scope: ExternalChannelConversationScope
    authority: ExternalChannelIngressAuthority
    deadline: ExternalChannelOperationDeadline
    operation: ExternalChannelIngestionOperation
    selected_route_id: str | None
    replay_boundary: ExternalChannelAnyReplayBoundary | None
    initial_title_eligible: bool

    def __post_init__(self) -> None:
        """Require operation-specific replay and scope ownership."""
        if self.scope.connection_id != self.locator.connection_id:
            raise ValueError("External Channel locator scope ownership is invalid.")
        if self.scope.provider_channel_id != self.locator.provider_channel_id:
            raise ValueError("External Channel locator channel scope is invalid.")
        if self.scope.provider_thread_key != self.locator.provider_thread_key:
            raise ValueError("External Channel locator thread scope is invalid.")
        if (
            self.operation is ExternalChannelIngestionOperation.CURRENT_TRIGGER
            and self.replay_boundary is not None
        ):
            raise ValueError(
                "Current trigger ingestion cannot carry a replay boundary."
            )
        if self.operation is not ExternalChannelIngestionOperation.CURRENT_TRIGGER and (
            self.replay_boundary is None
        ):
            raise ValueError("External Channel replay operation requires a boundary.")
        if (
            self.operation is ExternalChannelIngestionOperation.SETUP_CONTINUATION
        ) != isinstance(self.replay_boundary, ExternalChannelSetupReplayBoundary):
            raise ValueError(
                "External Channel setup continuation requires its typed boundary."
            )
        if (
            self.initial_title_eligible
            and self.operation is not ExternalChannelIngestionOperation.ACCESS_ALLOW
        ):
            raise ValueError(
                "Only access Allow replay may carry initial title eligibility."
            )

    def __repr__(self) -> str:
        """Return only closed operation and content-free locator identity."""
        return (
            "ExternalChannelIngestionRequest("
            f"operation={self.operation.value!r}, locator={self.locator!r})"
        )


@dataclasses.dataclass(frozen=True)
class ExternalChannelCanonicalHistoryMessage:
    """Provider-history-authoritative canonical message snapshot."""

    provider_message_key: str
    provider_position: str
    revision_key: str
    revision_kind: ExternalChannelMessageRevisionKind
    lifecycle: ExternalChannelMessageLifecycle
    author_type: ExternalChannelPrincipalAuthorType
    provider_user_id: str | None
    sender_display_name: str | None
    normalized_body: str | None
    attachment_metadata: dict[str, object] | None
    reference_mappings: dict[str, object] | None
    normalized_size: int
    provider_created_at: datetime.datetime | None
    provider_updated_at: datetime.datetime | None
    original_url: str | None

    def __post_init__(self) -> None:
        """Validate immutable provider-history message metadata."""
        if (
            not self.provider_message_key
            or not self.provider_position
            or not self.revision_key
            or self.normalized_size < 0
        ):
            raise ValueError("External Channel canonical history message is invalid.")


@dataclasses.dataclass(frozen=True)
class ExternalChannelIngestionOutcome:
    """Sanitized terminal ingestion result."""

    kind: ExternalChannelIngestionOutcomeKind
    reason: ExternalChannelIngestionReason
    mailbox_item_id: str | None = dataclasses.field(repr=False)
    control_plans: tuple[ProviderEffectPlan, ...] = dataclasses.field(repr=False)
    connection_id: str | None = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        """Require complete provider-control delivery identity."""
        if bool(self.control_plans) != (self.connection_id is not None):
            raise ValueError(
                "External Channel control delivery identity is incomplete."
            )


@dataclasses.dataclass(frozen=True)
class ExternalChannelIngestionPreparation:
    """Short database snapshot used before one provider-history read."""

    position_id: str | None
    exclusive_start_position: str | None
    immediate_outcome: ExternalChannelIngestionOutcome | None
    wake_mailbox_item_id: str | None
    wake_session_id: str | None
    priority_request: ExternalChannelIngestionRequest | None

    def __post_init__(self) -> None:
        """Require either a history position or one completed outcome."""
        completed = self.immediate_outcome is not None
        prepared = self.position_id is not None
        prioritized = self.priority_request is not None
        if sum((completed, prepared, prioritized)) != 1:
            raise ValueError("External Channel ingestion position is unavailable.")
        if (self.wake_mailbox_item_id is None) != (self.wake_session_id is None):
            raise ValueError("External Channel wake recovery identity is incomplete.")
        if prioritized and (
            self.exclusive_start_position is not None
            or self.wake_mailbox_item_id is not None
        ):
            raise ValueError(
                "External Channel priority recovery cannot carry prepared state."
            )


ExternalChannelAcceptanceStatus = Literal[
    "accepted",
    "duplicate",
    "position_mismatch",
    "awaiting_selection",
    "awaiting_access",
    "ignored",
    "terminal_rejection",
]


@dataclasses.dataclass(frozen=True)
class ExternalChannelIngestionAcceptance:
    """Final short-transaction acceptance result."""

    status: ExternalChannelAcceptanceStatus
    reason: ExternalChannelIngestionReason
    mailbox_item_id: str | None
    session_id: str | None
    control_plans: tuple[ProviderEffectPlan, ...]
    connection_id: str | None

    def __post_init__(self) -> None:
        """Require complete wake and provider-control identities."""
        if (self.mailbox_item_id is None) != (self.session_id is None):
            raise ValueError("External Channel accepted wake identity is incomplete.")
        if bool(self.control_plans) != (self.connection_id is not None):
            raise ValueError(
                "External Channel control delivery identity is incomplete."
            )


class ExternalChannelIngestionHistoryReader(Protocol):
    """Provider-history boundary with credentials contained by its adapter."""

    async def read_range(
        self,
        *,
        locator: ExternalChannelTriggerLocator,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
        """Read one exclusive-start, inclusive-trigger canonical range."""
        ...


class ExternalChannelIngestionStore(Protocol):
    """Database-owned preparation and final acceptance boundary."""

    async def prepare(
        self,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        """Load a content-free position/routing snapshot without provider I/O."""
        ...

    async def accept(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
        provider_preparation: ExternalChannelConversationPreparation | None,
    ) -> ExternalChannelIngestionAcceptance:
        """Apply one short atomic acceptance transaction."""
        ...


class ExternalChannelConversationProvisioner(Protocol):
    """Provider conversation preparation outside database transactions."""

    async def prepare(
        self,
        *,
        connection_id: str,
        target_resource_id: str,
    ) -> ExternalChannelConversationPreparation:
        """Prepare one usable provider conversation without Session creation."""
        ...


class ExternalChannelWakeDispatchUnavailable(RuntimeError):
    """The routing-only Session wake could not be durably completed."""


ExternalChannelWakeDispatchResult = Literal[
    "dispatched",
    "already_dispatched",
    "claimed_elsewhere",
]


class ExternalChannelWakeDispatcher(Protocol):
    """Post-commit routing wake boundary."""

    async def dispatch(
        self,
        *,
        mailbox_item_id: str,
        session_id: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelWakeDispatchResult:
        """Dispatch or recover one durable invocation wake."""
        ...


_MAX_PROVIDER_ATTEMPTS = 5
_MAX_ITEM_AGE = datetime.timedelta(minutes=5)
_DEFAULT_RETRY_DELAYS = (2, 10, 30, 60)


class ExternalChannelIngressFailureCategory(enum.StrEnum):
    """Closed content-free provider failure categories."""

    CREDENTIALS_INVALID = "credentials_invalid"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    MALFORMED_RESPONSE = "malformed_response"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TRIGGER_MISSING = "trigger_missing"
    RANGE_INCOMPLETE = "range_incomplete"
    POSITION_INVALID = "position_invalid"
    OWNERSHIP_STALE = "ownership_stale"


@dataclasses.dataclass(frozen=True)
class _PreparedSuccess:
    """Provider content prepared against one durable cursor snapshot."""

    item: ExternalChannelIngressItem
    durable_cursor: str | None
    history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]


@dataclasses.dataclass(frozen=True)
class _PreparedSuppressed:
    """One queued trigger already covered by the tentative cursor."""

    item: ExternalChannelIngressItem
    durable_cursor: str | None


@dataclasses.dataclass(frozen=True)
class _PreparedFailure:
    """One safe provider failure awaiting transactional retry or deletion."""

    item: ExternalChannelIngressItem
    durable_cursor: str | None
    category: ExternalChannelIngressFailureCategory
    retryable: bool
    retry_after_seconds: int | None


type _PreparedItem = _PreparedSuccess | _PreparedSuppressed | _PreparedFailure


def _provider_failure(
    *,
    item: ExternalChannelIngressItem,
    durable_cursor: str | None,
    error: ExternalChannelHistoryError,
) -> _PreparedFailure:
    """Classify a provider exception without retaining its raw message."""
    retry_after_seconds = None
    match error:
        case ExternalChannelHistoryRateLimited():
            category = ExternalChannelIngressFailureCategory.RATE_LIMITED
            retryable = True
            retry_after_seconds = error.retry_after_seconds
        case ExternalChannelHistoryTemporaryFailure():
            category = ExternalChannelIngressFailureCategory.TEMPORARY_FAILURE
            retryable = True
        case ExternalChannelHistoryDeadlineExceeded():
            category = ExternalChannelIngressFailureCategory.DEADLINE_EXCEEDED
            retryable = True
        case ExternalChannelHistoryCredentialsInvalid():
            category = ExternalChannelIngressFailureCategory.CREDENTIALS_INVALID
            retryable = False
        case ExternalChannelHistoryPermissionDenied():
            category = ExternalChannelIngressFailureCategory.PERMISSION_DENIED
            retryable = False
        case ExternalChannelHistoryResourceUnavailable():
            category = ExternalChannelIngressFailureCategory.RESOURCE_UNAVAILABLE
            retryable = False
        case ExternalChannelHistoryMalformed():
            category = ExternalChannelIngressFailureCategory.MALFORMED_RESPONSE
            retryable = False
        case ExternalChannelHistoryTriggerMissing():
            category = ExternalChannelIngressFailureCategory.TRIGGER_MISSING
            retryable = False
        case ExternalChannelHistoryRangeIncomplete():
            category = ExternalChannelIngressFailureCategory.RANGE_INCOMPLETE
            retryable = False
        case ExternalChannelHistoryPositionInvalid():
            category = ExternalChannelIngressFailureCategory.POSITION_INVALID
            retryable = False
        case _:
            raise error
    return _PreparedFailure(
        item=item,
        durable_cursor=durable_cursor,
        category=category,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def _retry_transition(
    failure: _PreparedFailure,
    *,
    now: datetime.datetime,
) -> datetime.datetime | None:
    """Return a bounded retry time or classify the item for deletion."""
    item = failure.item
    if not failure.retryable or item.attempt_count >= _MAX_PROVIDER_ATTEMPTS:
        return None
    age = now - item.created_at
    remaining = _MAX_ITEM_AGE - age
    if remaining <= datetime.timedelta(0):
        return None
    if failure.retry_after_seconds is not None:
        delay = datetime.timedelta(seconds=failure.retry_after_seconds)
    else:
        base = _DEFAULT_RETRY_DELAYS[item.attempt_count - 1]
        digest = hashlib.sha256(f"{item.id}:{item.attempt_count}".encode()).digest()
        jitter = 0.9 + (digest[0] / 2550)
        delay = datetime.timedelta(seconds=base * jitter)
    if delay > remaining:
        return None
    return now + delay


def _slack_presence_thread_ts(
    *,
    item: ExternalChannelIngressItem,
    resource: ExternalChannelResource,
) -> str:
    """Return the exact Slack loading anchor for one admitted Work cycle."""
    labels = resource.labels or {}
    retained = labels.get("thread_ts")
    if isinstance(retained, str) and retained:
        return retained
    return item.trigger_provider_message_id


def _locator(item: ExternalChannelIngressItem) -> ExternalChannelTriggerLocator:
    """Rebuild one credential-free provider locator from active queue state."""
    return ExternalChannelTriggerLocator(
        connection_id=item.connection_id,
        provider=item.provider,
        provider_event_type=item.provider_event_type,
        provider_tenant_id=item.provider_tenant_id,
        provider_channel_id=item.provider_channel_id,
        provider_parent_channel_id=item.provider_parent_channel_id,
        provider_thread_key=item.provider_thread_key,
        delivery_thread_key=item.delivery_thread_key,
        provider_resource_key=item.provider_resource_key,
        trigger_provider_message_key=item.trigger_provider_message_key,
        trigger_provider_message_id=item.trigger_provider_message_id,
        trigger_position=item.trigger_position,
        provider_user_id=item.provider_user_id,
        invocation=item.invocation,
        expected_file_count=item.expected_file_count,
    )


def _projection_item(
    *,
    item: ExternalChannelIngressItem,
    resource: ExternalChannelResource,
    binding: ExternalChannelBinding,
    message: ExternalChannelCanonicalHistoryMessage,
    invocation_id: str,
    principal_id: str | None,
    prompt_role: Literal["context", "invocation"],
    context_omitted: bool,
    sequence: int,
) -> ExternalChannelMailboxProjectionItem:
    """Build one canonical single-message mailbox projection."""
    return ExternalChannelMailboxProjectionItem(
        invocation_id=invocation_id,
        binding_id=binding.id,
        trigger_provider_message_key=item.trigger_provider_message_key,
        prompt_role=prompt_role,
        context_omitted=context_omitted,
        sequence=sequence,
        revision_kind=message.revision_kind,
        body=message.normalized_body,
        attachment_metadata=message.attachment_metadata,
        reference_mappings=message.reference_mappings,
        resource_id=resource.id,
        provider_resource_key=resource.provider_resource_key,
        resource_type=resource.resource_type,
        resource_labels=resource.labels,
        provider=item.provider,
        provider_tenant_id=item.provider_tenant_id,
        provider_message_key=message.provider_message_key,
        provider_position=message.provider_position,
        principal_id=principal_id,
        provider_user_id=message.provider_user_id,
        sender_display_name=message.sender_display_name,
        author_type=message.author_type,
        provider_created_at=message.provider_created_at,
        provider_updated_at=message.provider_updated_at,
        original_url=message.original_url,
    )


def _invocation_id(
    *,
    connection_id: str,
    position_id: str,
    provider_message_key: str,
    trigger_position: str,
) -> str:
    """Return one stable ingress invocation identity."""
    digest = hashlib.sha256(
        "\0".join(
            (
                connection_id,
                position_id,
                provider_message_key,
                trigger_position,
            )
        ).encode()
    ).hexdigest()
    return f"external-channel:{digest}"


def _message_idempotency_key(
    *,
    invocation_id: str,
    provider_message_key: str,
) -> str:
    """Return one stable provider-message mailbox identity."""
    digest = hashlib.md5(  # noqa: S324 - non-cryptographic durable identity only
        f"{len(invocation_id)}:{invocation_id}{provider_message_key}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return f"external-channel-message:{digest}"


def _outcome(
    kind: ExternalChannelIngestionOutcomeKind,
    reason: ExternalChannelIngestionReason,
) -> ExternalChannelIngestionOutcome:
    """Build one content-free callback outcome."""
    return ExternalChannelIngestionOutcome(
        kind=kind,
        reason=reason,
        mailbox_item_id=None,
        control_plans=(),
        connection_id=None,
    )
