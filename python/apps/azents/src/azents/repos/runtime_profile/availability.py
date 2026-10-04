"""Database-only Runtime Profile availability composition."""

import dataclasses
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends
from pydantic import ValidationError

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeProfileLifecycle,
    compose_workspace_runtime_profile,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_spec,
    parse_workspace_runtime_profile_policy,
)
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract
from azents.core.runtime_provider_data import RuntimeProvider
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)


@dataclasses.dataclass
class RuntimeProfileAvailabilityRepository:
    """Evaluate Agent Runtime Profile availability within a caller transaction."""

    profile_repository: Annotated[
        RuntimeProfileRepository,
        Depends(RuntimeProfileRepository),
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository,
        Depends(RuntimeProviderRepository),
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository,
        Depends(RuntimeProviderPolicyRepository),
    ]
    control_repository: Annotated[
        RuntimeProviderControlRepository,
        Depends(RuntimeProviderControlRepository),
    ]

    async def get_agent_profile_unavailability_code(
        self,
        session: WriteSession,
        *,
        workspace_id: str,
        profile_id: str,
    ) -> str | None:
        """Return the current rejection code, or ``None`` when selectable."""
        profile = await self.profile_repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile_id,
        )
        if profile is None:
            return "profile_not_found"
        infrastructure = await self.profile_repository.get_infrastructure_profile(
            session,
            profile_id=profile.infrastructure_profile_id,
        )
        if infrastructure is None:
            return "infrastructure_profile_not_found"
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=profile.provider_id,
            for_update=False,
        )
        if provider is None:
            raise AssertionError("Workspace Runtime Profile Provider is missing.")
        if profile.lifecycle is not RuntimeProfileLifecycle.ACTIVE:
            return "workspace_profile_disabled"
        if (
            infrastructure.lifecycle is not RuntimeProfileLifecycle.ACTIVE
            or infrastructure.provider_id != profile.provider_id
        ):
            return "infrastructure_profile_unavailable"
        if not await self._provider_ready_for_workspace(
            session,
            provider=provider,
            workspace_id=workspace_id,
        ):
            return "provider_unavailable"

        compatibility_error = await self._workspace_compatibility_error(
            session,
            provider=provider,
            infrastructure_spec=infrastructure.spec,
            policy_payload=profile.policy,
        )
        try:
            policy = parse_workspace_runtime_profile_policy(profile.policy)
            spec = parse_runtime_infrastructure_profile_spec(infrastructure.spec)
            compose_workspace_runtime_profile(spec, policy)
        except ValidationError:
            return "workspace_policy_invalid"
        except ValueError as error:
            return str(error)
        return compatibility_error

    async def _provider_ready_for_workspace(
        self,
        session: WriteSession,
        *,
        provider: RuntimeProvider,
        workspace_id: str,
    ) -> bool:
        """Return whether the Provider is currently selectable by the Workspace."""
        if (
            provider.scope is not RuntimeProviderScope.SYSTEM
            or not provider.enabled
            or provider.lifecycle_state is not RuntimeProviderLifecycleState.ACTIVE
            or provider.current_contract_revision_id is None
        ):
            return False
        if (
            provider.availability_mode
            is RuntimeProviderAvailabilityMode.SELECTED_WORKSPACES
            and not await self.provider_repository.is_available_to_workspace(
                session,
                provider_id=provider.id,
                workspace_id=workspace_id,
            )
        ):
            return False
        return await self.control_repository.has_connected_connection(
            session,
            provider_id=provider.id,
            now=tznow(),
        )

    async def _workspace_compatibility_error(
        self,
        session: WriteSession,
        *,
        provider: RuntimeProvider,
        infrastructure_spec: dict[str, object],
        policy_payload: dict[str, object],
    ) -> str | None:
        """Return current composed-profile incompatibility reason."""
        revision_id = provider.current_contract_revision_id
        if revision_id is None:
            return "provider_capability_unavailable"
        revision = await self.policy_repository.get_contract_by_id(
            session,
            contract_revision_id=revision_id,
        )
        if revision is None or revision.provider_id != provider.id:
            return "provider_capability_unavailable"
        try:
            contract = RuntimeProviderCapabilityContract.model_validate(
                revision.contract
            )
            spec = parse_runtime_infrastructure_profile_spec(infrastructure_spec)
            policy = parse_workspace_runtime_profile_policy(policy_payload)
            effective = parse_runtime_infrastructure_profile_spec(
                compose_workspace_runtime_profile(spec, policy)
            )
        except ValidationError:
            return "profile_document_invalid"
        except ValueError as error:
            return str(error)
        compatibility = evaluate_runtime_profile_compatibility(
            effective,
            contract.profile_contracts,
            provider_protocol_version=contract.protocol_version,
        )
        return None if compatibility.compatible else compatibility.reason_code
