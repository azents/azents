"""Resolve exact Workspace Runtime Profiles into immutable desired revisions."""

import dataclasses
import hashlib
import json
from typing import Annotated, Any

from azcommon.datetime import tznow
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOrigin,
    RuntimeProviderLifecycleState,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
    WorkspaceRuntimeProfilePolicyV1,
    compose_workspace_runtime_profile,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_spec,
)
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeCreate
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationRevisionCreate,
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.data import RuntimeProviderContractRevision
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)

from .data import (
    RuntimeProfileResolutionResult,
    RuntimeProfileResolutionUnavailable,
)


@dataclasses.dataclass(frozen=True)
class PreparedRuntimeProfileResolution:
    """One deterministic ready or blocked desired configuration."""

    status: RuntimeConfigurationResolutionStatus
    reason_code: str | None
    missing_capabilities: tuple[str, ...]
    capability_revision: RuntimeProviderContractRevision | None
    resolved_configuration: dict[str, Any] | None
    source_trace: dict[str, Any]
    digest: str


@dataclasses.dataclass(frozen=True)
class PreparedRuntimeProfileSelection:
    """Exact versioned sources for one explicit Runtime Profile selection."""

    provider: RuntimeProvider
    infrastructure: RuntimeInfrastructureProfile
    profile: WorkspaceRuntimeProfile
    resolution: PreparedRuntimeProfileResolution


