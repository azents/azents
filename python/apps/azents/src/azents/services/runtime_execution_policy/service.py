"""Runtime execution policy management and resolution service."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_execution_policy import (
    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
    SYSTEM_STANDARD_PROFILE_ID,
    JsonValue,
    RuntimeExecutionAuditEventType,
    RuntimeExecutionAvailabilityReason,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionModuleId,
    RuntimeExecutionModuleSupport,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyLayer,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionProviderCapabilities,
    RuntimeExecutionResolution,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    canonical_runtime_execution_policy,
    classify_runtime_execution_change,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    resolve_runtime_execution_policy,
    validate_runtime_execution_restriction,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.runtime_execution_policy.data import (
    AgentRuntimeExecutionSetting,
    RuntimeExecutionPlatformPolicy,
    RuntimeExecutionPolicyAuditEvent,
    RuntimeExecutionPolicyAuditEventCreate,
    RuntimeExecutionProfile,
    RuntimeExecutionProfileCreate,
    WorkspaceRuntimeExecutionPolicy,
)
from azents.repos.runtime_execution_policy.repository import (
    RuntimeExecutionPolicyRepository,
)


@dataclasses.dataclass
class RuntimeExecutionPolicyVersionConflict(Exception):
    """A mutable execution-policy resource changed before this write."""

    target_id: str
    expected_version: int
    current_version: int

    def __post_init__(self) -> None:
        Exception.__init__(
            self,
            f"Execution-policy version conflict for {self.target_id}.",
        )


@dataclasses.dataclass
class RuntimeExecutionPolicyUnavailable(Exception):
    """A requested execution-policy management operation is unavailable."""

    code: str
    target_id: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code)


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionPlatformMutation:
    """Replace the current Platform execution-policy ceiling."""

    expected_version: int
    policy: RuntimeExecutionPolicyDocument
    actor_user_id: str
    correlation_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionProfileMutation:
    """Replace one stable Profile's metadata and authority content."""

    expected_version: int
    display_name: str
    description: str
    policy: RuntimeExecutionPolicyDocument
    actor_user_id: str
    correlation_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeExecutionPolicyMutation:
    """Atomically replace one Workspace policy and allowance set."""

    expected_version: int
    restriction: RuntimeExecutionPolicyRestriction
    allowed_profile_ids: frozenset[str]
    actor_workspace_user_id: str
    correlation_id: str


@dataclasses.dataclass(frozen=True)
class AgentRuntimeExecutionSettingMutation:
    """Replace one Agent Profile selection and restrictive override."""

    expected_version: int
    profile_id: str
    restriction: RuntimeExecutionPolicyRestriction
    actor_workspace_user_id: str
    correlation_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceRuntimeExecutionPolicyView:
    """Safe current Workspace policy, including the implicit initial state."""

    workspace_id: str
    version: int
    restriction: RuntimeExecutionPolicyRestriction
    digest: str
    allowed_profile_ids: frozenset[str]
    updated_at: datetime.datetime | None


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionProfileAvailability:
    """One Profile's Workspace-level availability projection."""

    profile: RuntimeExecutionProfile
    allowed: bool
    available: bool
    reason: RuntimeExecutionAvailabilityReason | None


@dataclasses.dataclass(frozen=True)
class RuntimeExecutionManagementCapabilities:
    """Safe server-owned capability availability for policy management UI."""

    image_build: bool
    container_run: bool
    compose: bool
    storage_modes: tuple[RuntimeExecutionStorageMode, ...]
    network_modes: tuple[RuntimeExecutionNetworkMode, ...]


@dataclasses.dataclass(frozen=True)
class AgentRuntimeExecutionPolicyView:
    """Configured Agent execution intent with current capability evaluation."""

    setting: AgentRuntimeExecutionSetting
    profile: RuntimeExecutionProfile
    resolution: RuntimeExecutionResolution
    provider_compatibility_evaluated: bool
    capabilities: RuntimeExecutionManagementCapabilities


