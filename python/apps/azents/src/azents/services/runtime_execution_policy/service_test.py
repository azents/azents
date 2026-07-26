"""Runtime execution policy service tests."""

import datetime
from contextlib import asynccontextmanager
from typing import AsyncIterator, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_execution_policy import (
    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
    SYSTEM_STANDARD_PROFILE_ID,
    RuntimeExecutionBooleanModule,
    RuntimeExecutionBooleanRestriction,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionModuleId,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionResourceRestriction,
    RuntimeExecutionStorageMode,
    RuntimeExecutionStorageRestriction,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    standard_runtime_execution_policy,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.runtime_execution_policy.data import (
    AgentRuntimeExecutionSetting,
    RuntimeExecutionPlatformPolicy,
    RuntimeExecutionProfile,
    WorkspaceRuntimeExecutionPolicy,
)
from azents.repos.runtime_execution_policy.repository import (
    RuntimeExecutionPolicyRepository,
)

from .service import (
    AgentRuntimeExecutionSettingMutation,
    RuntimeExecutionPlatformMutation,
    RuntimeExecutionPolicyService,
    RuntimeExecutionPolicyUnavailable,
    RuntimeExecutionPolicyVersionConflict,
    RuntimeExecutionProfileMutation,
    WorkspaceRuntimeExecutionPolicyMutation,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _platform(*, version: int = 1) -> RuntimeExecutionPlatformPolicy:
    policy = standard_runtime_execution_policy()
    return RuntimeExecutionPlatformPolicy(
        id=RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
        version=version,
        policy=policy,
        digest=digest_runtime_execution_policy(policy),
        updated_by_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _expanded_standard() -> RuntimeExecutionPolicyDocument:
    policy = standard_runtime_execution_policy()
    return policy.model_copy(
        update={
            "image_build": RuntimeExecutionBooleanModule(
                module_id=RuntimeExecutionModuleId.IMAGE_BUILD,
                version=1,
                enabled=True,
            )
        }
    )


def _profile(
    *,
    reserved: bool,
    profile_id: str = SYSTEM_STANDARD_PROFILE_ID,
    lifecycle: RuntimeExecutionProfileLifecycle = (
        RuntimeExecutionProfileLifecycle.ACTIVE
    ),
) -> RuntimeExecutionProfile:
    policy = standard_runtime_execution_policy()
    return RuntimeExecutionProfile(
        id=profile_id,
        display_name="Standard",
        description="Baseline",
        lifecycle=lifecycle,
        version=1,
        policy=policy,
        digest=digest_runtime_execution_policy(policy),
        reserved=reserved,
        system_key=profile_id if reserved else None,
        updated_by_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _workspace(
    *,
    allowed_profile_ids: frozenset[str],
    restriction: RuntimeExecutionPolicyRestriction,
    version: int = 1,
) -> WorkspaceRuntimeExecutionPolicy:
    return WorkspaceRuntimeExecutionPolicy(
        workspace_id="workspace-1",
        version=version,
        restriction=restriction,
        digest=digest_runtime_execution_policy(restriction),
        allowed_profile_ids=allowed_profile_ids,
        updated_by_workspace_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    repository: Mock,
    agent_admin_repository: Mock | None = None,
) -> RuntimeExecutionPolicyService:
    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, Mock())

    return RuntimeExecutionPolicyService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(RuntimeExecutionPolicyRepository, repository),
        agent_admin_repository=cast(
            AgentAdminRepository,
            agent_admin_repository or Mock(),
        ),
    )


@pytest.mark.asyncio
async def test_stale_platform_write_has_no_mutation_or_audit_side_effect() -> None:
    """Expected-version rejection occurs before settings or audit writes."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_platform = AsyncMock(return_value=_platform(version=2))
    repository.replace_platform = AsyncMock()
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    with pytest.raises(RuntimeExecutionPolicyVersionConflict):
        await service.replace_platform(
            RuntimeExecutionPlatformMutation(
                expected_version=1,
                policy=standard_runtime_execution_policy(),
                actor_user_id="user-1",
                correlation_id="correlation-1",
            )
        )

    repository.replace_platform.assert_not_awaited()
    repository.append_audit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_platform_write_does_not_append_audit() -> None:
    """A conditional update race remains free of partial audit effects."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.replace_platform = AsyncMock(return_value=None)
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    with pytest.raises(RuntimeExecutionPolicyVersionConflict):
        await service.replace_platform(
            RuntimeExecutionPlatformMutation(
                expected_version=1,
                policy=standard_runtime_execution_policy(),
                actor_user_id="user-1",
                correlation_id="correlation-1",
            )
        )

    repository.append_audit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserved_standard_authority_cannot_be_changed() -> None:
    """Ordinary Profile mutation cannot broaden reserved Standard authority."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_profile = AsyncMock(return_value=_profile(reserved=True))
    repository.replace_profile = AsyncMock()
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    with pytest.raises(
        RuntimeExecutionPolicyUnavailable,
        match="reserved_profile_policy_immutable",
    ):
        await service.replace_profile(
            SYSTEM_STANDARD_PROFILE_ID,
            RuntimeExecutionProfileMutation(
                expected_version=1,
                display_name="Standard",
                description="Changed metadata",
                policy=_expanded_standard(),
                actor_user_id="user-1",
                correlation_id="correlation-1",
            ),
        )

    repository.replace_profile.assert_not_awaited()
    repository.append_audit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_restriction_cannot_expand_platform_boundary() -> None:
    """Workspace writes reject broader storage authority before persistence."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_workspace = AsyncMock(return_value=None)
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.profile_ids_exist = AsyncMock()
    repository.replace_workspace = AsyncMock()
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    with pytest.raises(ValueError, match="engine_storage.mode"):
        await service.replace_workspace(
            "workspace-1",
            WorkspaceRuntimeExecutionPolicyMutation(
                expected_version=0,
                restriction=RuntimeExecutionPolicyRestriction(
                    schema_version=1,
                    image_build=None,
                    container_run=None,
                    compose=None,
                    resources=None,
                    engine_storage=RuntimeExecutionStorageRestriction(
                        mode=RuntimeExecutionStorageMode.EPHEMERAL,
                        capacity_bytes=1_000,
                    ),
                    network_egress=None,
                ),
                allowed_profile_ids=frozenset({SYSTEM_STANDARD_PROFILE_ID}),
                actor_workspace_user_id="workspace-user-1",
                correlation_id="correlation-1",
            ),
        )

    repository.profile_ids_exist.assert_not_awaited()
    repository.replace_workspace.assert_not_awaited()
    repository.append_audit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_cannot_newly_select_workspace_disallowed_profile() -> None:
    """An unavailable Profile cannot become a new Agent selection."""
    restriction = empty_runtime_execution_restriction()
    current = AgentRuntimeExecutionSetting(
        agent_id="agent-1",
        profile_id=SYSTEM_STANDARD_PROFILE_ID,
        version=1,
        restriction=restriction,
        digest=digest_runtime_execution_policy(restriction),
        updated_by_workspace_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    workspace = WorkspaceRuntimeExecutionPolicy(
        workspace_id="workspace-1",
        version=1,
        restriction=restriction,
        digest=digest_runtime_execution_policy(restriction),
        allowed_profile_ids=frozenset({SYSTEM_STANDARD_PROFILE_ID}),
        updated_by_workspace_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_agent_setting = AsyncMock(return_value=current)
    repository.get_agent_workspace_id = AsyncMock(return_value="workspace-1")
    repository.get_profile = AsyncMock(
        return_value=_profile(reserved=False, profile_id="profile-2")
    )
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.get_workspace = AsyncMock(return_value=workspace)
    repository.replace_agent_setting = AsyncMock()
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    with pytest.raises(RuntimeExecutionPolicyUnavailable, match="profile_unavailable"):
        await service.replace_agent_setting(
            "agent-1",
            AgentRuntimeExecutionSettingMutation(
                expected_version=1,
                profile_id="profile-2",
                restriction=restriction,
                actor_workspace_user_id="workspace-user-1",
                correlation_id="correlation-1",
            ),
        )

    repository.replace_agent_setting.assert_not_awaited()
    repository.append_audit_event.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "restricted", "adding", "expected", "expected_path"),
    [
        (
            "image_build",
            RuntimeExecutionBooleanRestriction(enabled=False),
            True,
            RuntimeExecutionChangeDirection.RESTRICTIVE,
            "image_build.enabled",
        ),
        (
            "resources",
            RuntimeExecutionResourceRestriction(
                cpu_millicores=100,
                memory_bytes=None,
                pids=None,
                container_count=None,
                ephemeral_storage_bytes=None,
            ),
            True,
            RuntimeExecutionChangeDirection.RESTRICTIVE,
            "resources.cpu_millicores",
        ),
        (
            "image_build",
            RuntimeExecutionBooleanRestriction(enabled=False),
            False,
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
            "image_build.enabled",
        ),
        (
            "resources",
            RuntimeExecutionResourceRestriction(
                cpu_millicores=100,
                memory_bytes=None,
                pids=None,
                container_count=None,
                ephemeral_storage_bytes=None,
            ),
            False,
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
            "resources.cpu_millicores",
        ),
    ],
)
async def test_workspace_restriction_audit_aligns_optional_nested_modules(
    field: str,
    restricted: RuntimeExecutionBooleanRestriction
    | RuntimeExecutionResourceRestriction,
    adding: bool,
    expected: RuntimeExecutionChangeDirection,
    expected_path: str,
) -> None:
    """Adding and removing an optional nested restriction remains classifiable."""
    empty = empty_runtime_execution_restriction()
    narrowed = empty.model_copy(update={field: restricted})
    previous = empty if adding else narrowed
    current = narrowed if adding else empty
    allowed = frozenset({SYSTEM_STANDARD_PROFILE_ID})
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_workspace = AsyncMock(
        return_value=_workspace(
            allowed_profile_ids=allowed,
            restriction=previous,
        )
    )
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.profile_ids_exist = AsyncMock(return_value=True)
    repository.replace_workspace = AsyncMock(
        return_value=_workspace(
            allowed_profile_ids=allowed,
            restriction=current,
            version=2,
        )
    )
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    await service.replace_workspace(
        "workspace-1",
        WorkspaceRuntimeExecutionPolicyMutation(
            expected_version=1,
            restriction=current,
            allowed_profile_ids=allowed,
            actor_workspace_user_id="workspace-user-1",
            correlation_id="correlation-1",
        ),
    )

    audit = repository.append_audit_event.await_args.kwargs["create"]
    assert audit.classification is expected
    assert audit.changed_paths == (expected_path,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (
            frozenset({SYSTEM_STANDARD_PROFILE_ID}),
            frozenset({SYSTEM_STANDARD_PROFILE_ID, "profile-2"}),
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
        ),
        (
            frozenset({SYSTEM_STANDARD_PROFILE_ID, "profile-2"}),
            frozenset({SYSTEM_STANDARD_PROFILE_ID}),
            RuntimeExecutionChangeDirection.RESTRICTIVE,
        ),
        (
            frozenset({SYSTEM_STANDARD_PROFILE_ID, "profile-2"}),
            frozenset({SYSTEM_STANDARD_PROFILE_ID, "profile-3"}),
            RuntimeExecutionChangeDirection.MIXED,
        ),
    ],
)
async def test_workspace_allowance_audit_classifies_set_direction(
    previous: frozenset[str],
    current: frozenset[str],
    expected: RuntimeExecutionChangeDirection,
) -> None:
    """Workspace allowance audit distinguishes additions and removals."""
    restriction = empty_runtime_execution_restriction()
    current_workspace = _workspace(
        allowed_profile_ids=previous,
        restriction=restriction,
    )
    updated_workspace = _workspace(
        allowed_profile_ids=current,
        restriction=restriction,
        version=2,
    )
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_workspace = AsyncMock(return_value=current_workspace)
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.profile_ids_exist = AsyncMock(return_value=True)
    repository.replace_workspace = AsyncMock(return_value=updated_workspace)
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    await service.replace_workspace(
        "workspace-1",
        WorkspaceRuntimeExecutionPolicyMutation(
            expected_version=1,
            restriction=empty_runtime_execution_restriction(),
            allowed_profile_ids=current,
            actor_workspace_user_id="workspace-user-1",
            correlation_id="correlation-1",
        ),
    )

    audit = repository.append_audit_event.await_args.kwargs["create"]
    assert audit.classification is expected
    assert audit.changed_paths == ("allowed_profile_ids",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("allowed_profile_ids", "expected", "expected_paths"),
    [
        (
            frozenset({SYSTEM_STANDARD_PROFILE_ID}),
            RuntimeExecutionChangeDirection.METADATA_ONLY,
            (),
        ),
        (
            frozenset({SYSTEM_STANDARD_PROFILE_ID, "profile-2"}),
            RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING,
            ("allowed_profile_ids",),
        ),
    ],
)
async def test_workspace_first_materialization_uses_implicit_standard_allowance(
    allowed_profile_ids: frozenset[str],
    expected: RuntimeExecutionChangeDirection,
    expected_paths: tuple[str, ...],
) -> None:
    """A missing Workspace row already implies the Standard-only allowance."""
    restriction = empty_runtime_execution_restriction()
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_workspace = AsyncMock(return_value=None)
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.profile_ids_exist = AsyncMock(return_value=True)
    repository.replace_workspace = AsyncMock(
        return_value=_workspace(
            allowed_profile_ids=allowed_profile_ids,
            restriction=restriction,
        )
    )
    repository.append_audit_event = AsyncMock()
    service = _service(repository)

    await service.replace_workspace(
        "workspace-1",
        WorkspaceRuntimeExecutionPolicyMutation(
            expected_version=0,
            restriction=restriction,
            allowed_profile_ids=allowed_profile_ids,
            actor_workspace_user_id="workspace-user-1",
            correlation_id="correlation-1",
        ),
    )

    audit = repository.append_audit_event.await_args.kwargs["create"]
    assert audit.classification is expected
    assert audit.changed_paths == expected_paths


@pytest.mark.asyncio
async def test_missing_workspace_read_projects_safe_version_zero_policy() -> None:
    """The first Workspace write can use the version returned by its read."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_workspace = AsyncMock(return_value=None)
    service = _service(repository)

    policy = await service.get_workspace_policy("workspace-1")

    assert policy.version == 0
    assert policy.allowed_profile_ids == frozenset({SYSTEM_STANDARD_PROFILE_ID})
    assert policy.restriction == empty_runtime_execution_restriction()
    assert policy.updated_at is None


@pytest.mark.asyncio
async def test_workspace_service_rejects_member_mutation() -> None:
    """Workspace mutation authority is enforced below the HTTP route."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_workspace = AsyncMock()
    service = _service(repository)

    with pytest.raises(
        RuntimeExecutionPolicyUnavailable,
        match="workspace_policy_access_denied",
    ):
        await service.replace_workspace_for_manager(
            "workspace-1",
            WorkspaceRuntimeExecutionPolicyMutation(
                expected_version=0,
                restriction=empty_runtime_execution_restriction(),
                allowed_profile_ids=frozenset({SYSTEM_STANDARD_PROFILE_ID}),
                actor_workspace_user_id="workspace-user-1",
                correlation_id="correlation-1",
            ),
            role=WorkspaceUserRole.MEMBER,
        )

    repository.get_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_audit_read_is_limited_to_workspace_layer() -> None:
    """Workspace audit does not expose Agent-layer events in the same Workspace."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.list_audit_events = AsyncMock(return_value=[])
    service = _service(repository)

    assert (
        await service.list_workspace_audit_events(
            "workspace-1",
            offset=0,
            limit=50,
        )
        == []
    )
    repository.list_audit_events.assert_awaited_once_with(
        repository.list_audit_events.await_args.args[0],
        management_layer=RuntimeExecutionManagementLayer.WORKSPACE,
        target_id=None,
        workspace_id="workspace-1",
        agent_id=None,
        offset=0,
        limit=50,
    )


@pytest.mark.asyncio
async def test_agent_policy_read_rejects_non_admin_workspace_manager() -> None:
    """Workspace Manager role alone does not grant Agent administration."""
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_agent_workspace_id = AsyncMock(return_value="workspace-1")
    agent_admin_repository = Mock(spec=AgentAdminRepository)
    agent_admin_repository.is_admin = AsyncMock(return_value=False)
    service = _service(repository, agent_admin_repository)

    with pytest.raises(RuntimeExecutionPolicyUnavailable, match="agent_access_denied"):
        await service.get_agent_policy_for_manager(
            "agent-1",
            workspace_id="workspace-1",
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.MANAGER,
        )


@pytest.mark.asyncio
async def test_agent_admin_receives_hierarchy_preview_without_provider_claim() -> None:
    """Agent administrators receive safe hierarchy state without fake compatibility."""
    restriction = empty_runtime_execution_restriction()
    setting = AgentRuntimeExecutionSetting(
        agent_id="agent-1",
        profile_id=SYSTEM_STANDARD_PROFILE_ID,
        version=1,
        restriction=restriction,
        digest=digest_runtime_execution_policy(restriction),
        updated_by_workspace_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repository = Mock(spec=RuntimeExecutionPolicyRepository)
    repository.get_agent_workspace_id = AsyncMock(return_value="workspace-1")
    repository.get_platform = AsyncMock(return_value=_platform())
    repository.get_agent_setting = AsyncMock(return_value=setting)
    repository.get_workspace = AsyncMock(return_value=None)
    repository.get_profile = AsyncMock(return_value=_profile(reserved=True))
    agent_admin_repository = Mock(spec=AgentAdminRepository)
    agent_admin_repository.is_admin = AsyncMock(return_value=True)
    service = _service(repository, agent_admin_repository)

    policy = await service.get_agent_policy_for_manager(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
    )

    assert policy.setting == setting
    assert policy.resolution.available
    assert policy.provider_compatibility_evaluated is False
