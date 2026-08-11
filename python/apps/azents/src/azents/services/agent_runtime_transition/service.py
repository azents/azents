"""Commit explicit Agent Runtime addition and rearm transitions."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    AgentRuntimeRemovalStatus,
    RuntimeProviderBindingOrigin,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeCreate
from azents.repos.agent_runtime_add.data import (
    AgentRuntimeAddReceipt,
    AgentRuntimeAddReceiptCreate,
)
from azents.repos.agent_runtime_add.repository import (
    AgentRuntimeAddReceiptRepository,
)
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.services.runtime_profile_resolution.data import (
    RuntimeProfileResolutionUnavailable,
)
from azents.services.runtime_profile_resolution.service import (
    PreparedRuntimeProfileSelection,
    RuntimeProfileResolutionService,
)

from .data import (
    AgentRuntimeAdditionRequest,
    AgentRuntimeAdditionResult,
    AgentRuntimeAdditionUnavailable,
)


@dataclasses.dataclass
class AgentRuntimeTransitionService:
    """Own explicit `none` to `managed` Runtime transitions."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    removal_repository: Annotated[
        AgentRuntimeRemovalRepository,
        Depends(AgentRuntimeRemovalRepository),
    ]
    add_receipt_repository: Annotated[
        AgentRuntimeAddReceiptRepository,
        Depends(AgentRuntimeAddReceiptRepository),
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ]
    resolution_service: Annotated[
        RuntimeProfileResolutionService,
        Depends(RuntimeProfileResolutionService),
    ]

    async def add_runtime(
        self,
        request: AgentRuntimeAdditionRequest,
    ) -> AgentRuntimeAdditionResult:
        """Commit or replay one explicit stopped Runtime addition."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_runtime_selection_input_for_update(
                session,
                request.agent_id,
            )
            if agent is None:
                raise AgentRuntimeAdditionUnavailable(
                    code="agent_not_found",
                    message="Agent was not found.",
                )
            existing_receipt = (
                await self.add_receipt_repository.get_by_agent_idempotency_key(
                    session,
                    agent_id=agent.id,
                    idempotency_key=request.idempotency_key,
                )
            )
            if existing_receipt is not None:
                return await self._replay(
                    session,
                    request=request,
                    agent=agent,
                    receipt=existing_receipt,
                )
            self._require_addable_agent(agent, request)
            active_removal = await self.removal_repository.get_active_by_agent_id(
                session,
                agent.id,
            )
            if active_removal is not None:
                raise AgentRuntimeAdditionUnavailable(
                    code="runtime_removal_in_progress",
                    message="Runtime removal is still in progress.",
                )
            try:
                prepared = await self.resolution_service.prepare_explicit_selection(
                    session,
                    workspace_id=agent.workspace_id,
                    profile_id=request.workspace_runtime_profile_id,
                    agent_selection_version=(
                        agent.runtime_profile_selection_version + 1
                    ),
                )
            except RuntimeProfileResolutionUnavailable as error:
                raise AgentRuntimeAdditionUnavailable(
                    code=error.code,
                    message=str(error),
                ) from error
            if (
                prepared.resolution.status
                is not RuntimeConfigurationResolutionStatus.READY
            ):
                raise AgentRuntimeAdditionUnavailable(
                    code=(
                        prepared.resolution.reason_code or "runtime_profile_unavailable"
                    ),
                    message="The selected Runtime Profile is unavailable.",
                )

            runtime, runtime_created = await self._prepare_runtime(
                session,
                agent=agent,
                prepared=prepared,
            )
            updated_agent = (
                await self.agent_repository.compare_and_set_runtime_capability(
                    session,
                    agent_id=agent.id,
                    expected_capability=AgentRuntimeCapability.NONE,
                    expected_capability_version=request.expected_capability_version,
                    expected_runtime_profile_selection_version=(
                        request.expected_runtime_profile_selection_version
                    ),
                    capability=AgentRuntimeCapability.MANAGED,
                    runtime_profile_id=prepared.profile.id,
                    shell_enabled=False,
                )
            )
            if updated_agent is None:
                raise AgentRuntimeAdditionUnavailable(
                    code="runtime_capability_version_conflict",
                    message="Agent Runtime capability changed concurrently.",
                )
            resolution = await self.resolution_service.attach_prepared_selection(
                session,
                agent=updated_agent,
                runtime=runtime,
                prepared=prepared,
                runtime_created=runtime_created,
            )
            if resolution is None:
                raise AgentRuntimeAdditionUnavailable(
                    code="runtime_profile_source_changed",
                    message="Runtime Profile sources changed during the addition.",
                )
            create_result = await self.add_receipt_repository.create_or_get(
                session,
                AgentRuntimeAddReceiptCreate(
                    agent_id=updated_agent.id,
                    workspace_id=updated_agent.workspace_id,
                    idempotency_key=request.idempotency_key,
                    workspace_runtime_profile_id=prepared.profile.id,
                    expected_capability_version=request.expected_capability_version,
                    committed_capability_version=(
                        updated_agent.runtime_capability_version
                    ),
                    committed_runtime_profile_selection_version=(
                        updated_agent.runtime_profile_selection_version
                    ),
                    agent_runtime_id=resolution.runtime.id,
                    runtime_configuration_revision_id=(resolution.desired_revision.id),
                    runtime_desired_generation=(resolution.runtime.desired_generation),
                ),
            )
            if not create_result.created:
                self._require_matching_receipt(
                    request=request,
                    receipt=create_result.receipt,
                )
            return AgentRuntimeAdditionResult(
                agent=updated_agent,
                runtime=resolution.runtime,
                desired_revision=resolution.desired_revision,
                receipt=create_result.receipt,
                replayed=not create_result.created,
            )

    async def _prepare_runtime(
        self,
        session: AsyncSession,
        *,
        agent: Agent,
        prepared: PreparedRuntimeProfileSelection,
    ) -> tuple[AgentRuntime, bool]:
        """Create the first logical Runtime or rearm exact deleted history."""
        existing = await self.runtime_repository.get_by_agent_id_for_update(
            session,
            agent.id,
        )
        if existing is None:
            ensured = await self.runtime_repository.ensure_with_create(
                session,
                create=AgentRuntimeCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent.id,
                    runtime_provider_id=prepared.provider.provider_id,
                    runtime_provider_resource_id=prepared.provider.id,
                    provider_binding_origin=(
                        RuntimeProviderBindingOrigin.AGENT_EXPLICIT
                    ),
                    provider_binding_evidence={
                        "workspace_id": agent.workspace_id,
                        "workspace_runtime_profile_id": prepared.profile.id,
                    },
                    infrastructure_profile_id=prepared.infrastructure.id,
                    workspace_runtime_profile_id=prepared.profile.id,
                    desired_runtime_configuration_revision_id=None,
                    applied_runtime_configuration_revision_id=None,
                ),
            )
            return ensured.runtime, ensured.created

        completed_removal = (
            await self.removal_repository.get_latest_completed_by_agent_id(
                session,
                agent.id,
            )
        )
        if not self._completed_removal_authorizes_rearm(
            completed_removal,
            existing,
        ):
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_rearm_not_ready",
                message="The historical Runtime is not ready for re-addition.",
            )
        rearmed = await self.runtime_repository.rearm_terminally_deleted(
            session,
            runtime_id=existing.id,
            expected_terminal_generation=existing.desired_generation,
            provider_logical_id=prepared.provider.provider_id,
            provider_resource_id=prepared.provider.id,
        )
        if rearmed is None:
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_rearm_conflict",
                message="The historical Runtime changed during re-addition.",
            )
        return rearmed, False

    async def _replay(
        self,
        session: AsyncSession,
        *,
        request: AgentRuntimeAdditionRequest,
        agent: Agent,
        receipt: AgentRuntimeAddReceipt,
    ) -> AgentRuntimeAdditionResult:
        """Return a durable addition result only while its capability remains."""
        self._require_matching_receipt(request=request, receipt=receipt)
        if (
            agent.runtime_capability is not AgentRuntimeCapability.MANAGED
            or agent.runtime_capability_version != receipt.committed_capability_version
            or agent.runtime_profile_id != receipt.workspace_runtime_profile_id
            or agent.runtime_profile_selection_version
            != receipt.committed_runtime_profile_selection_version
        ):
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_add_idempotency_stale",
                message="The prior Runtime addition is no longer current.",
            )
        runtime = await self.runtime_repository.get_by_id(
            session,
            receipt.agent_runtime_id,
        )
        revision = await self.profile_repository.get_configuration_revision(
            session,
            revision_id=receipt.runtime_configuration_revision_id,
        )
        if (
            runtime is None
            or runtime.agent_id != agent.id
            or runtime.workspace_id != agent.workspace_id
            or runtime.desired_generation != receipt.runtime_desired_generation
            or runtime.desired_runtime_configuration_revision_id
            != receipt.runtime_configuration_revision_id
            or runtime.workspace_runtime_profile_id
            != receipt.workspace_runtime_profile_id
            or revision is None
            or revision.runtime_id != runtime.id
            or revision.id != receipt.runtime_configuration_revision_id
            or revision.workspace_runtime_profile_id
            != receipt.workspace_runtime_profile_id
            or revision.target_desired_generation != receipt.runtime_desired_generation
        ):
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_add_idempotency_evidence_missing",
                message="The prior Runtime addition evidence is unavailable.",
            )
        return AgentRuntimeAdditionResult(
            agent=agent,
            runtime=runtime,
            desired_revision=revision,
            receipt=receipt,
            replayed=True,
        )

    def _require_addable_agent(
        self,
        agent: Agent,
        request: AgentRuntimeAdditionRequest,
    ) -> None:
        """Reject non-current or already capable Agent state."""
        if (
            agent.runtime_capability_version != request.expected_capability_version
            or agent.runtime_profile_selection_version
            != request.expected_runtime_profile_selection_version
        ):
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_capability_version_conflict",
                message="Agent Runtime capability changed concurrently.",
            )
        if agent.runtime_capability is not AgentRuntimeCapability.NONE:
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_add_not_available",
                message="Runtime addition is available only for Runtime-free Agents.",
            )

    def _require_matching_receipt(
        self,
        *,
        request: AgentRuntimeAdditionRequest,
        receipt: AgentRuntimeAddReceipt,
    ) -> None:
        """Reject reuse of an idempotency key for a different transition."""
        if (
            receipt.agent_id != request.agent_id
            or receipt.expected_capability_version
            != request.expected_capability_version
            or receipt.workspace_runtime_profile_id
            != request.workspace_runtime_profile_id
            or receipt.committed_runtime_profile_selection_version
            != request.expected_runtime_profile_selection_version + 1
        ):
            raise AgentRuntimeAdditionUnavailable(
                code="runtime_add_idempotency_conflict",
                message="Runtime addition idempotency key was reused.",
            )

    def _completed_removal_authorizes_rearm(
        self,
        operation: AgentRuntimeRemovalOperation | None,
        runtime: AgentRuntime,
    ) -> bool:
        """Return whether completed operation evidence matches current deletion."""
        if (
            operation is None
            or operation.status is not AgentRuntimeRemovalStatus.COMPLETED
            or operation.agent_runtime_id != runtime.id
            or operation.completed_at is None
            or runtime.terminal_delete_requested_generation
            != runtime.desired_generation
            or runtime.terminal_delete_acknowledged_generation
            != runtime.desired_generation
            or runtime.terminal_delete_acknowledgement_kind is None
        ):
            return False
        if operation.physical_deletion_required is True:
            return (
                operation.target_terminal_delete_generation
                == runtime.desired_generation
                and operation.physical_delete_acknowledgement_kind
                is runtime.terminal_delete_acknowledgement_kind
                and operation.physical_delete_acknowledged_at is not None
            )
        if operation.physical_deletion_required is False:
            return (
                runtime.terminal_delete_acknowledgement_kind
                is RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
                and operation.target_terminal_delete_generation is None
                and operation.physical_delete_acknowledgement_kind is None
                and operation.physical_delete_acknowledged_at is None
            )
        return False
