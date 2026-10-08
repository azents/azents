"""Runtime management sequencing through completed repository operations."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.core.runtime_profile import (
    RuntimeProfileLifecycle,
    WorkspaceRuntimeProfilePolicy,
)
from azents.core.runtime_profile_deletion import WorkspaceRuntimeProfileDeletion
from azents.core.runtime_profile_workspace import (
    SelectableInfrastructureProfileProjection,
    WorkspaceRuntimeProfileDefaultProjection,
    WorkspaceRuntimeProfileProjection,
)
from azents.repos.runtime_profile_workspace_operations import (
    RuntimeProfileWorkspaceOperationsRepository,
)
from azents.services.terminal_policy.invalidation import (
    TerminalPolicyInvalidationPublisherDependency,
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class RuntimeProfileWorkspaceService:
    """Sequence completed management operations and postcommit effects."""

    operations: Annotated[
        RuntimeProfileWorkspaceOperationsRepository,
        Depends(RuntimeProfileWorkspaceOperationsRepository),
    ]
    terminal_policy_invalidation_publisher: (
        TerminalPolicyInvalidationPublisherDependency
    )

    async def get_default(
        self,
        workspace_id: str,
    ) -> WorkspaceRuntimeProfileDefaultProjection:
        """Return the Workspace default and current Profile availability."""
        return await self.operations.get_default(workspace_id=workspace_id)

    async def replace_default(
        self,
        workspace_id: str,
        *,
        expected_version: int,
        runtime_profile_id: str | None,
    ) -> WorkspaceRuntimeProfileDefaultProjection:
        """Set or clear the Workspace default with optimistic fencing."""
        return await self.operations.replace_default(
            workspace_id=workspace_id,
            expected_version=expected_version,
            runtime_profile_id=runtime_profile_id,
        )

    async def list_profiles(
        self,
        workspace_id: str,
        *,
        include_disabled: bool,
    ) -> list[WorkspaceRuntimeProfileProjection]:
        """List Workspace Profiles with current availability evidence."""
        return await self.operations.list_profiles(
            workspace_id=workspace_id, include_disabled=include_disabled
        )

    async def get_profile(
        self,
        workspace_id: str,
        profile_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Get one Workspace-owned Runtime Profile."""
        return await self.operations.get_profile(
            workspace_id=workspace_id, profile_id=profile_id
        )

    async def create_profile(
        self,
        workspace_id: str,
        *,
        infrastructure_profile_id: str,
        display_name: str,
        description: str,
        lifecycle: RuntimeProfileLifecycle,
        policy: WorkspaceRuntimeProfilePolicy,
        terminal_enabled: bool,
        actor_workspace_user_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Create one complete Workspace Runtime choice."""
        return await self.operations.create_profile(
            workspace_id=workspace_id,
            infrastructure_profile_id=infrastructure_profile_id,
            display_name=display_name,
            description=description,
            lifecycle=lifecycle,
            policy=policy,
            terminal_enabled=terminal_enabled,
            actor_workspace_user_id=actor_workspace_user_id,
        )

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
        terminal_enabled: bool,
        actor_workspace_user_id: str,
    ) -> WorkspaceRuntimeProfileProjection:
        """Replace one Workspace Profile with optimistic version fencing."""
        result = await self.operations.replace_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            expected_version=expected_version,
            infrastructure_profile_id=infrastructure_profile_id,
            display_name=display_name,
            description=description,
            lifecycle=lifecycle,
            policy=policy,
            terminal_enabled=terminal_enabled,
            actor_workspace_user_id=actor_workspace_user_id,
        )
        projection = result.projection
        profile = projection.profile
        terminal_changed = result.terminal_changed
        if terminal_changed:
            publisher = self.terminal_policy_invalidation_publisher
            await publisher.publish_terminal_policy_invalidation(
                TerminalPolicySourceInvalidation(
                    scope=TerminalPolicySourceScope.WORKSPACE_PROFILE,
                    source_id=profile.id,
                    source_version=str(profile.version),
                )
            )
        return projection

    async def delete_profile(
        self,
        workspace_id: str,
        profile_id: str,
        *,
        expected_version: int,
        actor_workspace_user_id: str,
    ) -> WorkspaceRuntimeProfileDeletion:
        """Permanently delete one exact Workspace Profile and live selection."""
        deletion = await self.operations.delete_profile(
            workspace_id=workspace_id,
            profile_id=profile_id,
            expected_version=expected_version,
            actor_workspace_user_id=actor_workspace_user_id,
        )
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
        return await self.operations.list_selectable_infrastructure(
            workspace_id=workspace_id
        )
