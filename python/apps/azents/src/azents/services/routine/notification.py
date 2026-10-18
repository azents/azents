"""One immediate post-completion notification through existing delivery authority."""

import asyncio
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.routine import RoutineDeliveryStatus, RoutineScope
from azents.core.routine_execution import RoutineExecutionState
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.core.tools import PublishEventFn
from azents.engine.tools.runtime_instruction_context import RuntimeInstructionContext
from azents.repos.routine.completion import (
    RoutineCompletionRepository,
    RoutineResultRecording,
)
from azents.repos.routine.notification import RoutineNotificationOperations
from azents.repos.session_primary_channel import SessionPrimaryChannelUnavailable
from azents.services.external_channel.channel_action import ExternalChannelActionService


@dataclass(frozen=True)
class RoutineNotificationService:
    """Do not terminalize a Run or Channel Work and never replay uncertain sends."""

    operations: Annotated[RoutineNotificationOperations, Depends()]
    completion: Annotated[RoutineCompletionRepository, Depends()]
    channels: Annotated[
        ExternalChannelActionService, Depends(ExternalChannelActionService.create)
    ]

    async def deliver(
        self,
        *,
        scope: RoutineScope,
        authority: SessionResourceAuthority,
        recording: RoutineResultRecording,
        runtime: RuntimeInstructionContext | None,
        publish_event: PublishEventFn | None,
    ) -> RoutineExecutionState:
        """The canonical result is already committed before reaching any effect."""
        state = recording.state
        if not recording.created or state.work is None or not state.work.notify:
            return state
        await self.completion.authorize(scope=scope, authority=authority)
        try:
            preparation = await self.operations.prepare(
                scope=scope,
                authority=authority,
                recording=recording,
            )
        except SessionPrimaryChannelUnavailable:
            return await self.completion.observe_delivery(
                scope=scope,
                authority=authority,
                recording=recording,
                status=RoutineDeliveryStatus.FAILED,
                error="Current Session Primary authority is unavailable.",
            )
        try:
            delivered = True
            if preparation.binding_id is None:
                if preparation.event is None:
                    raise RuntimeError("Routine chat notification event is missing.")
                if publish_event is not None:
                    await publish_event(preparation.event)
            else:
                delivered = bool(preparation.plans)
                channels = self.channels.for_execution_owner(authority.execution_owner)
                for plan in preparation.plans:
                    await self.completion.authorize(scope=scope, authority=authority)
                    if not await self.operations.primary_matches(
                        scope=scope,
                        authority=authority,
                        binding_id=preparation.binding_id,
                    ):
                        delivered = False
                        break
                    outcome = await channels.execute_binding_effect(
                        plan,
                        agent_id=scope.agent_id,
                        session_id=scope.session_id,
                        authority=authority,
                        file_storage=None if runtime is None else runtime.file_storage,
                        provider_delivery_service=None
                        if runtime is None
                        else runtime.provider_delivery_service,
                        resolve_runtime_target=None
                        if runtime is None
                        else runtime.resolve_runtime_target,
                    )
                    if outcome is None or outcome.status != "delivered":
                        delivered = False
        except asyncio.CancelledError:
            raise
        except Exception:
            # Preserve failure visibility while keeping the saved work complete.
            await self.completion.observe_delivery(
                scope=scope,
                authority=authority,
                recording=recording,
                status=RoutineDeliveryStatus.FAILED,
                error="Routine notification publication failed.",
            )
            raise
        return await self.completion.observe_delivery(
            scope=scope,
            authority=authority,
            recording=recording,
            status=RoutineDeliveryStatus.DELIVERED
            if delivered
            else RoutineDeliveryStatus.FAILED,
            error=None
            if delivered
            else "Routine notification delivery was not confirmed.",
        )
