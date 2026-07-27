"""Transactional Runtime Provider selection and immutable binding service."""

import dataclasses
import hashlib
import json
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimePolicySnapshotApplicationState,
    RuntimeProviderBindingOrigin,
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
    RuntimeProviderContractStatus,
    RuntimeProviderLifecycleState,
    RuntimeProviderScope,
)
from azents.core.platform_runtime_system_setting import PlatformRuntimeConfig
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract
from azents.core.system_setting import SystemSettingSection
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime, AgentRuntimeCreate
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.data import (
    RuntimePolicySnapshotCreate,
    RuntimeProviderConfigRevision,
    RuntimeProviderContractRevision,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository

from .data import (
    RuntimeProviderBindingResult,
    RuntimeProviderSelection,
    RuntimeProviderSelectionUnavailable,
)


@dataclasses.dataclass
class RuntimeProviderSelectionService:
    """Resolve one exact Provider candidate and persist an immutable Runtime binding."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    control_repository: Annotated[
        RuntimeProviderControlRepository,
        Depends(RuntimeProviderControlRepository),
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository,
        Depends(RuntimeProviderPolicyRepository),
    ]
    system_setting_repository: Annotated[
        SystemSettingRepository,
        Depends(SystemSettingRepository),
    ]

    async def ensure_for_agent(
        self,
        agent_id: str,
        *,
        requested_provider_id: str | None = None,
        required_capabilities: set[str] | None = None,
    ) -> RuntimeProviderBindingResult:
        """Ensure a Runtime using one transactionally resolved exact Provider."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_runtime_selection_input_for_update(
                session,
                agent_id=agent_id,
            )
            if agent is None:
                raise RuntimeProviderSelectionUnavailable(
                    code="agent_not_found",
                    provider_id=None,
                    message="Agent was not found.",
                )

            existing = await self.runtime_repository.get_by_agent_id_for_update(
                session,
                agent_id,
            )
            if existing is not None:
                if existing.runtime_policy_snapshot_id is None:
                    existing = await self._upgrade_existing_runtime(
                        session,
                        runtime=existing,
                        workspace_id=agent.workspace_id,
                        agent_runtime_provider_id=agent.runtime_provider_id,
                        requested_provider_id=requested_provider_id,
                        required_capabilities=required_capabilities,
                    )
                return RuntimeProviderBindingResult(
                    runtime=existing,
                    created=False,
                    selection=None,
                )

            selected_id, origin = await self.resolve_candidate_id(
                session,
                agent_runtime_provider_id=agent.runtime_provider_id,
                requested_provider_id=requested_provider_id,
            )
            provider = await self.provider_repository.get_by_provider_id_for_update(
                session,
                provider_logical_id=selected_id,
            )
            if provider is None:
                raise RuntimeProviderSelectionUnavailable(
                    code="provider_not_found",
                    provider_id=selected_id,
                    message="The selected Runtime Provider was not found.",
                )
            contract, active_config = await self.validate_provider_candidate(
                session,
                provider_logical_id=selected_id,
                provider=provider,
                workspace_id=agent.workspace_id,
                required_capabilities=required_capabilities,
            )
            binding_evidence = _binding_evidence(
                workspace_id=agent.workspace_id,
                origin=origin,
                provider=provider,
                contract=contract,
                active_config=active_config,
            )
            created = await self.runtime_repository.ensure_with_create(
                session,
                create=AgentRuntimeCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent.id,
                    runtime_provider_id=provider.provider_id,
                    runtime_provider_resource_id=provider.id,
                    provider_binding_origin=origin,
                    provider_binding_evidence=binding_evidence,
                    runtime_policy_snapshot_id=None,
                    applied_runtime_policy_snapshot_id=None,
                    provider_config=None,
                ),
            )
            if not created.created:
                return RuntimeProviderBindingResult(
                    runtime=created.runtime,
                    created=False,
                    selection=None,
                )

            snapshot = await self.policy_repository.create_snapshot(
                session,
                create=_initial_snapshot_create(
                    runtime=created.runtime,
                    provider=provider,
                    contract=contract,
                    active_config=active_config,
                    origin=origin,
                ),
            )
            if snapshot is None:
                raise RuntimeError("Runtime policy snapshot binding failed")
            runtime = await self.runtime_repository.get_by_id(
                session,
                created.runtime.id,
            )
            if runtime is None:
                raise RuntimeError("Created Agent Runtime could not be reloaded")
            return RuntimeProviderBindingResult(
                runtime=runtime,
                created=True,
                selection=RuntimeProviderSelection(
                    provider_resource_id=provider.id,
                    provider_logical_id=provider.provider_id,
                    binding_origin=origin,
                    binding_evidence=binding_evidence,
                ),
            )

    async def _upgrade_existing_runtime(
        self,
        session: AsyncSession,
        *,
        runtime: AgentRuntime,
        workspace_id: str,
        agent_runtime_provider_id: str | None,
        requested_provider_id: str | None,
        required_capabilities: set[str] | None,
    ) -> AgentRuntime:
        """Attach accepted policy evidence to a pre-contract Runtime."""
        if runtime.runtime_provider_resource_id is not None:
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=runtime.runtime_provider_resource_id,
                for_update=True,
            )
            origin = runtime.provider_binding_origin or (
                RuntimeProviderBindingOrigin.MIGRATION
            )
        else:
            if runtime.runtime_provider_id is not None:
                selected_id = runtime.runtime_provider_id
                origin = RuntimeProviderBindingOrigin.MIGRATION
            else:
                selected_id, origin = await self.resolve_candidate_id(
                    session,
                    agent_runtime_provider_id=agent_runtime_provider_id,
                    requested_provider_id=requested_provider_id,
                )
            provider = await self.provider_repository.get_by_provider_id_for_update(
                session,
                provider_logical_id=selected_id,
            )
        if provider is None:
            raise RuntimeProviderSelectionUnavailable(
                code="provider_not_found",
                provider_id=runtime.runtime_provider_id,
                message="The Runtime's bound Provider was not found.",
            )
        contract, active_config = await self.validate_provider_candidate(
            session,
            provider_logical_id=provider.provider_id,
            provider=provider,
            workspace_id=workspace_id,
            required_capabilities=required_capabilities,
        )
        binding_evidence = _binding_evidence(
            workspace_id=workspace_id,
            origin=origin,
            provider=provider,
            contract=contract,
            active_config=active_config,
        )
        bound = await self.runtime_repository.attach_provider_binding(
            session,
            runtime_id=runtime.id,
            provider_logical_id=provider.provider_id,
            provider_resource_id=provider.id,
            binding_origin=origin,
            binding_evidence=binding_evidence,
        )
        if bound is None:
            raise RuntimeProviderSelectionUnavailable(
                code="provider_binding_conflict",
                provider_id=provider.provider_id,
                message="The existing Runtime Provider binding conflicts.",
            )
        snapshot = await self.policy_repository.create_and_attach_target_snapshot(
            session,
            create=_initial_snapshot_create(
                runtime=bound,
                provider=provider,
                contract=contract,
                active_config=active_config,
                origin=origin,
            ),
            expected_target_snapshot_id=None,
        )
        if snapshot is None:
            raise RuntimeProviderSelectionUnavailable(
                code="runtime_policy_binding_conflict",
                provider_id=provider.provider_id,
                message="The existing Runtime policy binding changed concurrently.",
            )
        upgraded = await self.runtime_repository.get_by_id(session, runtime.id)
        if upgraded is None:
            raise RuntimeError("Upgraded Agent Runtime could not be reloaded")
        return upgraded

    async def resolve_candidate_id(
        self,
        session: AsyncSession,
        *,
        agent_runtime_provider_id: str | None,
        requested_provider_id: str | None,
    ) -> tuple[str, RuntimeProviderBindingOrigin]:
        """Resolve explicit preference before the Platform default without fallback."""
        explicit_id = requested_provider_id or agent_runtime_provider_id
        if explicit_id is not None:
            return explicit_id, RuntimeProviderBindingOrigin.AGENT_EXPLICIT
        current = await self.system_setting_repository.get_current(
            session,
            section=SystemSettingSection.PLATFORM_RUNTIME,
        )
        if current is None:
            raise RuntimeProviderSelectionUnavailable(
                code="platform_default_unset",
                provider_id=None,
                message="No Platform Runtime Provider default is configured.",
            )
        default_id = PlatformRuntimeConfig.model_validate(
            current.config
        ).default_provider_id
        if default_id is None:
            raise RuntimeProviderSelectionUnavailable(
                code="platform_default_unset",
                provider_id=None,
                message="No Platform Runtime Provider default is configured.",
            )
        return default_id, RuntimeProviderBindingOrigin.PLATFORM_DEFAULT

    async def validate_provider_candidate(
        self,
        session: AsyncSession,
        *,
        provider_logical_id: str,
        provider: RuntimeProvider,
        workspace_id: str,
        required_capabilities: set[str] | None,
    ) -> tuple[
        RuntimeProviderContractRevision,
        RuntimeProviderConfigRevision | None,
    ]:
        """Validate one exact Provider candidate.

        Return the accepted contract and active configuration revisions.
        """
        if provider.lifecycle_state != RuntimeProviderLifecycleState.ACTIVE:
            raise RuntimeProviderSelectionUnavailable(
                code="provider_not_active",
                provider_id=provider_logical_id,
                message="The selected Runtime Provider is not active.",
            )
        if not provider.enabled:
            raise RuntimeProviderSelectionUnavailable(
                code="provider_disabled",
                provider_id=provider_logical_id,
                message="The selected Runtime Provider is disabled.",
            )
        if provider.scope != RuntimeProviderScope.SYSTEM:
            raise RuntimeProviderSelectionUnavailable(
                code="provider_scope_unsupported",
                provider_id=provider_logical_id,
                message="The selected Provider is not a Platform Provider.",
            )
        if required_capabilities:
            available_capabilities = {
                str(capability)
                for capability in provider.capabilities.get(
                    "optional_capabilities",
                    provider.capabilities.get("capabilities", []),
                )
            }
            if required_capabilities - available_capabilities:
                raise RuntimeProviderSelectionUnavailable(
                    code="provider_capability_mismatch",
                    provider_id=provider_logical_id,
                    message=(
                        "The selected Provider cannot satisfy the Runtime capabilities."
                    ),
                )
        if provider.availability_mode.value == "selected_workspaces":
            if not await self.provider_repository.is_available_to_workspace(
                session,
                provider_id=provider.id,
                workspace_id=workspace_id,
            ):
                raise RuntimeProviderSelectionUnavailable(
                    code="provider_workspace_unavailable",
                    provider_id=provider_logical_id,
                    message="The selected Provider is unavailable to this Workspace.",
                )
        if not await self.control_repository.has_connected_connection(
            session,
            provider_id=provider.id,
            now=tznow(),
        ):
            raise RuntimeProviderSelectionUnavailable(
                code="provider_disconnected",
                provider_id=provider_logical_id,
                message="The selected Runtime Provider is disconnected.",
            )
        if provider.accepted_contract_revision_id is None:
            raise RuntimeProviderSelectionUnavailable(
                code="provider_contract_unaccepted",
                provider_id=provider_logical_id,
                message="The selected Provider has no accepted capability contract.",
            )
        contract = await self.policy_repository.get_contract_by_id(
            session,
            contract_revision_id=provider.accepted_contract_revision_id,
            for_update=False,
        )
        if (
            contract is None
            or contract.status != RuntimeProviderContractStatus.ACCEPTED
            or contract.provider_id != provider.id
        ):
            raise RuntimeProviderSelectionUnavailable(
                code="provider_contract_unaccepted",
                provider_id=provider_logical_id,
                message="The selected Provider has no accepted capability contract.",
            )
        parsed_contract = RuntimeProviderCapabilityContract.model_validate(
            contract.contract
        )
        active_config = await self.policy_repository.get_active_config(
            session,
            provider_id=provider.id,
        )
        if parsed_contract.configuration_fields and (
            active_config is None
            or active_config.state != RuntimeProviderConfigRevisionState.ACTIVE
            or active_config.validation_status
            != RuntimeProviderConfigValidationStatus.VALID
            or active_config.provider_id != provider.id
            or active_config.contract_revision_id != contract.id
        ):
            raise RuntimeProviderSelectionUnavailable(
                code="provider_configuration_unavailable",
                provider_id=provider_logical_id,
                message="The selected Provider has no active configuration.",
            )
        return contract, active_config


