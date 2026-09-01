"""Unified public Agent Runtime read-model tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import DEFAULT_MAIN_MODEL_OPTION_LABEL, SelectableModelOption
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExternalChannelResponseMode,
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.core.runtime_profile import RuntimeConfigurationStateStatus
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_runtime_removal_scope.data import AgentRuntimeRemovalImpact
from azents.repos.runtime_profile.data import (
    RuntimeConfigurationSlot,
    RuntimeConfigurationState,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)

from .service import AgentRuntimeService

_NOW = datetime.datetime.now(datetime.UTC)


def _agent(
    *,
    capability: AgentRuntimeCapability,
    runtime_profile_id: str | None = None,
) -> Agent:
    """Create one Agent projection input."""
    selection = make_test_model_selection()
    return Agent(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=[
            SelectableModelOption(
                label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                model_selection=selection,
                settings=make_test_model_settings(),
            )
        ],
        main_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        lightweight_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        external_channel_default_response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_profile_id=runtime_profile_id,
        runtime_profile_selection_version=3,
        runtime_capability=capability,
        runtime_capability_version=5,
        shell_enabled=False,
        terminal_enabled=True,
        memory_enabled=True,
        tool_search_enabled=True,
        max_turns=None,
        auto_archive_ttl_days=30,
        avatar=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _running_runtime() -> AgentRuntime:
    """Create one running physical Runtime projection input."""
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runtime_provider_id="provider-1",
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=2,
        last_lifecycle_command=None,
        reset_final_desired_state=None,
        terminal_delete_requested_generation=None,
        terminal_delete_acknowledged_generation=None,
        terminal_delete_acknowledged_at=None,
        terminal_delete_acknowledgement_kind=None,
        provider_observed_state=RuntimeProviderObservedState.RUNNING,
        provider_observed_generation=2,
        provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
        runner_state=RuntimeRunnerState.READY,
        runner_generation=2,
        workspace_path="/workspace",
        failure_generation=None,
        failure_code=None,
        failure_message=None,
        last_state_change_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _unconfigured_state() -> RuntimeConfigurationState:
    """Create retained current-state evidence for an unconfigured Runtime."""
    return RuntimeConfigurationState(
        runtime_id="runtime-1",
        desired=RuntimeConfigurationSlot(
            sequence=1,
            status=RuntimeConfigurationStateStatus.UNCONFIGURED,
            target_generation=2,
            digest=None,
            document=None,
            reason_code="runtime_profile_required",
            provider_reported_digest=None,
            runner_reported_digest=None,
            provider_acknowledged_at=None,
            runner_observed_at=None,
        ),
        applied=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    agent: Agent,
    *,
    can_manage: bool,
    impact: AgentRuntimeRemovalImpact | None = None,
    profile: object | None = None,
    runtime: AgentRuntime | None = None,
) -> "_ServiceFixture":
    """Create a Runtime service with read-only repository doubles."""

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, object())

    ensure_for_agent = AsyncMock()
    get_impact = AsyncMock(return_value=impact)
    get_profile = AsyncMock(return_value=profile)
    service = object.__new__(AgentRuntimeService)
    service.session_manager = cast(Any, session_manager)
    service.agent_repository = cast(
        Any,
        SimpleNamespace(get_by_id=AsyncMock(return_value=agent)),
    )
    service.agent_admin_repository = cast(
        Any,
        SimpleNamespace(is_admin=AsyncMock(return_value=can_manage)),
    )
    service.runtime_repository = cast(
        Any,
        SimpleNamespace(get_by_agent_id=AsyncMock(return_value=runtime)),
    )
    service.removal_repository = cast(
        Any,
        SimpleNamespace(
            get_active_by_agent_id=AsyncMock(return_value=None),
            get_latest_completed_by_agent_id=AsyncMock(return_value=None),
        ),
    )
    service.removal_scope_repository = cast(
        Any,
        SimpleNamespace(get_impact=get_impact),
    )
    service.runtime_profile_resolution_service = cast(
        Any,
        SimpleNamespace(ensure_for_agent=ensure_for_agent),
    )
    service.runtime_profile_workspace_service = cast(
        Any,
        SimpleNamespace(get_profile=get_profile),
    )
    service.runtime_profile_repository = cast(
        Any,
        SimpleNamespace(
            get_configuration_state=AsyncMock(
                return_value=_unconfigured_state() if runtime is not None else None
            )
        ),
    )
    service.transition_service = cast(Any, AsyncMock())
    return _ServiceFixture(
        service=service,
        ensure_for_agent=ensure_for_agent,
        get_impact=get_impact,
        get_profile=get_profile,
    )


@dataclasses.dataclass(frozen=True)
class _ServiceFixture:
    """Runtime service and its observable read-boundary doubles."""

    service: AgentRuntimeService
    ensure_for_agent: AsyncMock
    get_impact: AsyncMock
    get_profile: AsyncMock


async def test_runtime_free_get_is_read_only_and_has_no_physical_summary() -> None:
    """Runtime GET does not ensure a missing logical or physical Runtime."""
    fixture = _service(
        _agent(capability=AgentRuntimeCapability.NONE),
        can_manage=True,
    )

    result = await fixture.service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Success)
    assert result.value.capability is AgentRuntimeCapability.NONE
    assert result.value.runtime is None
    assert result.value.lifecycle is None
    assert result.value.configuration is None
    assert result.value.actions.add is True
    assert result.value.actions.remove is False
    assert result.value.runtime_profile_status == "not_applicable"
    fixture.ensure_for_agent.assert_not_awaited()


async def test_managed_unconfigured_projection_exposes_only_manager_actions() -> None:
    """Profile and destructive impact projections are management-contextual."""
    impact = AgentRuntimeRemovalImpact(
        active_root_session_count=2,
        active_subagent_count=3,
        active_run_count=1,
        queued_runtime_action_count=4,
    )
    manager_fixture = _service(
        _agent(capability=AgentRuntimeCapability.MANAGED),
        can_manage=True,
        impact=impact,
    )
    member_fixture = _service(
        _agent(capability=AgentRuntimeCapability.MANAGED),
        can_manage=False,
        impact=impact,
    )

    manager_result = await manager_fixture.service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )
    member_result = await member_fixture.service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-2",
        role=WorkspaceUserRole.MEMBER,
    )

    assert isinstance(manager_result, Success)
    assert manager_result.value.runtime_profile_status == "profile_required"
    assert manager_result.value.actions.remove is True
    assert manager_result.value.removal_impact == impact
    assert isinstance(member_result, Success)
    assert member_result.value.actions.remove is False
    assert member_result.value.removal_impact is None
    member_fixture.get_impact.assert_not_awaited()


async def test_managed_configured_missing_runtime_can_start_read_only() -> None:
    """Lazy provisioning remains an explicit start action after read-only GET."""
    fixture = _service(
        _agent(
            capability=AgentRuntimeCapability.MANAGED,
            runtime_profile_id="profile-1",
        ),
        can_manage=True,
        profile=SimpleNamespace(available=True, reason_code=None),
    )

    result = await fixture.service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Success)
    assert result.value.runtime is None
    assert result.value.lifecycle is None
    assert result.value.runtime_profile_status == "configured"
    assert result.value.actions.start is True
    fixture.ensure_for_agent.assert_not_awaited()


@pytest.mark.parametrize(
    ("runtime_profile_id", "profile"),
    [
        (None, None),
        (
            "profile-1",
            SimpleNamespace(available=False, reason_code="provider_disabled"),
        ),
    ],
)
async def test_existing_runtime_actions_require_available_profile(
    runtime_profile_id: str | None,
    profile: object | None,
) -> None:
    """Unavailable Profile authority blocks creation-dependent Runtime actions."""
    fixture = _service(
        _agent(
            capability=AgentRuntimeCapability.MANAGED,
            runtime_profile_id=runtime_profile_id,
        ),
        can_manage=False,
        profile=profile,
        runtime=_running_runtime(),
    )

    result = await fixture.service.get(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-2",
        role=WorkspaceUserRole.MEMBER,
    )

    assert isinstance(result, Success)
    assert result.value.actions.start is False
    assert result.value.actions.restart is False
    assert result.value.actions.reset is False
    assert result.value.actions.use_runner is True
    assert result.value.actions.stop is True
    assert result.value.actions.observe is True
    fixture.ensure_for_agent.assert_not_awaited()
