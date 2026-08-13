"""Workspace-owned Runtime Profile management and availability."""

import dataclasses
import hashlib
import json
import logging
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeProfileCompatibility,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
    WorkspaceRuntimeProfilePolicy,
    compose_workspace_runtime_profile,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_spec,
    parse_workspace_runtime_profile_policy,
)
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileCreate,
    WorkspaceRuntimeProfileDeletion,
    WorkspaceRuntimeProfileReplace,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import (
    Workspace,
    WorkspaceRuntimeProfileDefaultReplace,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeProfileProjection:
    """Workspace Profile plus current exact-reference availability."""

    profile: WorkspaceRuntimeProfile
    infrastructure_profile: RuntimeInfrastructureProfile
    provider: RuntimeProvider
    available: bool
    reason_code: str | None
    compatibility: RuntimeProfileCompatibility
    capability_revision_id: str | None


@dataclasses.dataclass(frozen=True)
class SelectableInfrastructureProfileProjection:
    """One exact Provider/Profile option available to a Workspace."""

    profile: RuntimeInfrastructureProfile
    provider: RuntimeProvider
    compatibility: RuntimeProfileCompatibility
    capability_revision_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeProfileDefaultProjection:
    """Workspace default and its current availability projection."""

    runtime_profile_id: str | None
    version: int
    profile: WorkspaceRuntimeProfileProjection | None


@dataclasses.dataclass
class RuntimeProfileWorkspaceUnavailable(Exception):
    """One bounded Workspace Runtime Profile failure."""

    code: str
    message: str
    current_profile: WorkspaceRuntimeProfile | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass
class RuntimeProfileWorkspaceService:
    """Manage complete Runtime choices owned by one Workspace."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository, Depends(RuntimeProviderPolicyRepository)
    ]
    control_repository: Annotated[
        RuntimeProviderControlRepository, Depends(RuntimeProviderControlRepository)
    ]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]

    async def get_default(
        self,
        workspace_id: str,
    ) -> WorkspaceRuntimeProfileDefaultProjection:
        """Return the Workspace default and current Profile availability."""
        async with self.session_manager() as session:
            workspace = await self.workspace_repository.get_by_id(
                session,
                workspace_id,
            )
            if workspace is None:
                raise RuntimeProfileWorkspaceUnavailable(
                    code="workspace_not_found",
                    message="Workspace was not found.",
                )
            return await self._project_default(session, workspace_id, workspace)

    async def replace_default(
        self,
        workspace_id: str,
        *,
        expected_version: int,
        runtime_profile_id: str | None,
    ) -> WorkspaceRuntimeProfileDefaultProjection:
        """Set or clear the Workspace default with optimistic fencing."""
        async with self.session_manager() as session:
            if runtime_profile_id is not None:
                profile = await self.profile_repository.get_workspace_runtime_profile(
                    session,
                    workspace_id=workspace_id,
                    profile_id=runtime_profile_id,
                    for_update=False,
                )
                if profile is None:
                    raise RuntimeProfileWorkspaceUnavailable(
                        code="profile_not_found",
                        message="Workspace Runtime Profile was not found.",
                    )
                if profile.lifecycle is not RuntimeProfileLifecycle.ACTIVE:
                    raise RuntimeProfileWorkspaceUnavailable(
                        code="workspace_profile_disabled",
                        message="A disabled Runtime Profile cannot be the default.",
                    )
            workspace = await self.workspace_repository.replace_runtime_profile_default(
                session,
                workspace_id,
                WorkspaceRuntimeProfileDefaultReplace(
                    expected_version=expected_version,
                    runtime_profile_id=runtime_profile_id,
                ),
            )
            if workspace is None:
                current = await self.workspace_repository.get_by_id(
                    session,
                    workspace_id,
                )
                if current is None:
                    raise RuntimeProfileWorkspaceUnavailable(
                        code="workspace_not_found",
                        message="Workspace was not found.",
                    )
                raise RuntimeProfileWorkspaceUnavailable(
                    code="default_version_conflict",
                    message="Workspace Runtime Profile default version is stale.",
                )
            return await self._project_default(session, workspace_id, workspace)

    async def resolve_agent_create_profile(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        explicit_profile_id: str | None,
    ) -> str | None:
        """Resolve explicit selection or copy one currently available default."""
        if explicit_profile_id is not None:
            await self.require_available_agent_profile(
                session,
                workspace_id=workspace_id,
                profile_id=explicit_profile_id,
            )
            return explicit_profile_id
        workspace = await self.workspace_repository.get_by_id_for_update(
            session,
            workspace_id,
        )
        if workspace is None:
            raise RuntimeProfileWorkspaceUnavailable(
                code="workspace_not_found",
                message="Workspace was not found.",
            )
        default_profile_id = workspace.default_runtime_profile_id
        if default_profile_id is None:
            return None
        profile = await self.profile_repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=default_profile_id,
            for_update=False,
        )
        if profile is None:
            return None
        projection = await self._project(session, workspace_id, profile)
        return profile.id if projection.available else None

    async def require_available_agent_profile(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        profile_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Require an exact currently available Profile owned by the Workspace."""
        profile = await self.profile_repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile_id,
            for_update=False,
        )
        if profile is None:
            raise RuntimeProfileWorkspaceUnavailable(
                code="profile_not_found",
                message="Workspace Runtime Profile was not found.",
            )
        projection = await self._project(session, workspace_id, profile)
        if not projection.available:
            raise RuntimeProfileWorkspaceUnavailable(
                code=projection.reason_code or "profile_unavailable",
                message="Workspace Runtime Profile is currently unavailable.",
                current_profile=profile,
            )
        return projection

    async def list_profiles(
        self,
        workspace_id: str,
        *,
        include_disabled: bool,
    ) -> list[WorkspaceRuntimeProfileProjection]:
        """List Workspace Profiles with current availability evidence."""
        async with self.session_manager() as session:
            profiles = await self.profile_repository.list_workspace_runtime_profiles(
                session,
                workspace_id=workspace_id,
                include_disabled=include_disabled,
            )
            return [
                await self._project(session, workspace_id, profile)
                for profile in profiles
            ]

    async def get_profile(
        self,
        workspace_id: str,
        profile_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Get one Workspace-owned Runtime Profile."""
        async with self.session_manager() as session:
            profile = await self.profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=workspace_id,
                profile_id=profile_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeProfileWorkspaceUnavailable(
                    code="profile_not_found",
                    message="Workspace Runtime Profile was not found.",
                )
            return await self._project(session, workspace_id, profile)

    async def create_profile(
        self,
        workspace_id: str,
        *,
        infrastructure_profile_id: str,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        policy: WorkspaceRuntimeProfilePolicy,
        actor_workspace_user_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Create one complete Workspace Runtime choice."""
        async with self.session_manager() as session:
            infrastructure = await self._require_infrastructure(
                session,
                infrastructure_profile_id,
            )
            self._require_valid_workspace_policy(
                infrastructure=infrastructure,
                policy=policy,
            )
            await self._require_selectable_workspace_profile(
                session,
                workspace_id=workspace_id,
                infrastructure=infrastructure,
                policy=policy,
            )
            try:
                profile = (
                    await self.profile_repository.create_workspace_runtime_profile(
                        session,
                        create=WorkspaceRuntimeProfileCreate(
                            workspace_id=workspace_id,
                            provider_id=infrastructure.provider_id,
                            infrastructure_profile_id=infrastructure.id,
                            display_name=display_name,
                            description=description,
                            lifecycle=lifecycle,
                            policy=policy.model_dump(mode="json"),
                            digest=_workspace_profile_digest(
                                infrastructure=infrastructure,
                                policy=policy,
                            ),
                            actor_workspace_user_id=actor_workspace_user_id,
                        ),
                    )
                )
            except IntegrityError as error:
                raise RuntimeProfileWorkspaceUnavailable(
                    code="profile_name_conflict",
                    message="A Runtime Profile with this name already exists.",
                ) from error
            await self.profile_repository.enqueue_reconcile_task(
                session,
                source_type=RuntimeReconcileSourceKind.WORKSPACE_RUNTIME_PROFILE,
                source_id=profile.id,
                source_version=str(profile.version),
                available_at=tznow(),
            )
            return await self._project(session, workspace_id, profile)

    async def replace_profile(
        self,
        workspace_id: str,
        profile_id: str,
        *,
        expected_version: int,
        infrastructure_profile_id: str,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        policy: WorkspaceRuntimeProfilePolicy,
        actor_workspace_user_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Replace one Workspace Profile with optimistic version fencing."""
        async with self.session_manager() as session:
            current = await self.profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=workspace_id,
                profile_id=profile_id,
                for_update=False,
            )
            if current is None:
                raise RuntimeProfileWorkspaceUnavailable(
                    code="profile_not_found",
                    message="Workspace Runtime Profile was not found.",
                )
            infrastructure = await self._require_infrastructure(
                session,
                infrastructure_profile_id,
            )
            self._require_valid_workspace_policy(
                infrastructure=infrastructure,
                policy=policy,
            )
            if lifecycle is RuntimeProfileLifecycle.ACTIVE:
                await self._require_selectable_workspace_profile(
                    session,
                    workspace_id=workspace_id,
                    infrastructure=infrastructure,
                    policy=policy,
                )
            try:
                profile = (
                    await self.profile_repository.replace_workspace_runtime_profile(
                        session,
                        workspace_id=workspace_id,
                        profile_id=profile_id,
                        expected_version=expected_version,
                        replacement=WorkspaceRuntimeProfileReplace(
                            provider_id=infrastructure.provider_id,
                            infrastructure_profile_id=infrastructure.id,
                            display_name=display_name,
                            description=description,
                            lifecycle=lifecycle,
                            policy=policy.model_dump(mode="json"),
                            digest=_workspace_profile_digest(
                                infrastructure=infrastructure,
                                policy=policy,
                            ),
                            actor_workspace_user_id=actor_workspace_user_id,
                        ),
                    )
                )
            except IntegrityError as error:
                raise RuntimeProfileWorkspaceUnavailable(
                    code="profile_name_conflict",
                    message="A Runtime Profile with this name already exists.",
                ) from error
            if profile is None:
                latest = await self.profile_repository.get_workspace_runtime_profile(
                    session,
                    workspace_id=workspace_id,
                    profile_id=profile_id,
                    for_update=False,
                )
                raise RuntimeProfileWorkspaceUnavailable(
                    code="profile_version_conflict",
                    message="Workspace Runtime Profile version is stale.",
                    current_profile=latest,
                )
            await self.profile_repository.enqueue_reconcile_task(
                session,
                source_type=RuntimeReconcileSourceKind.WORKSPACE_RUNTIME_PROFILE,
                source_id=profile.id,
                source_version=str(profile.version),
                available_at=tznow(),
            )
            return await self._project(session, workspace_id, profile)

    async def delete_profile(
        self,
        workspace_id: str,
        profile_id: str,
        *,
        expected_version: int,
        actor_workspace_user_id: str,
    ) -> WorkspaceRuntimeProfileDeletion:
        """Permanently delete one exact Workspace Profile and live selection."""
        async with self.session_manager() as session:
            try:
                outcome = (
                    await self.profile_repository.delete_workspace_runtime_profile(
                        session,
                        workspace_id=workspace_id,
                        profile_id=profile_id,
                        expected_version=expected_version,
                    )
                )
            except IntegrityError as error:
                raise RuntimeProfileWorkspaceUnavailable(
                    code="runtime_profile_delete_conflict",
                    message=(
                        "Runtime Profile deletion conflicted with a concurrent change."
                    ),
                ) from error
            if outcome.deletion is None:
                if outcome.current_profile is None:
                    raise RuntimeProfileWorkspaceUnavailable(
                        code="runtime_profile_not_found",
                        message="Workspace Runtime Profile was not found.",
                    )
                raise RuntimeProfileWorkspaceUnavailable(
                    code="runtime_profile_version_conflict",
                    message="Workspace Runtime Profile version is stale.",
                    current_profile=outcome.current_profile,
                )
            deletion = outcome.deletion

        logger.info(
            "Workspace Runtime Profile deleted",
            extra={
                "workspace_id": workspace_id,
                "profile_id": profile_id,
                "profile_version": expected_version,
                "actor_workspace_user_id": actor_workspace_user_id,
                "cleared_workspace_default": deletion.cleared_workspace_default,
                "cleared_agent_count": deletion.cleared_agent_count,
                "affected_running_runtime_count": (
                    deletion.affected_running_runtime_count
                ),
                "superseded_recreation_operation_count": (
                    deletion.superseded_recreation_operation_count
                ),
            },
        )
        return deletion

    async def list_selectable_infrastructure(
        self,
        workspace_id: str,
    ) -> list[SelectableInfrastructureProfileProjection]:
        """List active compatible infrastructure Profiles for one Workspace."""
        async with self.session_manager() as session:
            providers = await self.provider_repository.list_available(
                session,
                workspace_id=workspace_id,
                include_disabled=False,
            )
            selectable: list[SelectableInfrastructureProfileProjection] = []
            for provider in providers:
                if not await self._provider_ready_for_workspace(
                    session,
                    provider=provider,
                    workspace_id=workspace_id,
                ):
                    continue
                profiles = await self.profile_repository.list_infrastructure_profiles(
                    session,
                    provider_id=provider.id,
                    include_disabled=False,
                )
                for profile in profiles:
                    projection = await self._infrastructure_compatibility(
                        session,
                        provider=provider,
                        infrastructure=profile,
                    )
                    if projection.compatible:
                        if provider.current_contract_revision_id is None:
                            raise AssertionError(
                                "Ready Provider lost its capability revision."
                            )
                        selectable.append(
                            SelectableInfrastructureProfileProjection(
                                profile=profile,
                                provider=provider,
                                compatibility=projection,
                                capability_revision_id=(
                                    provider.current_contract_revision_id
                                ),
                            )
                        )
            return sorted(
                selectable,
                key=lambda item: (
                    item.provider.display_name,
                    item.profile.display_name,
                    item.profile.id,
                ),
            )

    async def _project(
        self,
        session: AsyncSession,
        workspace_id: str,
        profile: WorkspaceRuntimeProfile,
    ) -> WorkspaceRuntimeProfileProjection:
        infrastructure = await self._require_infrastructure(
            session,
            profile.infrastructure_profile_id,
        )
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=profile.provider_id,
            for_update=False,
        )
        if provider is None:
            raise AssertionError("Workspace Runtime Profile Provider is missing.")
        unavailable = RuntimeProfileCompatibility(
            compatible=False,
            reason_code="provider_unavailable",
            missing_capabilities=(),
            incompatible_constraints=(),
        )
        if profile.lifecycle is not RuntimeProfileLifecycle.ACTIVE:
            return WorkspaceRuntimeProfileProjection(
                profile=profile,
                infrastructure_profile=infrastructure,
                provider=provider,
                available=False,
                reason_code="workspace_profile_disabled",
                compatibility=unavailable,
                capability_revision_id=None,
            )
        if (
            infrastructure.lifecycle is not RuntimeProfileLifecycle.ACTIVE
            or infrastructure.provider_id != profile.provider_id
        ):
            return WorkspaceRuntimeProfileProjection(
                profile=profile,
                infrastructure_profile=infrastructure,
                provider=provider,
                available=False,
                reason_code="infrastructure_profile_unavailable",
                compatibility=unavailable,
                capability_revision_id=None,
            )
        if not await self._provider_ready_for_workspace(
            session,
            provider=provider,
            workspace_id=workspace_id,
        ):
            return WorkspaceRuntimeProfileProjection(
                profile=profile,
                infrastructure_profile=infrastructure,
                provider=provider,
                available=False,
                reason_code="provider_unavailable",
                compatibility=unavailable,
                capability_revision_id=provider.current_contract_revision_id,
            )
        compatibility = await self._workspace_profile_compatibility(
            session,
            provider=provider,
            infrastructure=infrastructure,
            policy_payload=profile.policy,
        )
        try:
            workspace_policy = parse_workspace_runtime_profile_policy(profile.policy)
            spec = parse_runtime_infrastructure_profile_spec(infrastructure.spec)
            compose_workspace_runtime_profile(spec, workspace_policy)
        except ValidationError:
            return WorkspaceRuntimeProfileProjection(
                profile=profile,
                infrastructure_profile=infrastructure,
                provider=provider,
                available=False,
                reason_code="workspace_policy_invalid",
                compatibility=compatibility,
                capability_revision_id=provider.current_contract_revision_id,
            )
        except ValueError as error:
            return WorkspaceRuntimeProfileProjection(
                profile=profile,
                infrastructure_profile=infrastructure,
                provider=provider,
                available=False,
                reason_code=str(error),
                compatibility=compatibility,
                capability_revision_id=provider.current_contract_revision_id,
            )
        return WorkspaceRuntimeProfileProjection(
            profile=profile,
            infrastructure_profile=infrastructure,
            provider=provider,
            available=compatibility.compatible,
            reason_code=compatibility.reason_code,
            compatibility=compatibility,
            capability_revision_id=provider.current_contract_revision_id,
        )

    async def _require_infrastructure(
        self,
        session: AsyncSession,
        profile_id: str,
    ) -> RuntimeInfrastructureProfile:
        profile = await self.profile_repository.get_infrastructure_profile(
            session,
            profile_id=profile_id,
            for_update=False,
        )
        if profile is None:
            raise RuntimeProfileWorkspaceUnavailable(
                code="infrastructure_profile_not_found",
                message="Runtime infrastructure Profile was not found.",
            )
        return profile

    async def _project_default(
        self,
        session: AsyncSession,
        workspace_id: str,
        workspace: Workspace,
    ) -> WorkspaceRuntimeProfileDefaultProjection:
        profile_id = workspace.default_runtime_profile_id
        if profile_id is None:
            return WorkspaceRuntimeProfileDefaultProjection(
                runtime_profile_id=None,
                version=workspace.default_runtime_profile_version,
                profile=None,
            )
        profile = await self.profile_repository.get_workspace_runtime_profile(
            session,
            workspace_id=workspace_id,
            profile_id=profile_id,
            for_update=False,
        )
        if profile is None:
            raise AssertionError("Workspace default Runtime Profile is missing.")
        return WorkspaceRuntimeProfileDefaultProjection(
            runtime_profile_id=profile_id,
            version=workspace.default_runtime_profile_version,
            profile=await self._project(session, workspace_id, profile),
        )

    async def _require_selectable_infrastructure(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        infrastructure: RuntimeInfrastructureProfile,
    ) -> None:
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=infrastructure.provider_id,
            for_update=False,
        )
        if (
            provider is None
            or infrastructure.lifecycle is not RuntimeProfileLifecycle.ACTIVE
            or not await self._provider_ready_for_workspace(
                session,
                provider=provider,
                workspace_id=workspace_id,
            )
        ):
            raise RuntimeProfileWorkspaceUnavailable(
                code="infrastructure_profile_unavailable",
                message="Runtime infrastructure Profile is not selectable.",
            )
        compatibility = await self._infrastructure_compatibility(
            session,
            provider=provider,
            infrastructure=infrastructure,
        )
        if not compatibility.compatible:
            raise RuntimeProfileWorkspaceUnavailable(
                code=compatibility.reason_code or "infrastructure_profile_unavailable",
                message="Runtime infrastructure Profile is incompatible.",
            )

    async def _require_selectable_workspace_profile(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        infrastructure: RuntimeInfrastructureProfile,
        policy: WorkspaceRuntimeProfilePolicy,
    ) -> None:
        """Require current Provider support for the effective Workspace Profile."""
        await self._require_selectable_infrastructure(
            session,
            workspace_id=workspace_id,
            infrastructure=infrastructure,
        )
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=infrastructure.provider_id,
            for_update=False,
        )
        if provider is None:
            raise RuntimeProfileWorkspaceUnavailable(
                code="infrastructure_profile_unavailable",
                message="Runtime infrastructure Profile is not selectable.",
            )
        compatibility = await self._workspace_profile_compatibility(
            session,
            provider=provider,
            infrastructure=infrastructure,
            policy_payload=policy.model_dump(mode="json"),
        )
        if not compatibility.compatible:
            raise RuntimeProfileWorkspaceUnavailable(
                code=compatibility.reason_code or "profile_incompatible",
                message="Workspace Runtime Profile is incompatible.",
            )

    @staticmethod
    def _require_valid_workspace_policy(
        *,
        infrastructure: RuntimeInfrastructureProfile,
        policy: WorkspaceRuntimeProfilePolicy,
    ) -> None:
        """Require policy composition to match Runtime resolution semantics."""
        spec = parse_runtime_infrastructure_profile_spec(infrastructure.spec)
        try:
            compose_workspace_runtime_profile(spec, policy)
        except ValueError as error:
            raise RuntimeProfileWorkspaceUnavailable(
                code=str(error),
                message="Workspace Runtime Profile policy is invalid.",
            ) from error

    async def _provider_ready_for_workspace(
        self,
        session: AsyncSession,
        *,
        provider: RuntimeProvider,
        workspace_id: str,
    ) -> bool:
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

    async def _infrastructure_compatibility(
        self,
        session: AsyncSession,
        *,
        provider: RuntimeProvider,
        infrastructure: RuntimeInfrastructureProfile,
    ) -> RuntimeProfileCompatibility:
        revision_id = provider.current_contract_revision_id
        if revision_id is None:
            return _unavailable_compatibility("provider_capability_unavailable")
        revision = await self.policy_repository.get_contract_by_id(
            session,
            contract_revision_id=revision_id,
            for_update=False,
        )
        if revision is None or revision.provider_id != provider.id:
            return _unavailable_compatibility("provider_capability_unavailable")
        try:
            contract = RuntimeProviderCapabilityContract.model_validate(
                revision.contract
            )
            spec = parse_runtime_infrastructure_profile_spec(infrastructure.spec)
        except ValidationError:
            return _unavailable_compatibility("profile_document_invalid")
        return evaluate_runtime_profile_compatibility(
            spec,
            contract.profile_contracts,
            provider_protocol_version=contract.protocol_version,
        )

    async def _workspace_profile_compatibility(
        self,
        session: AsyncSession,
        *,
        provider: RuntimeProvider,
        infrastructure: RuntimeInfrastructureProfile,
        policy_payload: dict[str, object],
    ) -> RuntimeProfileCompatibility:
        """Evaluate the composed effective Profile against current capability."""
        revision_id = provider.current_contract_revision_id
        if revision_id is None:
            return _unavailable_compatibility("provider_capability_unavailable")
        revision = await self.policy_repository.get_contract_by_id(
            session,
            contract_revision_id=revision_id,
            for_update=False,
        )
        if revision is None or revision.provider_id != provider.id:
            return _unavailable_compatibility("provider_capability_unavailable")
        try:
            contract = RuntimeProviderCapabilityContract.model_validate(
                revision.contract
            )
            spec = parse_runtime_infrastructure_profile_spec(infrastructure.spec)
            policy = parse_workspace_runtime_profile_policy(policy_payload)
            effective = parse_runtime_infrastructure_profile_spec(
                compose_workspace_runtime_profile(spec, policy)
            )
        except ValidationError:
            return _unavailable_compatibility("profile_document_invalid")
        except ValueError as error:
            return _unavailable_compatibility(str(error))
        return evaluate_runtime_profile_compatibility(
            effective,
            contract.profile_contracts,
            provider_protocol_version=contract.protocol_version,
        )


def _unavailable_compatibility(reason_code: str) -> RuntimeProfileCompatibility:
    return RuntimeProfileCompatibility(
        compatible=False,
        reason_code=reason_code,
        missing_capabilities=(),
        incompatible_constraints=(),
    )


def _workspace_profile_digest(
    *,
    infrastructure: RuntimeInfrastructureProfile,
    policy: WorkspaceRuntimeProfilePolicy,
) -> str:
    document = {
        "provider_id": infrastructure.provider_id,
        "infrastructure_profile_id": infrastructure.id,
        "infrastructure_profile_digest": infrastructure.digest,
        "policy": policy.model_dump(mode="json"),
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