def _binding_evidence(
    *,
    workspace_id: str,
    origin: RuntimeProviderBindingOrigin,
    provider: RuntimeProvider,
    contract: RuntimeProviderContractRevision,
    active_config: RuntimeProviderConfigRevision | None,
) -> dict[str, object]:
    """Build sanitized immutable Runtime Provider binding evidence."""
    return {
        "workspace_id": workspace_id,
        "origin": origin.value,
        "provider_admin_version": provider.admin_version,
        "contract_revision_id": contract.id,
        "contract_digest": contract.digest,
        "config_revision_id": active_config.id if active_config else None,
    }


def _initial_snapshot_create(
    *,
    runtime: AgentRuntime,
    provider: RuntimeProvider,
    contract: RuntimeProviderContractRevision,
    active_config: RuntimeProviderConfigRevision | None,
    origin: RuntimeProviderBindingOrigin,
) -> RuntimePolicySnapshotCreate:
    """Build the first immutable policy target for one exact Runtime binding."""
    config = active_config.config if active_config else {}
    encrypted_secrets = active_config.encrypted_secrets if active_config else None
    secret_metadata = active_config.secret_metadata if active_config else {}
    return RuntimePolicySnapshotCreate(
        runtime_id=runtime.id,
        provider_id=provider.id,
        contract_revision_id=contract.id,
        config_revision_id=active_config.id if active_config else None,
        override_provider_id=None,
        override_version=None,
        execution_profile_id=None,
        execution_profile_version=None,
        execution_workspace_version=None,
        execution_agent_version=None,
        resolved_execution_policy=None,
        execution_source_trace=None,
        execution_provider_compatibility=None,
        execution_target_digest=None,
        execution_reported_digest=None,
        resolved_config=config,
        encrypted_secrets=encrypted_secrets,
        secret_metadata=secret_metadata,
        source_trace={
            "contract": contract.digest,
            "configuration": active_config.revision if active_config else None,
            "binding": origin.value,
        },
        digest=_snapshot_digest(
            runtime_id=runtime.id,
            provider_id=provider.id,
            contract_digest=contract.digest,
            config_revision_id=active_config.id if active_config else None,
            config=config,
            encrypted_secrets=encrypted_secrets,
            secret_metadata=secret_metadata,
            override_provider_id=None,
            override_version=None,
            target_desired_generation=runtime.desired_generation,
            origin=origin,
        ),
        target_desired_generation=runtime.desired_generation,
        application_state=RuntimePolicySnapshotApplicationState.PENDING,
    )


def _snapshot_digest(
    *,
    runtime_id: str,
    provider_id: str,
    contract_digest: str,
    config_revision_id: str | None,
    config: dict[str, object],
    encrypted_secrets: str | None,
    secret_metadata: dict[str, object],
    override_provider_id: str | None,
    override_version: int | None,
    target_desired_generation: int,
    origin: RuntimeProviderBindingOrigin,
) -> str:
    """Create a stable digest for one immutable Runtime policy snapshot."""
    payload = json.dumps(
        {
            "runtime_id": runtime_id,
            "provider_id": provider_id,
            "contract_digest": contract_digest,
            "config_revision_id": config_revision_id,
            "config": config,
            "encrypted_secrets": encrypted_secrets,
            "secret_metadata": secret_metadata,
            "override_provider_id": override_provider_id,
            "override_version": override_version,
            "target_desired_generation": target_desired_generation,
            "origin": origin.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()
