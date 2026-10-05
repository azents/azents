"""Completed Scheduled Channel presentation preparations."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelDeliveryOperation
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.scheduled_task_terminal_operations import (
    ScheduledTaskTerminalEffectSnapshot,
)


@dataclasses.dataclass(frozen=True)
class ScheduledTaskTerminalChannelEffects:
    """Detached ordered terminal replies and captured Tracker cleanup plans."""

    reply_plans: tuple[ProviderEffectPlan, ...]
    cleanup_plans: tuple[tuple[int, ProviderEffectPlan], ...]


@dataclasses.dataclass(frozen=True)
class ScheduledTaskChannelOperations:
    """Own exact-Binding preparation scopes before provider publication."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelWorkRepository, Depends(ExternalChannelWorkRepository.create)
    ]

    async def prepare_binding_effect(
        self,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        operation: ExternalChannelDeliveryOperation,
        slack_payload: dict[str, object],
        discord_payload: dict[str, object],
        operation_seed: str,
    ) -> ProviderEffectPlan | None:
        """Complete one registration or deletion preparation before external I/O."""
        async with self.session_manager() as session:
            plan = await self.repository.prepare_binding_effect(
                session,
                agent_id=agent_id,
                session_id=session_id,
                binding_id=binding_id,
                operation=operation,
                slack_payload=slack_payload,
                discord_payload=discord_payload,
                operation_seed=operation_seed,
            )
            await session.write_session.commit()
        return plan

    async def prepare_terminal(
        self,
        snapshot: ScheduledTaskTerminalEffectSnapshot,
        *,
        files: Sequence[ExternalChannelOutboundFileManifest],
    ) -> ScheduledTaskTerminalChannelEffects:
        """Capture replies and cleanup in one exact-Binding transaction."""
        async with self.session_manager() as session:
            reply_plans = await self.repository.prepare_binding_reply_effects(
                session,
                agent_id=snapshot.agent_id,
                session_id=snapshot.session_id,
                binding_id=snapshot.binding_id,
                text=snapshot.result,
                files=files,
                operation_seed=f"scheduled-terminal:{snapshot.cycle_id}",
                slack_reply_broadcast=True,
                discord_forward_to_parent=True,
            )
            cleanup_plans: list[tuple[int, ProviderEffectPlan]] = []
            for part in snapshot.tracker_projection_parts:
                if part.provider_message_key is None:
                    continue
                plan = await self.repository.prepare_binding_effect(
                    session,
                    agent_id=snapshot.agent_id,
                    session_id=snapshot.session_id,
                    binding_id=snapshot.binding_id,
                    operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                    slack_payload={
                        "provider_message_key": part.provider_message_key,
                    },
                    discord_payload={
                        "provider_message_key": part.provider_message_key,
                    },
                    operation_seed=(
                        f"scheduled-tracker-delete:{snapshot.cycle_id}:"
                        f"{part.part_ordinal}"
                    ),
                )
                if plan is not None:
                    cleanup_plans.append((part.part_ordinal, plan))
            await session.write_session.commit()
        return ScheduledTaskTerminalChannelEffects(
            reply_plans=reply_plans, cleanup_plans=tuple(cleanup_plans)
        )
