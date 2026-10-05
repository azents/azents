"""Completed Channel Action admissions and provider settlements."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelActionMode
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_progress import (
    ExternalChannelWorkTask as ChannelWorkTask,
)
from azents.core.external_channel_provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadOnlySession, WriteSession
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import (
    AwaitingInputSettlement,
    ChannelActionEffectPlan,
    ChannelActionTransition,
    ChannelWorkSnapshot,
)
from azents.repos.session_execution.ownership import validate_session_execution_owner


@dataclasses.dataclass(frozen=True)
class ExternalChannelActionOperations:
    """Own database lifetimes without retaining authority over provider I/O."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_only_session_manager: Annotated[
        SessionManager[ReadOnlySession], Depends(get_read_only_session_manager)
    ]
    repository: Annotated[
        ExternalChannelWorkRepository, Depends(ExternalChannelWorkRepository.create)
    ]

    execution_owner: SessionExecutionOwner | None

    @classmethod
    def create(
        cls,
        session_manager: Annotated[
            SessionManager[WriteSession], Depends(get_session_manager)
        ],
        read_only_session_manager: Annotated[
            SessionManager[ReadOnlySession], Depends(get_read_only_session_manager)
        ],
        repository: Annotated[
            ExternalChannelWorkRepository, Depends(ExternalChannelWorkRepository.create)
        ],
    ) -> "ExternalChannelActionOperations":
        """Construct unbound operations with explicit absent execution authority."""
        return cls(
            session_manager=session_manager,
            read_only_session_manager=read_only_session_manager,
            repository=repository,
            execution_owner=None,
        )

    def for_execution(
        self, owner: SessionExecutionOwner
    ) -> "ExternalChannelActionOperations":
        """Bind effect admission while retaining native observations and settlements."""
        if self.execution_owner is not None and self.execution_owner != owner:
            raise ValueError(
                "External Channel execution authority does not match service"
            )
        return dataclasses.replace(self, execution_owner=owner)

    async def has_active_binding(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> bool:
        """Observe active Binding availability in a native read-only scope."""
        async with self.read_only_session_manager() as session:
            result = await self.repository.has_active_binding(
                session,
                session_id=session_id,
                agent_id=agent_id,
            )
        return result

    async def list_active_work(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> list[ChannelWorkSnapshot]:
        """Load detached active Work snapshots in a native read-only scope."""
        async with self.read_only_session_manager() as session:
            result = await self.repository.list_active_work(
                session,
                session_id=session_id,
                agent_id=agent_id,
            )
        return result

    async def commit_direct_action(
        self,
        *,
        session_id: str,
        agent_id: str,
        run_id: str | None,
        client_tool_call_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        title: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
        now: datetime.datetime,
    ) -> ChannelActionTransition:
        """Commit canonical Work and capture its ordered process-local effects."""
        async with self.session_manager() as session:
            if self.execution_owner is not None:
                await validate_session_execution_owner(session, self.execution_owner)
            result = await self.repository.commit_direct_action(
                session,
                session_id=session_id,
                agent_id=agent_id,
                run_id=run_id,
                client_tool_call_id=client_tool_call_id,
                binding_id=binding_id,
                mode=mode,
                message=message,
                title=title,
                tasks=tasks,
                files=files,
                now=now,
            )
            await session.write_session.commit()
        return result

    async def settle_awaiting_input(
        self,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
        run_id: str,
        work_cycle_id: str,
        expected_state_revision: int,
    ) -> AwaitingInputSettlement:
        """Commit awaiting-input state only for the exact current Work revision."""
        async with self.session_manager() as session:
            result = await self.repository.settle_awaiting_input(
                session,
                session_id=session_id,
                agent_id=agent_id,
                binding_id=binding_id,
                run_id=run_id,
                work_cycle_id=work_cycle_id,
                expected_state_revision=expected_state_revision,
            )
            await session.write_session.commit()
        return result

    async def revalidate_direct_effect(
        self,
        *,
        effect: ChannelActionEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Complete owner admission and current direct-effect authority validation."""
        async with self.session_manager() as session:
            if self.execution_owner is not None:
                await validate_session_execution_owner(session, self.execution_owner)
            result = await self.repository.revalidate_direct_effect(
                session,
                effect=effect,
            )
            await session.write_session.commit()
        return result

    async def apply_direct_effect_outcome(
        self,
        *,
        effect: ChannelActionEffectPlan,
        outcome: ProviderMutationOutcome,
    ) -> bool:
        """Settle an attempted effect through native Work projection CAS."""
        async with self.session_manager() as session:
            result = await self.repository.apply_direct_effect_outcome(
                session,
                effect=effect,
                outcome=outcome,
            )
            await session.write_session.commit()
        return result

    async def revalidate_direct_control(
        self,
        *,
        plan: ProviderEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Complete direct-control admission before provider execution."""
        async with self.session_manager() as session:
            result = await self.repository.revalidate_direct_control(
                session,
                plan=plan,
            )
            await session.write_session.commit()
        return result

    async def apply_access_control_outcome(
        self,
        *,
        plan: ProviderEffectPlan,
        outcome: ProviderMutationOutcome,
    ) -> bool:
        """Commit access-control outcome through its native projection CAS."""
        async with self.session_manager() as session:
            result = await self.repository.apply_access_control_outcome(
                session,
                plan=plan,
                outcome=outcome,
            )
            await session.write_session.commit()
        return result

    async def revalidate_binding_effect(
        self,
        *,
        plan: ProviderEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Complete owner admission and exact-Binding authority validation."""
        async with self.session_manager() as session:
            if self.execution_owner is not None:
                await validate_session_execution_owner(session, self.execution_owner)
            result = await self.repository.revalidate_binding_effect(
                session,
                plan=plan,
            )
            await session.write_session.commit()
        return result

    async def revalidate_terminal_control(
        self,
        *,
        plan: ProviderEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Validate captured cleanup against committed terminal authority."""
        async with self.session_manager() as session:
            result = await self.repository.revalidate_terminal_control(
                session,
                plan=plan,
            )
            await session.write_session.commit()
        return result

    async def record_discord_delivery_channel(
        self,
        *,
        resource_id: str,
        delivery_channel_id: str,
        initial_thread_title: str | None,
    ) -> str | None:
        """Commit a provisioned Discord thread identity before further delivery."""
        async with self.session_manager() as session:
            result = await self.repository.record_discord_delivery_channel(
                session,
                resource_id=resource_id,
                delivery_channel_id=delivery_channel_id,
                initial_thread_title=initial_thread_title,
            )
            await session.write_session.commit()
        return result
