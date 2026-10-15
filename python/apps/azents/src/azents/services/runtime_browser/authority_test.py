"""Current Runtime and trusted Session folder admission for public Browser."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple
from unittest.mock import AsyncMock

import pytest

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionKind,
    RuntimeDesiredState,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import RuntimeConfigurationDocument
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_browser_authority_read import (
    RuntimeBrowserAuthorityReadRepository,
    RuntimeBrowserDurableSnapshot,
    RuntimeBrowserIdentityDenied,
)
from azents.repos.runtime_profile.data import RuntimeConfigurationAppliedSlot
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.services.runtime_browser.authority import (
    DatabaseRuntimeBrowserAuthorityResolver,
)
from azents.services.runtime_browser.data import (
    RuntimeBrowserAuthority,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserUnavailable,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_RESOURCE = RuntimeBrowserResource("workspace", "agent-1", "child-session")


def _snapshot() -> RuntimeBrowserDurableSnapshot:
    return RuntimeBrowserDurableSnapshot(
        agent=Agent.model_construct(
            browser_enabled=True,
            id="agent-1",
            workspace_id="workspace-1",
            runtime_capability=AgentRuntimeCapability.MANAGED,
            runtime_capability_version=3,
        ),
        agent_session=AgentSession.model_construct(
            id="child-session",
            session_kind=AgentSessionKind.SUBAGENT,
        ),
        runtime=AgentRuntime.model_construct(
            id="runtime-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            desired_state=RuntimeDesiredState.RUNNING,
            desired_generation=8,
            provider_connection_state=RuntimeProviderConnectionState.CONNECTED,
            provider_observed_state=RuntimeProviderObservedState.RUNNING,
            provider_observed_generation=8,
            runner_state=RuntimeRunnerState.READY,
            runner_generation=5,
            workspace_path="/runner-reported",
            configuration_sequence=2,
            terminal_delete_requested_generation=None,
        ),
        applied_configuration=RuntimeConfigurationAppliedSlot(
            sequence=2,
            target_generation=8,
            digest="digest",
            document=RuntimeConfigurationDocument(
                schema_version=1,
                source_trace={},
                provider_id="provider-1",
                provider_capability_revision_id=None,
                infrastructure_profile_id="infra-1",
                infrastructure_profile_version=1,
                workspace_runtime_profile_id="profile-1",
                workspace_runtime_profile_version=1,
                agent_selection_version=1,
                required_capabilities=(),
                missing_capabilities=(),
                resolved_configuration={},
            ),
            applied_at=_NOW,
        ),
        authentication_session_expires_at=_NOW + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_disabled_browser_denies_before_runtime_or_folder_access() -> None:
    harness = _resolver()
    snapshot = _snapshot()
    harness.authority_repository.read_snapshot.return_value = dataclasses.replace(
        snapshot, agent=snapshot.agent.model_copy(update={"browser_enabled": False})
    )
    result = await _resolve(harness)
    assert result == RuntimeBrowserUnavailable("browser_disabled")
    harness.runtime_coordination.get_connection.assert_not_awaited()
    harness.working_folder_service.resolve_bound_authority_for_target.assert_not_awaited()


def _runner() -> RuntimeConnectionRecord:
    return RuntimeConnectionRecord(
        RuntimeConnectionKind.RUNNER,
        "runtime-1",
        "connection-1",
        "control-1",
        5,
        _NOW,
        _NOW,
        _NOW + timedelta(seconds=60),
        {"workspace_path": "/runner-reported", "capabilities": ["browser.v1"]},
    )


class _Harness(NamedTuple):
    resolver: DatabaseRuntimeBrowserAuthorityResolver
    authority_repository: AsyncMock
    runtime_coordination: AsyncMock
    working_folder_service: AsyncMock


def _resolver() -> _Harness:
    repository = AsyncMock(spec=RuntimeBrowserAuthorityReadRepository)
    repository.read_snapshot.return_value = _snapshot()
    coordination = AsyncMock(spec=RuntimeCoordinationStore)
    coordination.get_connection.return_value = _runner()
    folders = AsyncMock(spec=SessionWorkingFolderBindingService)
    folders.resolve_bound_authority_for_target.return_value = (
        SessionWorkingFolderAuthority(
            "context-1",
            "agent-1",
            "runtime-1",
            "/runner-reported/.azents/sessions/child-session",
            3,
        )
    )
    return _Harness(
        DatabaseRuntimeBrowserAuthorityResolver(repository, coordination, folders),
        repository,
        coordination,
        folders,
    )


async def _resolve(
    resolver: _Harness,
) -> RuntimeBrowserAuthority | RuntimeBrowserUnavailable:
    return await resolver.resolver.resolve(
        user_id="user-1",
        authentication_session_id="auth-1",
        resource=_RESOURCE,
        resolved_at=_NOW,
    )


async def test_admission_uses_current_runner_and_concrete_bound_child_session() -> None:
    resolver = _resolver()
    authority = await _resolve(resolver)
    assert isinstance(authority, RuntimeBrowserAuthority) and not authority.allow_input
    assert authority.working_directory.endswith("/.azents/sessions/child-session")
    assert authority.target.workspace_path == "/runner-reported"
    assert (
        authority.target.desired_generation == 8
        and authority.target.runner_generation == 5
    )
    resolver.working_folder_service.resolve_bound_authority_for_target.assert_awaited_once_with(
        agent_id="agent-1",
        session_id="child-session",
        runtime_target=authority.target,
    )
    resolver.working_folder_service.resolve_authority.assert_not_awaited()


@pytest.mark.parametrize(
    "reason,status",
    [
        ("unauthenticated", 401),
        ("not_found", 404),
        ("access_denied", 403),
    ],
)
async def test_identity_rejection_never_reads_runner_or_folder(
    reason: Literal["unauthenticated", "not_found", "access_denied"], status: int
) -> None:
    resolver = _resolver()
    resolver.authority_repository.read_snapshot.return_value = (
        RuntimeBrowserIdentityDenied(reason)
    )
    with pytest.raises(RuntimeBrowserRequestError) as captured:
        await _resolve(resolver)
    assert captured.value.status_code == status
    resolver.runtime_coordination.get_connection.assert_not_awaited()
    resolver.working_folder_service.resolve_bound_authority_for_target.assert_not_awaited()


@pytest.mark.parametrize(
    "updates",
    [
        {"desired_state": RuntimeDesiredState.STOPPED},
        {"provider_observed_state": RuntimeProviderObservedState.STOPPED},
        {"provider_observed_generation": 7},
        {"desired_generation": 9},
        {"runner_state": RuntimeRunnerState.STARTING},
        {"runner_generation": 0},
        {"terminal_delete_requested_generation": 8},
        {"agent_id": "different-agent"},
        {"workspace_id": "different-workspace"},
    ],
)
async def test_noncurrent_runtime_cannot_dispatch_or_load_browser(
    updates: dict[str, object],
) -> None:
    resolver = _resolver()
    snapshot = _snapshot()
    assert snapshot.runtime is not None
    resolver.authority_repository.read_snapshot.return_value = dataclasses.replace(
        snapshot, runtime=snapshot.runtime.model_copy(update=updates)
    )
    assert await _resolve(resolver) == RuntimeBrowserUnavailable("runtime_unavailable")
    resolver.runtime_coordination.get_connection.assert_not_awaited()
    resolver.working_folder_service.resolve_bound_authority_for_target.assert_not_awaited()


@pytest.mark.parametrize(
    "snapshot",
    [
        dataclasses.replace(_snapshot(), runtime=None),
        dataclasses.replace(_snapshot(), applied_configuration=None),
        dataclasses.replace(
            _snapshot(),
            agent=_snapshot().agent.model_copy(
                update={
                    "runtime_capability": AgentRuntimeCapability.NONE,
                }
            ),
        ),
    ],
)
async def test_missing_managed_runtime_is_unavailable_without_provisioning(
    snapshot: RuntimeBrowserDurableSnapshot,
) -> None:
    resolver = _resolver()
    resolver.authority_repository.read_snapshot.return_value = snapshot
    assert await _resolve(resolver) == RuntimeBrowserUnavailable("runtime_unavailable")
    resolver.runtime_coordination.get_connection.assert_not_awaited()


@pytest.mark.parametrize(
    "runner",
    [
        None,
        dataclasses.replace(_runner(), generation=6),
        dataclasses.replace(_runner(), expires_at=_NOW),
        dataclasses.replace(
            _runner(),
            metadata={"workspace_path": "/other", "capabilities": ["browser.v1"]},
        ),
        dataclasses.replace(
            _runner(), metadata={"workspace_path": None, "capabilities": ["browser.v1"]}
        ),
    ],
)
async def test_stale_runner_or_missing_workspace_cannot_use_a_server_fallback(
    runner: RuntimeConnectionRecord | None,
) -> None:
    resolver = _resolver()
    resolver.runtime_coordination.get_connection.return_value = runner
    assert await _resolve(resolver) == RuntimeBrowserUnavailable("runtime_unavailable")
    resolver.working_folder_service.resolve_bound_authority_for_target.assert_not_awaited()


@pytest.mark.parametrize("capabilities", [None, [], ["file.v1"], ["browser.v1", 42]])
async def test_browser_capability_is_required_without_allocating_context(
    capabilities: list[str | int] | None,
) -> None:
    resolver = _resolver()
    resolver.runtime_coordination.get_connection.return_value = dataclasses.replace(
        _runner(),
        metadata={"workspace_path": "/runner-reported", "capabilities": capabilities},
    )
    assert await _resolve(resolver) == RuntimeBrowserUnavailable("browser_unavailable")
    resolver.working_folder_service.resolve_bound_authority_for_target.assert_not_awaited()


async def test_pending_or_detached_binding_is_not_bound_by_projection() -> None:
    resolver = _resolver()
    resolver.working_folder_service.resolve_bound_authority_for_target.side_effect = (
        SessionWorkingFolderBindingError("binding_pending")
    )
    assert await _resolve(resolver) == RuntimeBrowserUnavailable(
        "working_folder_unavailable"
    )
    resolver.working_folder_service.resolve_authority.assert_not_awaited()


async def test_retained_applied_configuration_and_live_runner_remain_usable() -> None:
    resolver = _resolver()
    snapshot = _snapshot()
    assert snapshot.runtime is not None
    resolver.authority_repository.read_snapshot.return_value = dataclasses.replace(
        snapshot,
        runtime=snapshot.runtime.model_copy(
            update={
                "configuration_sequence": 3,
                "provider_connection_state": (
                    RuntimeProviderConnectionState.DISCONNECTED
                ),
            }
        ),
    )
    authority = await _resolve(resolver)
    assert isinstance(authority, RuntimeBrowserAuthority)
    assert authority.target.configuration_sequence == 2


@pytest.mark.parametrize(
    "updates",
    [
        {"agent_id": "other-agent"},
        {"agent_runtime_id": "other-runtime"},
        {"runtime_capability_version": 4},
        {"working_folder_path": "/outside/child"},
        {"working_folder_path": "/runner-reported/../outside"},
    ],
)
async def test_inconsistent_binding_cannot_authorize_commands(
    updates: dict[str, object],
) -> None:
    resolver = _resolver()
    folder = (
        resolver.working_folder_service.resolve_bound_authority_for_target.return_value
    )
    resolver.working_folder_service.resolve_bound_authority_for_target.return_value = (
        dataclasses.replace(folder, **updates)
    )
    assert await _resolve(resolver) == RuntimeBrowserUnavailable(
        "working_folder_unavailable"
    )