@dataclasses.dataclass
class RuntimeExecutionPolicyService:
    """Manage current policy rows and resolve effective Agent policy."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        RuntimeExecutionPolicyRepository,
        Depends(RuntimeExecutionPolicyRepository),
    ]
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]

    def get_management_capabilities(self) -> RuntimeExecutionManagementCapabilities:
        """Return the current server-owned policy management capability gate."""
        return _management_capabilities()

    async def get_platform(self) -> RuntimeExecutionPlatformPolicy:
        """Return the current Platform execution-policy ceiling."""
        async with self.session_manager() as session:
            platform = await self.repository.get_platform(session, for_update=False)
        if platform is None:
            raise RuntimeExecutionPolicyUnavailable(
                "platform_policy_missing",
                RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
            )
        return platform

    async def list_profiles(
        self,
        *,
        include_retired: bool,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionProfile]:
        """List Profiles for System Admin management."""
        async with self.session_manager() as session:
            return await self.repository.list_profiles(
                session,
                include_retired=include_retired,
                profile_ids=None,
                offset=offset,
                limit=limit,
            )

    async def get_profile(self, profile_id: str) -> RuntimeExecutionProfile:
        """Return one stable Profile."""
        async with self.session_manager() as session:
            profile = await self.repository.get_profile(
                session,
                profile_id=profile_id,
                for_update=False,
            )
        if profile is None:
            raise RuntimeExecutionPolicyUnavailable(
                "profile_not_found",
                profile_id,
            )
        return profile

    async def list_admin_audit_events(
        self,
        *,
        management_layer: RuntimeExecutionManagementLayer | None,
        target_id: str | None,
        workspace_id: str | None,
        agent_id: str | None,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionPolicyAuditEvent]:
        """List metadata-only audit events for System Admins."""
        async with self.session_manager() as session:
            return await self.repository.list_audit_events(
                session,
                management_layer=management_layer,
                target_id=target_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                offset=offset,
                limit=limit,
            )

    async def get_workspace_policy(
        self,
        workspace_id: str,
    ) -> WorkspaceRuntimeExecutionPolicyView:
        """Return the explicit or implicit safe Workspace policy."""
        async with self.session_manager() as session:
            workspace = await self.repository.get_workspace(
                session,
                workspace_id=workspace_id,
                for_update=False,
            )
        return _workspace_view(workspace_id, workspace)

    async def replace_workspace_for_manager(
        self,
        workspace_id: str,
        mutation: WorkspaceRuntimeExecutionPolicyMutation,
        *,
        role: WorkspaceUserRole,
    ) -> WorkspaceRuntimeExecutionPolicyView:
        """Authorize and replace one Workspace execution policy."""
        if role not in {WorkspaceUserRole.OWNER, WorkspaceUserRole.MANAGER}:
            raise RuntimeExecutionPolicyUnavailable(
                "workspace_policy_access_denied",
                workspace_id,
            )
        await self.replace_workspace(workspace_id, mutation)
        return await self.get_workspace_policy(workspace_id)

    async def list_workspace_profiles(
        self,
        workspace_id: str,
        *,
        include_retired: bool,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionProfileAvailability]:
        """List Platform Profiles with Workspace allowance diagnostics."""
        async with self.session_manager() as session:
            workspace = await self.repository.get_workspace(
                session,
                workspace_id=workspace_id,
                for_update=False,
            )
            profiles = await self.repository.list_profiles(
                session,
                include_retired=include_retired,
                profile_ids=None,
                offset=offset,
                limit=limit,
            )
        allowed_profile_ids = _workspace_view(
            workspace_id,
            workspace,
        ).allowed_profile_ids
        return [
            _profile_availability(
                profile,
                allowed_profile_ids,
                capability_reason=_policy_capability_reason(profile.policy),
            )
            for profile in profiles
        ]

    async def list_workspace_audit_events(
        self,
        workspace_id: str,
        *,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionPolicyAuditEvent]:
        """List metadata-only audit events scoped to one Workspace."""
        async with self.session_manager() as session:
            return await self.repository.list_audit_events(
                session,
                management_layer=RuntimeExecutionManagementLayer.WORKSPACE,
                target_id=None,
                workspace_id=workspace_id,
                agent_id=None,
                offset=offset,
                limit=limit,
            )

    async def get_agent_policy_for_manager(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> AgentRuntimeExecutionPolicyView:
        """Return Agent intent only to its administrators or Workspace owner."""
        async with self.session_manager() as session:
            await self._require_agent_manager(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
            )
            platform = await self.repository.get_platform(session, for_update=False)
            setting = await self.repository.get_agent_setting(
                session,
                agent_id=agent_id,
                for_update=False,
            )
            workspace = await self.repository.get_workspace(
                session,
                workspace_id=workspace_id,
                for_update=False,
            )
            if platform is None or setting is None:
                target_id = (
                    RUNTIME_EXECUTION_PLATFORM_POLICY_ID
                    if platform is None
                    else agent_id
                )
                raise RuntimeExecutionPolicyUnavailable(
                    "execution_policy_state_missing",
                    target_id,
                )
            profile = await self.repository.get_profile(
                session,
                profile_id=setting.profile_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_not_found",
                    setting.profile_id,
                )
        workspace_view = _workspace_view(workspace_id, workspace)
        resolution = resolve_runtime_execution_policy(
            platform_policy=platform.policy,
            profile_policy=profile.policy,
            workspace_restriction=workspace_view.restriction,
            agent_restriction=setting.restriction,
            source_versions=RuntimeExecutionSourceVersions(
                platform=platform.version,
                profile=profile.version,
                workspace=max(workspace_view.version, 1),
                agent=setting.version,
            ),
            provider_capabilities=_validation_provider_capabilities(),
            profile_active=(
                profile.lifecycle is RuntimeExecutionProfileLifecycle.ACTIVE
            ),
            profile_allowed=profile.id in workspace_view.allowed_profile_ids,
            applied_policy=None,
        )
        return AgentRuntimeExecutionPolicyView(
            setting=setting,
            profile=profile,
            resolution=resolution,
            provider_compatibility_evaluated=True,
            capabilities=_management_capabilities(),
        )

    async def replace_agent_setting_for_manager(
        self,
        agent_id: str,
        mutation: AgentRuntimeExecutionSettingMutation,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> AgentRuntimeExecutionPolicyView:
        """Authorize and replace Agent intent without Runtime application."""
        async with self.session_manager() as session:
            await self._require_agent_manager(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
            )
        await self.replace_agent_setting(agent_id, mutation)
        return await self.get_agent_policy_for_manager(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def list_agent_audit_events_for_manager(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionPolicyAuditEvent]:
        """List Agent policy audit only for authorized Agent managers."""
        async with self.session_manager() as session:
            await self._require_agent_manager(
                session,
                agent_id=agent_id,
                workspace_id=workspace_id,
                workspace_user_id=workspace_user_id,
                role=role,
            )
            return await self.repository.list_audit_events(
                session,
                management_layer=None,
                target_id=None,
                workspace_id=workspace_id,
                agent_id=agent_id,
                offset=offset,
                limit=limit,
            )

    async def _require_agent_manager(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> None:
        """Enforce the existing Agent administrator-or-owner boundary."""
        owner_workspace_id = await self.repository.get_agent_workspace_id(
            session,
            agent_id=agent_id,
        )
        if owner_workspace_id != workspace_id:
            raise RuntimeExecutionPolicyUnavailable(
                "agent_not_found",
                agent_id,
            )
        if role is WorkspaceUserRole.OWNER:
            return
        if not await self.agent_admin_repository.is_admin(
            session,
            agent_id,
            workspace_user_id,
        ):
            raise RuntimeExecutionPolicyUnavailable(
                "agent_access_denied",
                agent_id,
            )

    async def replace_platform(
        self,
        mutation: RuntimeExecutionPlatformMutation,
    ) -> RuntimeExecutionPlatformPolicy:
        """Replace Platform policy with atomic expected-version audit."""
        _require_policy_capability_available(
            mutation.policy,
            target_id=RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
        )
        async with self.session_manager() as session:
            current = await self.repository.get_platform(session, for_update=True)
            if current is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "platform_policy_missing",
                    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
                )
            self._require_version(
                target_id=current.id,
                expected=mutation.expected_version,
                current=current.version,
            )
            digest = digest_runtime_execution_policy(mutation.policy)
            changed = classify_runtime_execution_change(
                current.policy,
                mutation.policy,
            )
            updated = await self.repository.replace_platform(
                session,
                expected_version=mutation.expected_version,
                policy=mutation.policy,
                digest=digest,
                updated_by_user_id=mutation.actor_user_id,
            )
            if updated is None:
                raise RuntimeExecutionPolicyVersionConflict(
                    current.id,
                    mutation.expected_version,
                    current.version,
                )
            await self._append_audit(
                session,
                event_type=RuntimeExecutionAuditEventType.PLATFORM_POLICY_REPLACED,
                layer=RuntimeExecutionManagementLayer.PLATFORM,
                target_id=current.id,
                correlation_id=mutation.correlation_id,
                classification=changed.direction,
                changed_paths=tuple(field.path for field in changed.fields),
                before_digest=current.digest,
                after_digest=updated.digest,
                actor_user_id=mutation.actor_user_id,
                actor_workspace_user_id=None,
                workspace_id=None,
                agent_id=None,
                reason_code="operator_replace",
            )
            return updated

    async def create_profile(
        self,
        *,
        profile_id: str,
        display_name: str,
        description: str,
        policy: RuntimeExecutionPolicyDocument,
        actor_user_id: str,
        correlation_id: str,
    ) -> RuntimeExecutionProfile:
        """Create one ordinary active Profile and its audit event."""
        if profile_id == SYSTEM_STANDARD_PROFILE_ID:
            raise RuntimeExecutionPolicyUnavailable(
                "reserved_profile_identity",
                profile_id,
            )
        _require_policy_capability_available(policy, target_id=profile_id)
        async with self.session_manager() as session:
            created = await self.repository.create_profile(
                session,
                create=RuntimeExecutionProfileCreate(
                    id=profile_id,
                    display_name=display_name,
                    description=description,
                    policy=policy,
                    digest=digest_runtime_execution_policy(policy),
                    updated_by_user_id=actor_user_id,
                ),
            )
            direction = classify_runtime_execution_change(None, policy)
            await self._append_audit(
                session,
                event_type=RuntimeExecutionAuditEventType.PROFILE_CREATED,
                layer=RuntimeExecutionManagementLayer.PROFILE,
                target_id=profile_id,
                correlation_id=correlation_id,
                classification=direction.direction,
                changed_paths=tuple(field.path for field in direction.fields),
                before_digest=None,
                after_digest=created.digest,
                actor_user_id=actor_user_id,
                actor_workspace_user_id=None,
                workspace_id=None,
                agent_id=None,
                reason_code="operator_create",
            )
            return created

    async def replace_profile(
        self,
        profile_id: str,
        mutation: RuntimeExecutionProfileMutation,
    ) -> RuntimeExecutionProfile:
        """Replace one Profile without broadening the reserved Standard."""
        async with self.session_manager() as session:
            current = await self.repository.get_profile(
                session,
                profile_id=profile_id,
                for_update=True,
            )
            if current is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_not_found",
                    profile_id,
                )
            self._require_version(
                target_id=profile_id,
                expected=mutation.expected_version,
                current=current.version,
            )
            digest = digest_runtime_execution_policy(mutation.policy)
            if current.reserved and digest != current.digest:
                raise RuntimeExecutionPolicyUnavailable(
                    "reserved_profile_policy_immutable",
                    profile_id,
                )
            _require_policy_capability_available(
                mutation.policy,
                target_id=profile_id,
            )
            changed = classify_runtime_execution_change(
                current.policy,
                mutation.policy,
            )
            updated = await self.repository.replace_profile(
                session,
                profile_id=profile_id,
                expected_version=mutation.expected_version,
                display_name=mutation.display_name,
                description=mutation.description,
                policy=mutation.policy,
                digest=digest,
                updated_by_user_id=mutation.actor_user_id,
            )
            if updated is None:
                raise RuntimeExecutionPolicyVersionConflict(
                    profile_id,
                    mutation.expected_version,
                    current.version,
                )
            await self._append_audit(
                session,
                event_type=RuntimeExecutionAuditEventType.PROFILE_REPLACED,
                layer=RuntimeExecutionManagementLayer.PROFILE,
                target_id=profile_id,
                correlation_id=mutation.correlation_id,
                classification=changed.direction,
                changed_paths=tuple(field.path for field in changed.fields),
                before_digest=current.digest,
                after_digest=updated.digest,
                actor_user_id=mutation.actor_user_id,
                actor_workspace_user_id=None,
                workspace_id=None,
                agent_id=None,
                reason_code="operator_replace",
            )
            return updated

    async def retire_profile(
        self,
        profile_id: str,
        *,
        expected_version: int,
        actor_user_id: str,
        correlation_id: str,
    ) -> RuntimeExecutionProfile:
        """Retire an ordinary Profile without affecting reserved Standard."""
        async with self.session_manager() as session:
            current = await self.repository.get_profile(
                session,
                profile_id=profile_id,
                for_update=True,
            )
            if current is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_not_found",
                    profile_id,
                )
            self._require_version(
                target_id=profile_id,
                expected=expected_version,
                current=current.version,
            )
            if current.reserved:
                raise RuntimeExecutionPolicyUnavailable(
                    "reserved_profile_cannot_retire",
                    profile_id,
                )
            updated = await self.repository.retire_profile(
                session,
                profile_id=profile_id,
                expected_version=expected_version,
                updated_by_user_id=actor_user_id,
            )
            if updated is None:
                raise RuntimeExecutionPolicyVersionConflict(
                    profile_id,
                    expected_version,
                    current.version,
                )
            await self._append_audit(
                session,
                event_type=RuntimeExecutionAuditEventType.PROFILE_RETIRED,
                layer=RuntimeExecutionManagementLayer.PROFILE,
                target_id=profile_id,
                correlation_id=correlation_id,
                classification=RuntimeExecutionChangeDirection.RESTRICTIVE,
                changed_paths=("lifecycle",),
                before_digest=current.digest,
                after_digest=updated.digest,
                actor_user_id=actor_user_id,
                actor_workspace_user_id=None,
                workspace_id=None,
                agent_id=None,
                reason_code="operator_retire",
            )
            return updated

    async def replace_workspace(
        self,
        workspace_id: str,
        mutation: WorkspaceRuntimeExecutionPolicyMutation,
    ) -> WorkspaceRuntimeExecutionPolicy:
        """Replace Workspace restrictions and allowances in one transaction."""
        async with self.session_manager() as session:
            current = await self.repository.get_workspace(
                session,
                workspace_id=workspace_id,
                for_update=True,
            )
            current_version = current.version if current is not None else 0
            self._require_version(
                target_id=workspace_id,
                expected=mutation.expected_version,
                current=current_version,
            )
            platform = await self.repository.get_platform(
                session,
                for_update=False,
            )
            if platform is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "platform_policy_missing",
                    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
                )
            validate_runtime_execution_restriction(
                platform.policy,
                mutation.restriction,
                governing_layer=RuntimeExecutionPolicyLayer.PLATFORM,
            )
            profiles = await self.repository.list_profiles(
                session,
                include_retired=True,
                profile_ids=mutation.allowed_profile_ids,
                offset=0,
                limit=len(mutation.allowed_profile_ids),
            )
            if {profile.id for profile in profiles} != set(
                mutation.allowed_profile_ids
            ):
                raise RuntimeExecutionPolicyUnavailable(
                    "allowed_profile_not_found",
                    workspace_id,
                )
            if any(
                not _profile_availability(
                    profile,
                    mutation.allowed_profile_ids,
                    capability_reason=_policy_capability_reason(profile.policy),
                ).available
                for profile in profiles
            ):
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_unavailable",
                    workspace_id,
                )
            digest = digest_runtime_execution_policy(mutation.restriction)
            before = (
                current.restriction
                if current is not None
                else empty_runtime_execution_restriction()
            )
            restriction_change = _classify_restriction_change(
                before,
                mutation.restriction,
            )
            allowance_change = _classify_profile_allowance_change(
                (
                    current.allowed_profile_ids
                    if current is not None
                    else frozenset({SYSTEM_STANDARD_PROFILE_ID})
                ),
                mutation.allowed_profile_ids,
            )
            classification = _combine_change_directions(
                restriction_change.direction,
                allowance_change,
            )
            paths = restriction_change.paths
            if allowance_change is not RuntimeExecutionChangeDirection.METADATA_ONLY:
                paths = (*paths, "allowed_profile_ids")
            updated = await self.repository.replace_workspace(
                session,
                workspace_id=workspace_id,
                expected_version=mutation.expected_version,
                restriction=mutation.restriction,
                digest=digest,
                allowed_profile_ids=mutation.allowed_profile_ids,
                updated_by_workspace_user_id=mutation.actor_workspace_user_id,
            )
            if updated is None:
                raise RuntimeExecutionPolicyVersionConflict(
                    workspace_id,
                    mutation.expected_version,
                    current_version,
                )
            await self._append_audit(
                session,
                event_type=(RuntimeExecutionAuditEventType.WORKSPACE_POLICY_REPLACED),
                layer=RuntimeExecutionManagementLayer.WORKSPACE,
                target_id=workspace_id,
                correlation_id=mutation.correlation_id,
                classification=classification,
                changed_paths=paths,
                before_digest=current.digest if current is not None else None,
                after_digest=updated.digest,
                actor_user_id=None,
                actor_workspace_user_id=mutation.actor_workspace_user_id,
                workspace_id=workspace_id,
                agent_id=None,
                reason_code="operator_replace",
            )
            return updated

    async def replace_agent_setting(
        self,
        agent_id: str,
        mutation: AgentRuntimeExecutionSettingMutation,
    ) -> AgentRuntimeExecutionSetting:
        """Replace Agent intent without creating or dispatching a target."""
        async with self.session_manager() as session:
            current = await self.repository.get_agent_setting(
                session,
                agent_id=agent_id,
                for_update=True,
            )
            if current is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "agent_execution_setting_missing",
                    agent_id,
                )
            workspace_id = await self.repository.get_agent_workspace_id(
                session,
                agent_id=agent_id,
            )
            if workspace_id is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "agent_not_found",
                    agent_id,
                )
            self._require_version(
                target_id=agent_id,
                expected=mutation.expected_version,
                current=current.version,
            )
            profile = await self.repository.get_profile(
                session,
                profile_id=mutation.profile_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_not_found",
                    mutation.profile_id,
                )
            platform = await self.repository.get_platform(
                session,
                for_update=False,
            )
            if platform is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "platform_policy_missing",
                    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
                )
            workspace = await self.repository.get_workspace(
                session,
                workspace_id=workspace_id,
                for_update=False,
            )
            workspace_restriction = (
                workspace.restriction
                if workspace is not None
                else empty_runtime_execution_restriction()
            )
            allowed_profile_ids = (
                workspace.allowed_profile_ids
                if workspace is not None
                else frozenset({SYSTEM_STANDARD_PROFILE_ID})
            )
            selecting_new_profile = current.profile_id != mutation.profile_id
            if selecting_new_profile and (
                profile.lifecycle is not RuntimeExecutionProfileLifecycle.ACTIVE
                or profile.id not in allowed_profile_ids
                or _policy_capability_reason(profile.policy) is not None
            ):
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_unavailable",
                    mutation.profile_id,
                )
            parent_policy = resolve_runtime_execution_policy(
                platform_policy=platform.policy,
                profile_policy=profile.policy,
                workspace_restriction=workspace_restriction,
                agent_restriction=empty_runtime_execution_restriction(),
                source_versions=RuntimeExecutionSourceVersions(
                    platform=platform.version,
                    profile=profile.version,
                    workspace=workspace.version if workspace is not None else 1,
                    agent=current.version,
                ),
                provider_capabilities=_validation_provider_capabilities(),
                profile_active=True,
                profile_allowed=True,
                applied_policy=None,
            ).effective_policy
            validate_runtime_execution_restriction(
                parent_policy,
                mutation.restriction,
                governing_layer=RuntimeExecutionPolicyLayer.AGENT,
            )
            change = _classify_restriction_change(
                current.restriction,
                mutation.restriction,
            )
            classification = change.direction
            paths = change.paths
            if current.profile_id != mutation.profile_id:
                classification = RuntimeExecutionChangeDirection.MIXED
                paths = (*paths, "profile_id")
            updated = await self.repository.replace_agent_setting(
                session,
                agent_id=agent_id,
                expected_version=mutation.expected_version,
                profile_id=mutation.profile_id,
                restriction=mutation.restriction,
                digest=digest_runtime_execution_policy(mutation.restriction),
                updated_by_workspace_user_id=mutation.actor_workspace_user_id,
            )
            if updated is None:
                raise RuntimeExecutionPolicyVersionConflict(
                    agent_id,
                    mutation.expected_version,
                    current.version,
                )
            await self._append_audit(
                session,
                event_type=RuntimeExecutionAuditEventType.AGENT_SETTINGS_REPLACED,
                layer=RuntimeExecutionManagementLayer.AGENT,
                target_id=agent_id,
                correlation_id=mutation.correlation_id,
                classification=classification,
                changed_paths=paths,
                before_digest=current.digest,
                after_digest=updated.digest,
                actor_user_id=None,
                actor_workspace_user_id=mutation.actor_workspace_user_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                reason_code="operator_replace",
            )
            return updated

    async def resolve_agent(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        provider_capabilities: RuntimeExecutionProviderCapabilities,
        applied_policy: RuntimeExecutionPolicyDocument | None,
    ) -> RuntimeExecutionResolution:
        """Resolve current Agent intent against typed Provider compatibility."""
        async with self.session_manager() as session:
            platform = await self.repository.get_platform(session, for_update=False)
            setting = await self.repository.get_agent_setting(
                session,
                agent_id=agent_id,
                for_update=False,
            )
            workspace = await self.repository.get_workspace(
                session,
                workspace_id=workspace_id,
                for_update=False,
            )
            if platform is None or setting is None:
                target = (
                    RUNTIME_EXECUTION_PLATFORM_POLICY_ID
                    if platform is None
                    else agent_id
                )
                raise RuntimeExecutionPolicyUnavailable(
                    "execution_policy_state_missing",
                    target,
                )
            profile = await self.repository.get_profile(
                session,
                profile_id=setting.profile_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeExecutionPolicyUnavailable(
                    "profile_not_found",
                    setting.profile_id,
                )
        workspace_restriction = (
            workspace.restriction
            if workspace is not None
            else empty_runtime_execution_restriction()
        )
        allowed_profile_ids = (
            workspace.allowed_profile_ids
            if workspace is not None
            else frozenset({SYSTEM_STANDARD_PROFILE_ID})
        )
        return resolve_runtime_execution_policy(
            platform_policy=platform.policy,
            profile_policy=profile.policy,
            workspace_restriction=workspace_restriction,
            agent_restriction=setting.restriction,
            source_versions=RuntimeExecutionSourceVersions(
                platform=platform.version,
                profile=profile.version,
                workspace=workspace.version if workspace is not None else 1,
                agent=setting.version,
            ),
            provider_capabilities=provider_capabilities,
            profile_active=(
                profile.lifecycle is RuntimeExecutionProfileLifecycle.ACTIVE
            ),
            profile_allowed=profile.id in allowed_profile_ids,
            applied_policy=applied_policy,
        )

    async def _append_audit(
        self,
        session: AsyncSession,
        *,
        event_type: RuntimeExecutionAuditEventType,
        layer: RuntimeExecutionManagementLayer,
        target_id: str,
        correlation_id: str,
        classification: RuntimeExecutionChangeDirection,
        changed_paths: tuple[str, ...],
        before_digest: str | None,
        after_digest: str | None,
        actor_user_id: str | None,
        actor_workspace_user_id: str | None,
        workspace_id: str | None,
        agent_id: str | None,
        reason_code: str,
    ) -> None:
        await self.repository.append_audit_event(
            session,
            create=RuntimeExecutionPolicyAuditEventCreate(
                event_type=event_type,
                management_layer=layer,
                target_id=target_id,
                correlation_id=correlation_id,
                classification=classification,
                changed_paths=tuple(sorted(set(changed_paths))),
                impact_counts={},
                reason_code=reason_code,
                outcome_code="applied",
                metadata={},
                workspace_id=workspace_id,
                agent_id=agent_id,
                runtime_id=None,
                actor_user_id=actor_user_id,
                actor_workspace_user_id=actor_workspace_user_id,
                system_authority=False,
                before_digest=before_digest,
                after_digest=after_digest,
            ),
        )

    @staticmethod
    def _require_version(
        *,
        target_id: str,
        expected: int,
        current: int,
    ) -> None:
        if expected != current:
            raise RuntimeExecutionPolicyVersionConflict(
                target_id,
                expected,
                current,
            )


@dataclasses.dataclass(frozen=True)
class _RestrictionChangeClassification:
    """Security direction and semantic paths for one restriction change."""

    direction: RuntimeExecutionChangeDirection
    paths: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class _RestrictionFieldValues:
    """Aligned values for one semantic restriction leaf."""

    path: str
    before: JsonValue
    after: JsonValue


def _classify_restriction_change(
    previous: RuntimeExecutionPolicyRestriction,
    current: RuntimeExecutionPolicyRestriction,
) -> _RestrictionChangeClassification:
    """Classify restrictive-document fields without inventing a parent policy."""
    fields = _align_restriction_fields(
        canonical_runtime_execution_policy(previous),
        canonical_runtime_execution_policy(current),
    )
    changed = tuple(field for field in fields if field.before != field.after)
    paths = tuple(field.path for field in changed)
    directions = {
        _restriction_field_direction(field.path, field.before, field.after)
        for field in changed
    }
    if not paths:
        return _RestrictionChangeClassification(
            RuntimeExecutionChangeDirection.METADATA_ONLY,
            (),
        )
    if directions == {RuntimeExecutionChangeDirection.RESTRICTIVE}:
        return _RestrictionChangeClassification(
            RuntimeExecutionChangeDirection.RESTRICTIVE,
            paths,
        )
    if directions == {RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING}:
        return _RestrictionChangeClassification(
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
            paths,
        )
    return _RestrictionChangeClassification(
        RuntimeExecutionChangeDirection.MIXED,
        paths,
    )


def _align_restriction_fields(
    before: JsonValue,
    after: JsonValue,
    prefix: str = "",
) -> tuple[_RestrictionFieldValues, ...]:
    """Align optional nested objects to their semantic leaf paths."""
    if isinstance(before, dict) or isinstance(after, dict):
        before_mapping = before if isinstance(before, dict) else {}
        after_mapping = after if isinstance(after, dict) else {}
        fields: list[_RestrictionFieldValues] = []
        for key in sorted(before_mapping.keys() | after_mapping.keys()):
            path = f"{prefix}.{key}" if prefix else key
            fields.extend(
                _align_restriction_fields(
                    before_mapping.get(key),
                    after_mapping.get(key),
                    path,
                )
            )
        return tuple(fields)
    if not prefix:
        raise AssertionError("Restriction field path cannot be empty.")
    return (_RestrictionFieldValues(prefix, before, after),)


def _classify_profile_allowance_change(
    previous: frozenset[str],
    current: frozenset[str],
) -> RuntimeExecutionChangeDirection:
    """Classify additions and removals in a Workspace Profile allowance set."""
    added = current - previous
    removed = previous - current
    if added and removed:
        return RuntimeExecutionChangeDirection.MIXED
    if added:
        return RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
    if removed:
        return RuntimeExecutionChangeDirection.RESTRICTIVE
    return RuntimeExecutionChangeDirection.METADATA_ONLY


def _combine_change_directions(
    *directions: RuntimeExecutionChangeDirection,
) -> RuntimeExecutionChangeDirection:
    """Combine independently classified policy contributions."""
    material = {
        direction
        for direction in directions
        if direction is not RuntimeExecutionChangeDirection.METADATA_ONLY
    }
    if not material:
        return RuntimeExecutionChangeDirection.METADATA_ONLY
    if len(material) == 1:
        return next(iter(material))
    return RuntimeExecutionChangeDirection.MIXED


def _restriction_field_direction(
    path: str,
    before: JsonValue,
    after: JsonValue,
) -> RuntimeExecutionChangeDirection:
    if before is None:
        return RuntimeExecutionChangeDirection.RESTRICTIVE
    if after is None:
        return RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return (
            RuntimeExecutionChangeDirection.RESTRICTIVE
            if after < before
            else RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
        )
    if path.endswith("denied_destinations"):
        return (
            RuntimeExecutionChangeDirection.RESTRICTIVE
            if _string_set(after) >= _string_set(before)
            else RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
        )
    if path.endswith("allowed_destinations"):
        return (
            RuntimeExecutionChangeDirection.RESTRICTIVE
            if _string_set(after) <= _string_set(before)
            else RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
        )
    return RuntimeExecutionChangeDirection.MIXED


def _string_set(value: JsonValue) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Execution-policy destination set is invalid.")
    return {item for item in value if isinstance(item, str)}


def _validation_provider_capabilities() -> RuntimeExecutionProviderCapabilities:
    """Return the installation capability ceiling backed by qualified Providers."""
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(
            RuntimeExecutionModuleSupport(module_id=module_id, version=1)
            for module_id in RuntimeExecutionModuleId
        ),
        privileged_engine=True,
        storage_modes=frozenset(
            {
                RuntimeExecutionStorageMode.NONE,
                RuntimeExecutionStorageMode.EPHEMERAL,
            }
        ),
        network_modes=frozenset(
            {
                RuntimeExecutionNetworkMode.NONE,
                RuntimeExecutionNetworkMode.DIRECT,
            }
        ),
        resource_maxima=None,
    )


def _management_capabilities() -> RuntimeExecutionManagementCapabilities:
    """Project current compatibility into a stable UI capability gate."""
    capabilities = _validation_provider_capabilities()
    privileged_engine = capabilities.privileged_engine
    return RuntimeExecutionManagementCapabilities(
        image_build=privileged_engine,
        container_run=privileged_engine,
        compose=privileged_engine,
        storage_modes=tuple(sorted(capabilities.storage_modes)),
        network_modes=tuple(sorted(capabilities.network_modes)),
    )


def _policy_capability_reason(
    policy: RuntimeExecutionPolicyDocument,
) -> RuntimeExecutionAvailabilityReason | None:
    """Return a bounded incompatibility reason for one raw authority policy."""
    resolution = resolve_runtime_execution_policy(
        platform_policy=policy,
        profile_policy=policy,
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(
            platform=1,
            profile=1,
            workspace=1,
            agent=1,
        ),
        provider_capabilities=_validation_provider_capabilities(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )
    return resolution.availability_reason


def _require_policy_capability_available(
    policy: RuntimeExecutionPolicyDocument,
    *,
    target_id: str,
) -> None:
    """Reject authority content without current compatible enforcement."""
    reason = _policy_capability_reason(policy)
    if reason is not None:
        raise RuntimeExecutionPolicyUnavailable(reason.value, target_id)


def _workspace_view(
    workspace_id: str,
    workspace: WorkspaceRuntimeExecutionPolicy | None,
) -> WorkspaceRuntimeExecutionPolicyView:
    """Project an absent Workspace row as the safe initial policy."""
    if workspace is not None:
        return WorkspaceRuntimeExecutionPolicyView(
            workspace_id=workspace.workspace_id,
            version=workspace.version,
            restriction=workspace.restriction,
            digest=workspace.digest,
            allowed_profile_ids=workspace.allowed_profile_ids,
            updated_at=workspace.updated_at,
        )
    restriction = empty_runtime_execution_restriction()
    return WorkspaceRuntimeExecutionPolicyView(
        workspace_id=workspace_id,
        version=0,
        restriction=restriction,
        digest=digest_runtime_execution_policy(restriction),
        allowed_profile_ids=frozenset({SYSTEM_STANDARD_PROFILE_ID}),
        updated_at=None,
    )


def _profile_availability(
    profile: RuntimeExecutionProfile,
    allowed_profile_ids: frozenset[str],
    *,
    capability_reason: RuntimeExecutionAvailabilityReason | None,
) -> RuntimeExecutionProfileAvailability:
    """Build one bounded Workspace-level Profile availability explanation."""
    allowed = profile.id in allowed_profile_ids
    if profile.lifecycle is RuntimeExecutionProfileLifecycle.RETIRED:
        reason = RuntimeExecutionAvailabilityReason.PROFILE_RETIRED
    elif not allowed:
        reason = RuntimeExecutionAvailabilityReason.PROFILE_NOT_ALLOWED
    elif capability_reason is not None:
        reason = capability_reason
    else:
        reason = None
    return RuntimeExecutionProfileAvailability(
        profile=profile,
        allowed=allowed,
        available=reason is None,
        reason=reason,
    )
