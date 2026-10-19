"""Completed Routine notification preparation over current Primary authority."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import EventKind
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.routine import RoutineScope
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.events.types import Event, RoutineNotificationPayload
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.routine.authority import RoutineExecutionAuthorityRepository
from azents.repos.routine.completion import RoutineResultRecording
from azents.repos.session_primary_channel import SessionPrimaryChannelRepository


@dataclass(frozen=True)
class RoutineNotificationPreparation:
    """Immediate process-local effect; never a durable retry or destination queue."""

    binding_id: str | None
    plans: tuple[ProviderEffectPlan, ...]
    event: Event | None


@dataclass(frozen=True)
class RoutineNotificationOperations:
    """Close the DB transaction before any provider or live event publication."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    primary: Annotated[SessionPrimaryChannelRepository, Depends()]
    channels: Annotated[
        ExternalChannelWorkRepository, Depends(ExternalChannelWorkRepository.create)
    ]
    events: Annotated[EventTranscriptRepository, Depends()]
    execution_authority: Annotated[RoutineExecutionAuthorityRepository, Depends()]

    async def primary_matches(
        self,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
        binding_id: str,
    ) -> bool:
        """Suppress a captured effect after Primary replacement or disconnect."""
        async with self.session_manager() as session:
            await self.execution_authority.fence_execution_scope(
                session, scope=scope, authority=authority
            )
            current = await self.primary.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            return current == binding_id

    async def prepare(
        self,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
        recording: RoutineResultRecording,
    ) -> RoutineNotificationPreparation:
        """Capture only the current Primary; absence alone permits Session chat."""
        state = recording.state
        work = state.work
        if (
            not recording.created
            or work is None
            or not work.notify
            or work.message is None
            or state.context.scope != scope
            or state.current_run_id != authority.run_id
            or state.phase != "completed"
        ):
            raise ValueError("Routine delivery requires a newly recorded notification.")
        async with self.session_manager() as session:
            await self.execution_authority.fence_execution_scope(
                session, scope=scope, authority=authority
            )
            binding_id = await self.primary.get_current(
                session,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                session_id=scope.session_id,
            )
            if binding_id is not None:
                plans = await self.channels.prepare_binding_reply_effects(
                    session,
                    links=(),
                    agent_id=scope.agent_id,
                    session_id=scope.session_id,
                    binding_id=binding_id,
                    text=work.message,
                    files=(),
                    operation_seed=f"routine-result:{state.context.execution_id}",
                    slack_reply_broadcast=False,
                    discord_forward_to_parent=False,
                )
                return RoutineNotificationPreparation(
                    binding_id=binding_id, plans=plans, event=None
                )
            payload = RoutineNotificationPayload(
                execution_id=state.context.execution_id,
                slug=state.context.candidate.slug,
                title=state.context.candidate.content.title,
                content=work.message,
            )
            event = await self.events.append(
                session,
                EventCreate(
                    session_id=scope.session_id,
                    kind=EventKind.ROUTINE_NOTIFICATION,
                    payload=payload.model_dump(mode="json"),
                    external_id=f"routine-notification:{state.context.execution_id}",
                ),
            )
            return RoutineNotificationPreparation(
                binding_id=None, plans=(), event=event
            )
