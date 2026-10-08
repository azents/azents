"""Provider-neutral synchronous External Channel conversation ingestion."""

import asyncio
import dataclasses
import datetime
from typing import Annotated, assert_never

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationLock,
    ExternalChannelConversationLockError,
    ExternalChannelHistoryError,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationLock,
    ExternalChannelParticipationScope,
)
from azents.core.external_channel_conversation_preparation import (
    ExternalChannelConversationPreparation,
    ExternalChannelConversationProvisioningError,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelConversationProvisioner,
    ExternalChannelIngestionAcceptance,
    ExternalChannelIngestionHistoryReader,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngestionStore,
    ExternalChannelReplayBoundary,
    ExternalChannelSetupReplayBoundary,
    ExternalChannelWakeDispatcher,
    ExternalChannelWakeDispatchUnavailable,
)
from azents.services.external_channel.deps import (
    get_external_channel_conversation_lock,
    get_external_channel_participation_lock,
)


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
    conversation_provisioning: ExternalChannelConversationProvisioner
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
                        control_plans=(),
                        connection_id=None,
                    )
                provider_preparation = await self._prepare_provider_conversation(
                    request
                )
                acceptance = await self._accept_locked(
                    request=request,
                    preparation=preparation,
                    history=history,
                    provider_preparation=provider_preparation,
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
                control_plans=(),
                connection_id=None,
            )
        except asyncio.CancelledError:
            raise
        except ExternalChannelConversationLockError:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.COORDINATION_UNAVAILABLE,
                mailbox_item_id=None,
                control_plans=(),
                connection_id=None,
            )
        except ExternalChannelHistoryError:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
                mailbox_item_id=None,
                control_plans=(),
                connection_id=None,
            )
        except ExternalChannelConversationProvisioningError as error:
            return ExternalChannelIngestionOutcome(
                kind=(
                    ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
                    if error.retryable
                    else ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
                ),
                reason=(
                    ExternalChannelIngestionReason.HISTORY_UNAVAILABLE
                    if error.retryable
                    else ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
                ),
                mailbox_item_id=None,
                control_plans=(),
                connection_id=None,
            )
        except ExternalChannelWakeDispatchUnavailable:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.WAKE_DISPATCH_PENDING,
                mailbox_item_id=None,
                control_plans=(),
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
        provider_preparation: ExternalChannelConversationPreparation | None,
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
                    provider_preparation=provider_preparation,
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
                    provider_preparation=provider_preparation,
                )

    async def _prepare_provider_conversation(
        self,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelConversationPreparation | None:
        """Prepare replay-created provider conversations outside database locks."""
        if request.operation not in {
            ExternalChannelIngestionOperation.ACCESS_ALLOW,
            ExternalChannelIngestionOperation.SETUP_CONTINUATION,
        }:
            return None
        boundary = request.replay_boundary
        if isinstance(boundary, ExternalChannelSetupReplayBoundary):
            target_resource_id = boundary.target_resource_id
        elif isinstance(boundary, ExternalChannelReplayBoundary):
            target_resource_id = boundary.target_resource_id
        else:
            raise ValueError(
                "External Channel replay provisioning boundary is unavailable."
            )
        return await self.conversation_provisioning.prepare(
            connection_id=request.locator.connection_id,
            target_resource_id=target_resource_id,
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
                    control_plans=(),
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
                    control_plans=(),
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
            control_plans=acceptance.control_plans,
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
