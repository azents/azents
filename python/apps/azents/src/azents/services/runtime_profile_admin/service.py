"""System-Admin orchestration for completed infrastructure Profile operations."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileInternalSpec,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileCompatibility,
    RuntimeProfileLifecycle,
)
from azents.core.runtime_provider_data import RuntimeProvider
from azents.repos.runtime_profile.admin_operations import (
    InfrastructureProfileSnapshot,
    ProfileAdminOperationUnavailable,
    RuntimeProfileAdminOperationsRepository,
)
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    RuntimeInfrastructureProfileDeletion,
    RuntimeInfrastructureProfileDeletionImpact,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileUsage,
)
from azents.repos.workspace.data import Workspace
from azents.services.terminal_policy.invalidation import (
    TerminalPolicyInvalidationPublisherDependency,
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class RuntimeInfrastructureProfileProjection:
    """Infrastructure Profile plus current Provider compatibility evidence."""

    profile: RuntimeInfrastructureProfile
    compatibility: RuntimeProfileCompatibility
    capability_revision_id: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeInfrastructureProfileDeletionImpactProjection:
    """Infrastructure Profile plus current deletion impact."""

    profile: RuntimeInfrastructureProfile
    impact: RuntimeInfrastructureProfileDeletionImpact


@dataclasses.dataclass(frozen=True)
class AdminWorkspaceRuntimeProfileDetailProjection:
    """System-Admin read-only Workspace Runtime Profile detail."""

    workspace_id: str
    workspace: Workspace
    profile: WorkspaceRuntimeProfile
    infrastructure_profile: RuntimeInfrastructureProfile
    provider: RuntimeProvider
    usage: WorkspaceRuntimeProfileUsage


@dataclasses.dataclass
class RuntimeProfileAdminUnavailable(Exception):
    """One bounded infrastructure Profile management failure."""

    code: str
    message: str
    current_profile: RuntimeInfrastructureProfile | None = None
    blocking_reference_count: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


def _projection(
    snapshot: InfrastructureProfileSnapshot,
) -> RuntimeInfrastructureProfileProjection:
    """Present detached compatibility evidence after repository completion."""
    return RuntimeInfrastructureProfileProjection(
        profile=snapshot.profile,
        compatibility=snapshot.compatibility,
        capability_revision_id=snapshot.capability_revision_id,
    )


def _unavailable(
    error: ProfileAdminOperationUnavailable,
) -> RuntimeProfileAdminUnavailable:
    """Preserve the public failure contract for completed database operations."""
    return RuntimeProfileAdminUnavailable(
        code=error.code,
        message=error.message,
        current_profile=error.current_profile,
        blocking_reference_count=error.blocking_reference_count,
    )


@dataclasses.dataclass
class RuntimeProfileAdminService:
    """Present Profile operations and publish required postcommit invalidation."""

    repository: Annotated[
        RuntimeProfileAdminOperationsRepository,
        Depends(RuntimeProfileAdminOperationsRepository),
    ]
    terminal_policy_invalidation_publisher: (
        TerminalPolicyInvalidationPublisherDependency
    )

    async def list_profiles(
        self,
        provider_logical_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        include_disabled: bool,
    ) -> list[RuntimeInfrastructureProfileProjection]:
        """List one Provider's Profiles with current compatibility."""
        try:
            snapshots = await self.repository.list_profiles(
                provider_logical_id,
                profile_kind=profile_kind,
                include_disabled=include_disabled,
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return [_projection(snapshot) for snapshot in snapshots]

    async def get_profile(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
    ) -> RuntimeInfrastructureProfileProjection:
        """Get one exact Provider-owned Profile."""
        try:
            snapshot = await self.repository.get_profile(
                provider_logical_id, profile_id, profile_kind=profile_kind
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return _projection(snapshot)

    async def create_profile(
        self,
        provider_logical_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        spec: RuntimeInfrastructureProfileInternalSpec,
        terminal_enabled: bool,
        actor_user_id: str,
    ) -> RuntimeInfrastructureProfileProjection:
        """Create a typed Profile and enqueue its source version atomically."""
        try:
            snapshot = await self.repository.create_profile(
                provider_logical_id,
                profile_kind=profile_kind,
                display_name=display_name,
                description=description,
                lifecycle=lifecycle,
                spec=spec,
                terminal_enabled=terminal_enabled,
                actor_user_id=actor_user_id,
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return _projection(snapshot)

    async def replace_profile(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        expected_version: int,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        spec: RuntimeInfrastructureProfileInternalSpec,
        terminal_enabled: bool,
        actor_user_id: str,
    ) -> RuntimeInfrastructureProfileProjection:
        """Complete replacement before publishing terminal-policy invalidation."""
        try:
            outcome = await self.repository.replace_profile(
                provider_logical_id,
                profile_id,
                profile_kind=profile_kind,
                expected_version=expected_version,
                display_name=display_name,
                description=description,
                lifecycle=lifecycle,
                spec=spec,
                terminal_enabled=terminal_enabled,
                actor_user_id=actor_user_id,
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        if outcome.terminal_changed:
            profile = outcome.projection.profile
            publisher = self.terminal_policy_invalidation_publisher
            await publisher.publish_terminal_policy_invalidation(
                TerminalPolicySourceInvalidation(
                    scope=TerminalPolicySourceScope.INFRASTRUCTURE_PROFILE,
                    source_id=profile.id,
                    source_version=str(profile.version),
                )
            )
        return _projection(outcome.projection)

    async def get_profile_deletion_impact(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        offset: int,
        limit: int,
    ) -> RuntimeInfrastructureProfileDeletionImpactProjection:
        """Return fresh bounded impact from a completed read operation."""
        try:
            snapshot = await self.repository.get_profile_deletion_impact(
                provider_logical_id,
                profile_id,
                profile_kind=profile_kind,
                offset=offset,
                limit=limit,
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        logger.info(
            "Projected infrastructure Profile deletion impact",
            extra={
                "provider_id": provider_logical_id,
                "infrastructure_profile_id": snapshot.profile.id,
                "infrastructure_profile_kind": snapshot.profile.profile_kind.value,
                "infrastructure_profile_version": snapshot.profile.version,
                "blocking_reference_count": snapshot.impact.blocking_reference_count,
                "applied_only_running_runtime_count": (
                    snapshot.impact.applied_only_running_runtime_count
                ),
            },
        )
        return RuntimeInfrastructureProfileDeletionImpactProjection(
            profile=snapshot.profile, impact=snapshot.impact
        )

    async def delete_profile(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        expected_version: int,
        actor_user_id: str,
    ) -> RuntimeInfrastructureProfileDeletion:
        """Delete one unreferenced Profile and log the completed outcome."""
        try:
            deletion = await self.repository.delete_profile(
                provider_logical_id,
                profile_id,
                profile_kind=profile_kind,
                expected_version=expected_version,
                actor_user_id=actor_user_id,
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        logger.info(
            "Deleted infrastructure Profile",
            extra={
                "provider_id": provider_logical_id,
                "infrastructure_profile_id": profile_id,
                "infrastructure_profile_kind": profile_kind.value,
                "infrastructure_profile_version": expected_version,
                "actor_user_id": actor_user_id,
                "superseded_recreation_operation_count": (
                    deletion.superseded_recreation_operation_count
                ),
                "skipped_recreation_item_count": deletion.skipped_recreation_item_count,
            },
        )
        return deletion

    async def get_workspace_profile_admin_detail(
        self, workspace_handle: str, profile_id: str
    ) -> AdminWorkspaceRuntimeProfileDetailProjection:
        """Return detached System-Admin Workspace Profile detail."""
        try:
            snapshot = await self.repository.get_workspace_profile_admin_detail(
                workspace_handle, profile_id
            )
        except ProfileAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return AdminWorkspaceRuntimeProfileDetailProjection(
            workspace_id=snapshot.workspace_id,
            workspace=snapshot.workspace,
            profile=snapshot.profile,
            infrastructure_profile=snapshot.infrastructure_profile,
            provider=snapshot.provider,
            usage=snapshot.usage,
        )