@dataclasses.dataclass
class RuntimeProfileResolutionService:
    """Resolve and attach one exact Agent Runtime Profile selection."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    provider_policy_repository: Annotated[
        RuntimeProviderPolicyRepository,
        Depends(RuntimeProviderPolicyRepository),
    ]

    async def prepare_explicit_selection(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        profile_id: str,
        agent_selection_version: int,
    ) -> PreparedRuntimeProfileSelection:
        """Resolve one explicit Profile from exact versioned source rows."""
        profile = await self.profile_repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile_id,
            for_update=False,
        )
        if profile is None:
            raise RuntimeProfileResolutionUnavailable(
                code="runtime_profile_not_found",
                provider_id=None,
                message="The selected Workspace Runtime Profile was not found.",
            )
        infrastructure = await self.profile_repository.get_infrastructure_profile(
            session,
            profile_id=profile.infrastructure_profile_id,
            for_update=False,
        )
        if infrastructure is None:
            raise RuntimeProfileResolutionUnavailable(
                code="infrastructure_profile_not_found",
                provider_id=None,
                message="The selected infrastructure Profile was not found.",
            )
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=profile.provider_id,
            for_update=False,
        )
        if provider is None:
            raise RuntimeProfileResolutionUnavailable(
                code="provider_not_found",
                provider_id=None,
                message="The selected Runtime Provider was not found.",
            )
        resolution = await self._prepare_resolution(
            session,
            agent_selection_version=agent_selection_version,
            workspace_id=workspace_id,
            provider=provider,
            infrastructure=infrastructure,
            profile=profile,
        )
        return PreparedRuntimeProfileSelection(
            provider=provider,
            infrastructure=infrastructure,
            profile=profile,
            resolution=resolution,
        )

    async def attach_prepared_selection(
        self,
        session: AsyncSession,
        *,
        agent: Agent,
        runtime: AgentRuntime,
        prepared: PreparedRuntimeProfileSelection,
        runtime_created: bool,
    ) -> RuntimeProfileResolutionResult | None:
        """Attach one prepared selection through the exact source CAS."""
        resolution = prepared.resolution
        provider = prepared.provider
        infrastructure = prepared.infrastructure
        profile = prepared.profile
        revision = await self.profile_repository.create_or_get_configuration_revision(
            session,
            create=RuntimeConfigurationRevisionCreate(
                runtime_id=runtime.id,
                provider_id=provider.id,
                provider_capability_revision_id=(
                    resolution.capability_revision.id
                    if resolution.capability_revision is not None
                    else None
                ),
                infrastructure_profile_id=infrastructure.id,
                infrastructure_profile_version=infrastructure.version,
                workspace_runtime_profile_id=profile.id,
                workspace_runtime_profile_version=profile.version,
                agent_selection_version=agent.runtime_profile_selection_version,
                resolution_status=resolution.status,
                reason_code=resolution.reason_code,
                required_capabilities=infrastructure.required_capabilities,
                missing_capabilities=resolution.missing_capabilities,
                resolved_configuration=resolution.resolved_configuration,
                source_trace=resolution.source_trace,
                digest=resolution.digest,
                target_desired_generation=runtime.desired_generation,
            ),
        )
        attached = await self.runtime_repository.attach_desired_configuration_revision(
            session,
            runtime_id=runtime.id,
            expected_revision_id=runtime.desired_runtime_configuration_revision_id,
            expected_desired_generation=runtime.desired_generation,
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
            agent_selection_version=agent.runtime_profile_selection_version,
            provider_logical_id=provider.provider_id,
            provider_resource_id=provider.id,
            provider_admin_version=provider.admin_version,
            provider_capability_revision_id=provider.current_contract_revision_id,
            binding_origin=RuntimeProviderBindingOrigin.AGENT_EXPLICIT,
            binding_evidence={
                "workspace_id": agent.workspace_id,
                "agent_selection_version": agent.runtime_profile_selection_version,
                "workspace_runtime_profile_id": profile.id,
                "workspace_runtime_profile_version": profile.version,
                "infrastructure_profile_id": infrastructure.id,
                "infrastructure_profile_version": infrastructure.version,
                "provider_capability_revision_id": (
                    resolution.capability_revision.id
                    if resolution.capability_revision is not None
                    else None
                ),
            },
            infrastructure_profile_id=infrastructure.id,
            infrastructure_profile_version=infrastructure.version,
            workspace_runtime_profile_id=profile.id,
            workspace_runtime_profile_version=profile.version,
            configuration_revision_id=revision.id,
        )
        if attached is None:
            return None
        return RuntimeProfileResolutionResult(
            runtime=attached,
            desired_revision=revision,
            applied_revision=None,
            runtime_created=runtime_created,
        )

    async def ensure_for_agent(
        self,
        agent_id: str,
    ) -> RuntimeProfileResolutionResult:
        """Create or reconcile one Runtime from the Agent's exact selection."""
        for _ in range(2):
            resolution = await self._ensure_for_agent_once(agent_id)
            if resolution is not None:
                return resolution
        raise RuntimeProfileResolutionUnavailable(
            code="runtime_configuration_reconciling",
            provider_id=None,
            message="Runtime configuration is reconciling a concurrent change.",
        )

    async def _ensure_for_agent_once(
        self,
        agent_id: str,
    ) -> RuntimeProfileResolutionResult | None:
        """Resolve one lock-free source snapshot and attach it through final CAS."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                raise RuntimeProfileResolutionUnavailable(
                    code="agent_not_found",
                    provider_id=None,
                    message="Agent was not found.",
                )
            if agent.runtime_profile_id is None:
                raise RuntimeProfileResolutionUnavailable(
                    code="runtime_profile_required",
                    provider_id=None,
                    message=(
                        "A Runtime Profile must be selected before using a Runtime."
                    ),
                )

            existing = await self.runtime_repository.get_by_agent_id(session, agent.id)
            profile = await self.profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=agent.workspace_id,
                profile_id=agent.runtime_profile_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeProfileResolutionUnavailable(
                    code="runtime_profile_not_found",
                    provider_id=None,
                    message="The selected Workspace Runtime Profile was not found.",
                )
            infrastructure = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile.infrastructure_profile_id,
                for_update=False,
            )
            if infrastructure is None:
                raise RuntimeProfileResolutionUnavailable(
                    code="infrastructure_profile_not_found",
                    provider_id=None,
                    message="The selected infrastructure Profile was not found.",
                )
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=profile.provider_id,
                for_update=False,
            )
            if provider is None:
                raise RuntimeProfileResolutionUnavailable(
                    code="provider_not_found",
                    provider_id=None,
                    message="The selected Runtime Provider was not found.",
                )

            created = False
            if existing is None:
                ensured = await self.runtime_repository.ensure_with_create(
                    session,
                    create=AgentRuntimeCreate(
                        workspace_id=agent.workspace_id,
                        agent_id=agent.id,
                        runtime_provider_id=provider.provider_id,
                        runtime_provider_resource_id=provider.id,
                        provider_binding_origin=(
                            RuntimeProviderBindingOrigin.AGENT_EXPLICIT
                        ),
                        provider_binding_evidence=None,
                        infrastructure_profile_id=infrastructure.id,
                        workspace_runtime_profile_id=profile.id,
                        desired_runtime_configuration_revision_id=None,
                        applied_runtime_configuration_revision_id=None,
                    ),
                )
                existing = ensured.runtime
                created = ensured.created

            prepared = await self._prepare_resolution(
                session,
                agent_selection_version=agent.runtime_profile_selection_version,
                workspace_id=agent.workspace_id,
                provider=provider,
                infrastructure=infrastructure,
                profile=profile,
            )
            revision = (
                await self.profile_repository.create_or_get_configuration_revision(
                    session,
                    create=RuntimeConfigurationRevisionCreate(
                        runtime_id=existing.id,
                        provider_id=provider.id,
                        provider_capability_revision_id=(
                            prepared.capability_revision.id
                            if prepared.capability_revision is not None
                            else None
                        ),
                        infrastructure_profile_id=infrastructure.id,
                        infrastructure_profile_version=infrastructure.version,
                        workspace_runtime_profile_id=profile.id,
                        workspace_runtime_profile_version=profile.version,
                        agent_selection_version=(
                            agent.runtime_profile_selection_version
                        ),
                        resolution_status=prepared.status,
                        reason_code=prepared.reason_code,
                        required_capabilities=infrastructure.required_capabilities,
                        missing_capabilities=prepared.missing_capabilities,
                        resolved_configuration=prepared.resolved_configuration,
                        source_trace=prepared.source_trace,
                        digest=prepared.digest,
                        target_desired_generation=existing.desired_generation,
                    ),
                )
            )
            attach_desired = (
                self.runtime_repository.attach_desired_configuration_revision
            )
            attached = await attach_desired(
                session,
                runtime_id=existing.id,
                expected_revision_id=(
                    existing.desired_runtime_configuration_revision_id
                ),
                expected_desired_generation=existing.desired_generation,
                agent_id=agent.id,
                workspace_id=agent.workspace_id,
                agent_selection_version=agent.runtime_profile_selection_version,
                provider_logical_id=provider.provider_id,
                provider_resource_id=provider.id,
                provider_admin_version=provider.admin_version,
                provider_capability_revision_id=provider.current_contract_revision_id,
                binding_origin=RuntimeProviderBindingOrigin.AGENT_EXPLICIT,
                binding_evidence={
                    "workspace_id": agent.workspace_id,
                    "agent_selection_version": (
                        agent.runtime_profile_selection_version
                    ),
                    "workspace_runtime_profile_id": profile.id,
                    "workspace_runtime_profile_version": profile.version,
                    "infrastructure_profile_id": infrastructure.id,
                    "infrastructure_profile_version": infrastructure.version,
                    "provider_capability_revision_id": (
                        prepared.capability_revision.id
                        if prepared.capability_revision is not None
                        else None
                    ),
                },
                infrastructure_profile_id=infrastructure.id,
                infrastructure_profile_version=infrastructure.version,
                workspace_runtime_profile_id=profile.id,
                workspace_runtime_profile_version=profile.version,
                configuration_revision_id=revision.id,
            )
            if attached is None:
                current_agent = await self.agent_repository.get_by_id(session, agent.id)
                if current_agent is not None:
                    await self.profile_repository.enqueue_reconcile_task(
                        session,
                        source_type=RuntimeReconcileSourceKind.AGENT_SELECTION,
                        source_id=current_agent.id,
                        source_version=str(
                            current_agent.runtime_profile_selection_version
                        ),
                        available_at=tznow(),
                    )
                current_runtime = await self.runtime_repository.get_by_agent_id(
                    session,
                    agent.id,
                )
                if (
                    current_runtime is None
                    or current_runtime.desired_runtime_configuration_revision_id is None
                ):
                    return None
                current_revision = (
                    await self.profile_repository.get_configuration_revision(
                        session,
                        revision_id=(
                            current_runtime.desired_runtime_configuration_revision_id
                        ),
                    )
                )
                if current_revision is None:
                    return None
                if (
                    current_agent is None
                    or current_agent.runtime_profile_id
                    != current_revision.workspace_runtime_profile_id
                    or current_agent.runtime_profile_selection_version
                    != current_revision.agent_selection_version
                ):
                    return None
                applied_revision = None
                if (
                    current_runtime.applied_runtime_configuration_revision_id
                    is not None
                ):
                    get_revision = self.profile_repository.get_configuration_revision
                    applied_revision = await get_revision(
                        session,
                        revision_id=(
                            current_runtime.applied_runtime_configuration_revision_id
                        ),
                    )
                return RuntimeProfileResolutionResult(
                    runtime=current_runtime,
                    desired_revision=current_revision,
                    applied_revision=applied_revision,
                    runtime_created=False,
                )
            applied_revision = None
            if attached.applied_runtime_configuration_revision_id is not None:
                applied_revision = (
                    await self.profile_repository.get_configuration_revision(
                        session,
                        revision_id=(
                            attached.applied_runtime_configuration_revision_id
                        ),
                    )
                )
            return RuntimeProfileResolutionResult(
                runtime=attached,
                desired_revision=revision,
                applied_revision=applied_revision,
                runtime_created=created,
            )

    async def _prepare_resolution(
        self,
        session: AsyncSession,
        *,
        agent_selection_version: int,
        workspace_id: str,
        provider: RuntimeProvider,
        infrastructure: RuntimeInfrastructureProfile,
        profile: WorkspaceRuntimeProfile,
    ) -> PreparedRuntimeProfileResolution:
        """Validate current exact sources and build deterministic evidence."""
        capability_revision = None
        capability_digest = None
        contract = None
        reason_code = _source_reason(
            provider=provider,
            infrastructure=infrastructure,
            profile=profile,
        )
        if reason_code is None and (
            provider.availability_mode
            is RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES
            and not await self.provider_repository.is_available_to_workspace(
                session,
                provider_id=provider.id,
                workspace_id=workspace_id,
            )
        ):
            reason_code = "provider_workspace_unavailable"

        if provider.current_contract_revision_id is not None:
            capability_revision = (
                await self.provider_policy_repository.get_contract_by_id(
                    session,
                    contract_revision_id=provider.current_contract_revision_id,
                    for_update=False,
                )
            )
            if (
                capability_revision is None
                or capability_revision.provider_id != provider.id
            ):
                capability_revision = None
                if reason_code is None:
                    reason_code = "provider_capability_unavailable"
            else:
                capability_digest = capability_revision.digest
                try:
                    contract = RuntimeProviderCapabilityContract.model_validate(
                        capability_revision.contract
                    )
                except ValidationError:
                    if reason_code is None:
                        reason_code = "provider_capability_invalid"
        elif reason_code is None:
            reason_code = "provider_capability_unavailable"

        missing_capabilities: tuple[str, ...] = ()
        resolved_configuration = None
        try:
            spec = parse_runtime_infrastructure_profile_spec(infrastructure.spec)
            workspace_policy = WorkspaceRuntimeProfilePolicyV1.model_validate(
                profile.policy
            )
        except ValidationError:
            if reason_code is None:
                reason_code = "profile_document_invalid"
        else:
            if contract is not None:
                compatibility = evaluate_runtime_profile_compatibility(
                    spec,
                    contract.profile_contracts,
                )
                missing_capabilities = compatibility.missing_capabilities
                if not compatibility.compatible and reason_code is None:
                    reason_code = compatibility.reason_code or "profile_incompatible"
            if reason_code is None:
                try:
                    effective_spec = compose_workspace_runtime_profile(
                        spec,
                        workspace_policy,
                    )
                except ValueError as error:
                    reason_code = str(error)
                else:
                    resolved_configuration = {
                        "schema_version": 1,
                        "provider": {
                            "id": provider.id,
                            "logical_id": provider.provider_id,
                            "kind": provider.kind.value,
                            "capability_revision_id": (
                                capability_revision.id
                                if capability_revision is not None
                                else None
                            ),
                            "capability_digest": capability_digest,
                        },
                        "infrastructure_profile": {
                            "id": infrastructure.id,
                            "version": infrastructure.version,
                            "digest": infrastructure.digest,
                        },
                        "workspace_runtime_profile": {
                            "id": profile.id,
                            "version": profile.version,
                            "digest": profile.digest,
                        },
                        "effective_profile": effective_spec,
                    }

        status = (
            RuntimeConfigurationResolutionStatus.READY
            if reason_code is None
            else RuntimeConfigurationResolutionStatus.BLOCKED
        )
        source_trace = {
            "agent_selection_version": agent_selection_version,
            "provider_admin_version": provider.admin_version,
            "provider_capability_revision_id": (
                capability_revision.id if capability_revision is not None else None
            ),
            "provider_capability_digest": capability_digest,
            "infrastructure_profile_version": infrastructure.version,
            "infrastructure_profile_digest": infrastructure.digest,
            "workspace_runtime_profile_version": profile.version,
            "workspace_runtime_profile_digest": profile.digest,
        }
        digest = _resolution_digest(
            status=status,
            reason_code=reason_code,
            missing_capabilities=missing_capabilities,
            resolved_configuration=resolved_configuration,
            source_trace=source_trace,
        )
        return PreparedRuntimeProfileResolution(
            status=status,
            reason_code=reason_code,
            missing_capabilities=missing_capabilities,
            capability_revision=capability_revision,
            resolved_configuration=resolved_configuration,
            source_trace=source_trace,
            digest=digest,
        )


def _source_reason(
    *,
    provider: RuntimeProvider,
    infrastructure: RuntimeInfrastructureProfile,
    profile: WorkspaceRuntimeProfile,
) -> str | None:
    if profile.provider_id != provider.id:
        return "workspace_profile_provider_mismatch"
    if infrastructure.provider_id != provider.id:
        return "infrastructure_profile_provider_mismatch"
    if profile.infrastructure_profile_id != infrastructure.id:
        return "workspace_profile_infrastructure_mismatch"
    if profile.lifecycle is not RuntimeProfileLifecycle.ACTIVE:
        return "workspace_profile_disabled"
    if infrastructure.lifecycle is not RuntimeProfileLifecycle.ACTIVE:
        return "infrastructure_profile_disabled"
    if provider.scope is not RuntimeProviderScope.SYSTEM:
        return "provider_scope_unsupported"
    if provider.lifecycle_state is not RuntimeProviderLifecycleState.ACTIVE:
        return "provider_not_active"
    if not provider.enabled:
        return "provider_disabled"
    return None


def _resolution_digest(
    *,
    status: RuntimeConfigurationResolutionStatus,
    reason_code: str | None,
    missing_capabilities: tuple[str, ...],
    resolved_configuration: dict[str, Any] | None,
    source_trace: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "status": status.value,
            "reason_code": reason_code,
            "missing_capabilities": missing_capabilities,
            "resolved_configuration": resolved_configuration,
            "source_trace": source_trace,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
