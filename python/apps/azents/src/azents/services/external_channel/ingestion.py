"""Provider-neutral synchronous External Channel conversation ingestion."""

import asyncio
import dataclasses
import datetime
import enum
import hashlib
from typing import Annotated, Literal, Protocol, assert_never

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLock,
    ExternalChannelConversationLockError,
    ExternalChannelConversationScope,
    ExternalChannelHistoryError,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationLock,
    ExternalChannelParticipationScope,
)
from azents.services.external_channel.deps import (
    get_external_channel_conversation_lock,
    get_external_channel_participation_lock,
)


class ExternalChannelIngestionOperation(enum.StrEnum):
    """Closed synchronous ingestion operation kind."""

    CURRENT_TRIGGER = "current_trigger"
    SELECTOR_CONTINUATION = "selector_continuation"
    ACCESS_ALLOW = "access_allow"
    SETUP_CONTINUATION = "setup_continuation"


class ExternalChannelIngressAuthorityKind(enum.StrEnum):
    """Authority proof used by the final ingestion transaction."""

    CONFIGURATION = "configuration"
    LEASE = "lease"
    DURABLE_REPLAY = "durable_replay"


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
    resource_id: str
    principal_id: str
    trigger_provider_message_key: str
    conversation_position_id: str
    range_start_position: str | None
    trigger_position: str

    def __post_init__(self) -> None:
        """Require complete relational and inclusive-trigger identities."""
        required = (
            self.connection_id,
            self.resource_id,
            self.principal_id,
            self.trigger_provider_message_key,
            self.conversation_position_id,
            self.trigger_position,
        )
        if any(not value for value in required):
            raise ValueError("External Channel replay boundary is incomplete.")

    def __repr__(self) -> str:
        """Exclude provider and durable row identifiers from diagnostics."""
        digest = hashlib.sha256(
            "\0".join(
                (
                    self.connection_id,
                    self.resource_id,
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
    control_delivery_attempt_id: str | None = dataclasses.field(repr=False)
    connection_id: str | None = dataclasses.field(repr=False)

    def __post_init__(self) -> None:
        """Require complete provider-control delivery identity."""
        if (self.control_delivery_attempt_id is None) != (self.connection_id is None):
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
    control_delivery_attempt_id: str | None
    connection_id: str | None

    def __post_init__(self) -> None:
        """Require complete wake and provider-control identities."""
        if (self.mailbox_item_id is None) != (self.session_id is None):
            raise ValueError("External Channel accepted wake identity is incomplete.")
        if (self.control_delivery_attempt_id is None) != (self.connection_id is None):
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
    ) -> ExternalChannelIngestionAcceptance:
        """Apply one short atomic acceptance transaction."""
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


@dataclasses.dataclass
class ExternalChannelConversationIngestionService:
    """Coordinate one synchronous provider-history ingestion operation."""

    conversation_lock: Annotated[
        ExternalChannelConversationLock,
        Depends(get_external_channel_conversation_lock),
    ]
    participation_lock: Annotated[
        ExternalChannelParticipationLock,
        Depends(get_external_channel_participation_lock),
    ]
    history_reader: ExternalChannelIngestionHistoryReader
    store: ExternalChannelIngestionStore
    wake_dispatcher: ExternalChannelWakeDispatcher
    maximum_position_restarts: int = 4

    async def ingest(
        self,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionOutcome:
        """Return one completed terminal result without retaining inbound content."""
        try:
            for _ in range(self.maximum_position_restarts):
                preparation = await self._prepare_locked(request)
                if preparation.priority_request is not None:
                    recovery = await self.ingest(preparation.priority_request)
                    if recovery.kind not in {
                        ExternalChannelIngestionOutcomeKind.ACCEPTED,
                        ExternalChannelIngestionOutcomeKind.DUPLICATE,
                    }:
                        return recovery
                    continue
                if preparation.immediate_outcome is not None:
                    return await self._finish_prepared(
                        preparation,
                        deadline=request.deadline,
                    )
                history = await self.history_reader.read_range(
                    locator=request.locator,
                    exclusive_start_position=(preparation.exclusive_start_position),
                    deadline=request.deadline,
                )
                if history.trigger_position != request.locator.trigger_position:
                    return ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                        reason=ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                        mailbox_item_id=None,
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    )
                acceptance = await self._accept_locked(
                    request=request,
                    preparation=preparation,
                    history=history,
                )
                if acceptance.status == "position_mismatch":
                    continue
                return await self._finish_acceptance(
                    acceptance,
                    now=_utc_now(),
                    deadline=request.deadline,
                )
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.POSITION_CHANGED,
                mailbox_item_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        except asyncio.CancelledError:
            raise
        except ExternalChannelConversationLockError:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.COORDINATION_UNAVAILABLE,
                mailbox_item_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        except ExternalChannelHistoryError:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
                mailbox_item_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )
        except ExternalChannelWakeDispatchUnavailable:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.WAKE_DISPATCH_PENDING,
                mailbox_item_id=None,
                control_delivery_attempt_id=None,
                connection_id=None,
            )

    async def _prepare_locked(
        self,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        """Prepare under conversation then optional parent participation lock."""
        async with self.conversation_lock.acquire(
            scope=request.scope,
            deadline=request.deadline,
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            participation_scope = _participation_scope(request)
            if participation_scope is None:
                return await self.store.prepare(request=request)
            async with self.participation_lock.acquire(
                scope=participation_scope,
                deadline=request.deadline,
            ) as participation_lease:
                await participation_lease.assert_owned()
                await conversation_lease.assert_owned()
                return await self.store.prepare(request=request)

    async def _accept_locked(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAcceptance:
        """Accept under conversation then optional parent participation lock."""
        async with self.conversation_lock.acquire(
            scope=request.scope,
            deadline=request.deadline,
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            participation_scope = _participation_scope(request)
            if participation_scope is None:
                return await self.store.accept(
                    request=request,
                    preparation=preparation,
                    history=history,
                )
            async with self.participation_lock.acquire(
                scope=participation_scope,
                deadline=request.deadline,
            ) as participation_lease:
                await participation_lease.assert_owned()
                await conversation_lease.assert_owned()
                return await self.store.accept(
                    request=request,
                    preparation=preparation,
                    history=history,
                )

    async def _finish_prepared(
        self,
        preparation: ExternalChannelIngestionPreparation,
        *,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Recover an existing wake intent before returning its terminal result."""
        outcome = preparation.immediate_outcome
        if outcome is None:
            raise RuntimeError("External Channel immediate outcome is unavailable.")
        if (
            preparation.wake_mailbox_item_id is not None
            and preparation.wake_session_id is not None
        ):
            dispatch = await self.wake_dispatcher.dispatch(
                mailbox_item_id=preparation.wake_mailbox_item_id,
                session_id=preparation.wake_session_id,
                now=_utc_now(),
                deadline=deadline,
            )
            if dispatch == "claimed_elsewhere":
                return ExternalChannelIngestionOutcome(
                    kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                    reason=ExternalChannelIngestionReason.WAKE_DISPATCH_PENDING,
                    mailbox_item_id=preparation.wake_mailbox_item_id,
                    control_delivery_attempt_id=None,
                    connection_id=None,
                )
        return outcome

    async def _finish_acceptance(
        self,
        acceptance: ExternalChannelIngestionAcceptance,
        *,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Dispatch accepted input and translate the closed store result."""
        if acceptance.mailbox_item_id is not None and acceptance.session_id is not None:
            dispatch = await self.wake_dispatcher.dispatch(
                mailbox_item_id=acceptance.mailbox_item_id,
                session_id=acceptance.session_id,
                now=now,
                deadline=deadline,
            )
            if dispatch == "claimed_elsewhere":
                return ExternalChannelIngestionOutcome(
                    kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                    reason=ExternalChannelIngestionReason.WAKE_DISPATCH_PENDING,
                    mailbox_item_id=acceptance.mailbox_item_id,
                    control_delivery_attempt_id=None,
                    connection_id=None,
                )
        match acceptance.status:
            case "accepted":
                kind = ExternalChannelIngestionOutcomeKind.ACCEPTED
            case "duplicate":
                kind = ExternalChannelIngestionOutcomeKind.DUPLICATE
            case "awaiting_selection":
                kind = ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
            case "awaiting_access":
                kind = ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS
            case "ignored":
                kind = ExternalChannelIngestionOutcomeKind.IGNORED
            case "terminal_rejection":
                kind = ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
            case "position_mismatch":
                raise RuntimeError(
                    "External Channel position mismatch escaped the retry loop."
                )
            case _ as unreachable:
                assert_never(unreachable)
        return ExternalChannelIngestionOutcome(
            kind=kind,
            reason=acceptance.reason,
            mailbox_item_id=acceptance.mailbox_item_id,
            control_delivery_attempt_id=acceptance.control_delivery_attempt_id,
            connection_id=acceptance.connection_id,
        )


def _utc_now() -> datetime.datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.datetime.now(datetime.UTC)


def _participation_scope(
    request: ExternalChannelIngestionRequest,
) -> ExternalChannelParticipationScope | None:
    """Return the parent participation lock required by top-level ingestion."""
    if request.scope.kind is not ExternalChannelConversationScopeKind.PARENT_CHANNEL:
        return None
    return ExternalChannelParticipationScope(
        connection_id=request.locator.connection_id,
        provider_parent_channel_id=(
            request.locator.provider_parent_channel_id
            or request.scope.provider_channel_id
        ),
    )
