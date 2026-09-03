"""Current durable and Runner Runtime Terminal authority tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    AgentType,
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
)
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session.data import AgentSession
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationAppliedSlot,
    RuntimeConfigurationSlot,
    RuntimeConfigurationState,
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
)
from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeRunnerRegistration,
)
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.services.runtime_terminal.authority import (
    DatabaseRuntimeTerminalAuthorityResolver,
)
from azents.services.runtime_terminal.data import (
    RuntimeTerminalProjectionState,
    RuntimeTerminalReasonCode,
    RuntimeTerminalResource,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderAuthority,
)
from azents.services.terminal_policy.service import TerminalPolicyResolver

_NOW = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.UTC)
_RESOURCE = RuntimeTerminalResource(
    workspace_handle="workspace",
    agent_id="agent-1",
    session_id="session-1",
)


@pytest.mark.asyncio
async def test_authority_accepts_terminal_only_profile_version_without_recreation() -> (
    None
):
    """Current policy versions may advance without changing applied Runtime bytes."""
    resolver, runtime_coordination, working_folder = _resolver(
        runtime=_runtime(),
        applied=_applied(workspace_profile_version=6),
        workspace_profile=_workspace_profile(version=7),
    )
    await _register_runner(runtime_coordination, terminal_capability=True)

    authority = await resolver.resolve(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
        resolved_at=_NOW,
    )

    assert authority.projection_state is RuntimeTerminalProjectionState.READY
    assert authority.reason_code is None
    assert authority.can_open_or_attach is True
    assert authority.workspace_profile_version == 7
    assert authority.provider_profile_version == 4
    assert authority.working_directory == "/workspace/.azents/sessions/session"
    working_folder.resolve_bound_authority_for_target.assert_awaited_once()


@pytest.mark.asyncio
async def test_authority_projects_stopped_runtime_without_runner_or_auto_start() -> (
    None
):
    """A stopped Runtime stays an explicit user-start action."""
    resolver, _runtime_coordination, working_folder = _resolver(
        runtime=_runtime(
            desired_state=RuntimeDesiredState.STOPPED,
            desired_generation=3,
            provider_observed_state=RuntimeProviderObservedState.STOPPED,
            provider_observed_generation=3,
            runner_state=RuntimeRunnerState.DISCONNECTED,
            runner_generation=0,
            workspace_path=None,
        ),
        applied=_applied(target_generation=2),
    )

    authority = await resolver.resolve(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
        resolved_at=_NOW,
    )

    assert authority.projection_state is RuntimeTerminalProjectionState.STOPPED
    assert authority.reason_code is RuntimeTerminalReasonCode.RUNTIME_STOPPED
    assert authority.can_start_runtime is True
    assert authority.can_open_or_attach is False
    working_folder.resolve_bound_authority_for_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_authority_fails_closed_for_runner_without_terminal_capability() -> None:
    """Mixed deployments expose the bounded unsupported-Runner reason."""
    resolver, runtime_coordination, working_folder = _resolver()
    await _register_runner(runtime_coordination, terminal_capability=False)

    authority = await resolver.resolve(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
        resolved_at=_NOW,
    )

    assert authority.projection_state is RuntimeTerminalProjectionState.UNAVAILABLE
    assert (
        authority.reason_code is RuntimeTerminalReasonCode.RUNNER_TERMINAL_UNSUPPORTED
    )
    assert authority.can_open_or_attach is False
    working_folder.resolve_bound_authority_for_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_agent_requires_owner_or_agent_admin() -> None:
    """Ordinary Workspace membership cannot authorize a Private Agent Terminal."""
    resolver, _runtime_coordination, working_folder = _resolver(
        agent=_agent(agent_type=AgentType.PRIVATE),
        workspace_role=WorkspaceUserRole.MEMBER,
        agent_admin=False,
    )

    authority = await resolver.resolve(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
        resolved_at=_NOW,
    )

    assert authority.projection_state is RuntimeTerminalProjectionState.ABSENT
    assert authority.reason_code is RuntimeTerminalReasonCode.AGENT_NOT_FOUND
    working_folder.resolve_bound_authority_for_target.assert_not_awaited()


def _resolver(
    *,
    runtime: AgentRuntime | None = None,
    applied: RuntimeConfigurationAppliedSlot | None = None,
    workspace_profile: WorkspaceRuntimeProfile | None = None,
    agent: Agent | None = None,
    workspace_role: WorkspaceUserRole = WorkspaceUserRole.OWNER,
    agent_admin: bool = False,
) -> tuple[
    DatabaseRuntimeTerminalAuthorityResolver,
    InMemoryRuntimeCoordinationStore,
    AsyncMock,
]:
    runtime = runtime or _runtime()
    applied = applied or _applied()
    workspace_profile = workspace_profile or _workspace_profile()
    user_repository = AsyncMock()
    authentication_session_repository = AsyncMock()
    workspace_repository = AsyncMock()
    workspace_user_repository = AsyncMock()
    agent_repository = AsyncMock()
    agent_admin_repository = AsyncMock()
    agent_session_repository = AsyncMock()
    runtime_repository = AsyncMock()
    profile_repository = AsyncMock()
    working_folder = AsyncMock()
    runtime_coordination = InMemoryRuntimeCoordinationStore()

    user_repository.get.return_value = SimpleNamespace(access_disabled_at=None)
    authentication_session_repository.get.return_value = SimpleNamespace(
        user_id="user-1",
        revoked_at=None,
        expires_at=_NOW + datetime.timedelta(hours=1),
    )
    workspace_repository.get_with_id_by_handle.return_value = (
        "workspace-1",
        SimpleNamespace(handle="workspace"),
    )
    workspace_user_repository.get_by_workspace_and_user.return_value = SimpleNamespace(
        id="workspace-user-1",
        role=workspace_role,
    )
    agent_repository.get_by_id.return_value = agent or _agent()
    agent_admin_repository.is_admin.return_value = agent_admin
    agent_session_repository.get_by_id.return_value = _agent_session()
    runtime_repository.get_by_agent_id.return_value = runtime
    profile_repository.get_workspace_runtime_profile.return_value = workspace_profile
    profile_repository.get_infrastructure_profile.return_value = (
        _infrastructure_profile()
    )
    profile_repository.get_configuration_state.return_value = RuntimeConfigurationState(
        runtime_id=runtime.id,
        desired=RuntimeConfigurationSlot(
            sequence=1,
            status=RuntimeConfigurationStateStatus.READY,
            target_generation=runtime.desired_generation,
            digest="d" * 64,
            document=None,
            reason_code=None,
            provider_reported_digest=None,
            runner_reported_digest=None,
            provider_acknowledged_at=None,
            runner_observed_at=None,
        ),
        applied=applied,
        created_at=_NOW,
        updated_at=_NOW,
    )
    working_folder.resolve_bound_authority_for_target.return_value = (
        SessionWorkingFolderAuthority(
            context_id="context-1",
            agent_id="agent-1",
            agent_runtime_id=runtime.id,
            working_folder_path="/workspace/.azents/sessions/session",
            runtime_capability_version=3,
        )
    )

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[Any, None]:
        yield SimpleNamespace()

    resolver = DatabaseRuntimeTerminalAuthorityResolver(
        session_manager=session_manager,
        user_repository=user_repository,
        authentication_session_repository=authentication_session_repository,
        workspace_repository=workspace_repository,
        workspace_user_repository=workspace_user_repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        agent_session_repository=agent_session_repository,
        runtime_repository=runtime_repository,
        profile_repository=profile_repository,
        runtime_coordination=runtime_coordination,
        working_folder_service=working_folder,
        policy_resolver=TerminalPolicyResolver(),
    )
    return resolver, runtime_coordination, working_folder


async def _register_runner(
    store: InMemoryRuntimeCoordinationStore,
    *,
    terminal_capability: bool,
) -> None:
    capabilities = ["file.transfer.v1"]
    if terminal_capability:
        capabilities.append("terminal.v1")
    await RuntimeControlProtocolService(store).register_runner(
        RuntimeRunnerRegistration(
            runtime_id="runtime-1",
            runner_id="runner-1",
            protocol_version="2026-07-25",
            capabilities=RuntimeProtocolCapabilities(tuple(capabilities)),
            health="ok",
            workspace_path="/workspace",
            metadata={},
            auth_credential_id="credential-1",
            runtime_configuration=RuntimeConfigurationEvidence(
                configuration_sequence=1,
                digest="d" * 64,
                desired_generation=2,
            ),
            connection_id="connection-1",
            owner_replica_id="control-1",
        ),
        registered_at=datetime.datetime.now(datetime.UTC),
    )


def _agent(*, agent_type: AgentType = AgentType.PUBLIC) -> Agent:
    return Agent.model_construct(
        id="agent-1",
        workspace_id="workspace-1",
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=agent_type,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        runtime_capability_version=3,
        runtime_profile_id="workspace-profile-1",
        runtime_profile_selection_version=5,
        terminal_enabled=True,
        updated_at=_NOW,
    )


def _agent_session() -> AgentSession:
    return AgentSession.model_construct(
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        status=AgentSessionStatus.ACTIVE,
        session_kind=AgentSessionKind.ROOT,
        product_mode=AgentSessionProductMode.USER,
        associated_user_id="user-1",
    )


def _runtime(
    *,
    desired_state: RuntimeDesiredState = RuntimeDesiredState.RUNNING,
    desired_generation: int = 2,
    provider_observed_state: RuntimeProviderObservedState = (
        RuntimeProviderObservedState.RUNNING
    ),
    provider_observed_generation: int = 2,
    runner_state: RuntimeRunnerState = RuntimeRunnerState.READY,
    runner_generation: int = 1,
    workspace_path: str | None = "/workspace",
) -> AgentRuntime:
    return AgentRuntime.model_construct(
        id="runtime-1",
        desired_state=desired_state,
        desired_generation=desired_generation,
        terminal_delete_requested_generation=None,
        provider_observed_state=provider_observed_state,
        provider_observed_generation=provider_observed_generation,
        runner_state=runner_state,
        runner_generation=runner_generation,
        workspace_path=workspace_path,
    )


def _infrastructure_profile() -> RuntimeInfrastructureProfile:
    return RuntimeInfrastructureProfile(
        id="infrastructure-profile-1",
        provider_id="provider-1",
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        display_name="Docker",
        description="Docker",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        contract_family="docker.container-profile",
        schema_version=1,
        spec={"schema_version": 1},
        required_capabilities=(),
        terminal_enabled=True,
        version=4,
        digest="a" * 64,
        created_by_user_id=None,
        updated_by_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _workspace_profile(*, version: int = 7) -> WorkspaceRuntimeProfile:
    return WorkspaceRuntimeProfile(
        id="workspace-profile-1",
        workspace_id="workspace-1",
        provider_id="provider-1",
        infrastructure_profile_id="infrastructure-profile-1",
        display_name="Workspace Docker",
        description="Workspace Docker",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        policy={"schema_version": 1},
        terminal_enabled=True,
        version=version,
        digest="b" * 64,
        created_by_workspace_user_id=None,
        updated_by_workspace_user_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _applied(
    *,
    target_generation: int = 2,
    workspace_profile_version: int = 7,
) -> RuntimeConfigurationAppliedSlot:
    return RuntimeConfigurationAppliedSlot(
        sequence=1,
        target_generation=target_generation,
        digest="d" * 64,
        document=RuntimeConfigurationDocument(
            schema_version=1,
            source_trace={},
            provider_id="provider-1",
            provider_capability_revision_id=None,
            infrastructure_profile_id="infrastructure-profile-1",
            infrastructure_profile_version=4,
            workspace_runtime_profile_id="workspace-profile-1",
            workspace_runtime_profile_version=workspace_profile_version,
            agent_selection_version=5,
            required_capabilities=(),
            missing_capabilities=(),
            resolved_configuration={},
        ),
        applied_at=_NOW,
    )
