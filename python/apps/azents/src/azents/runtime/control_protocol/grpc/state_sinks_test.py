"""Durable Agent Runtime gRPC state sink tests."""

from datetime import UTC, datetime

from azcommon.result import Success
from azents_runtime_control.provider import (
    RuntimeProviderObservedState as SharedProviderState,
)
from azents_runtime_control.provider import RuntimeProviderReport
from azents_runtime_control.runner import RunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntimeFailurePatch
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.runtime.control_protocol.grpc.state_sinks import (
    RuntimeProviderReportRepositorySink,
    RuntimeRunnerStateRepositorySink,
)
from azents.testing.model_selection import make_test_model_selection_dict


async def test_runner_state_sink_rejects_missing_provider_workspace_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner cannot make a Runtime runnable before Provider reports workspace path."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-missing")
    sink = RuntimeRunnerStateRepositorySink(repo, rdb_session_manager)

    await sink.record_runner_state(_report(runtime_id, "/workspace/agent"))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.FAILED
    assert runtime.workspace_path is None
    assert runtime.failure_code == "PROVIDER_WORKSPACE_PATH_MISSING"


async def test_provider_running_report_clears_start_timeout_failure(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Late provider RUNNING report recovers a Control start timeout."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "provider-sink-late-running")
        command = await repo.set_desired_state(
            session,
            runtime_id,
            RuntimeLifecycleCommandType.START,
            RuntimeDesiredState.RUNNING,
        )
        assert command is not None
        await repo.record_runtime_failure(
            session,
            runtime_id,
            AgentRuntimeFailurePatch(
                generation=command.desired_generation,
                code="START_TIMEOUT",
                message="Runtime start timed out",
            ),
        )
    sink = RuntimeProviderReportRepositorySink(repo, rdb_session_manager)

    await sink.record_provider_report(
        RuntimeProviderReport(
            runtime_id=runtime_id,
            provider_id="system-kubernetes",
            provider_generation=1,
            observed_state=SharedProviderState.RUNNING,
            observed_desired_generation=command.desired_generation,
            provider_runtime_id="pod-runtime",
            workspace_path="/workspace/agent",
            reason="ready",
            diagnostic={},
            reported_at=datetime(2026, 5, 25, tzinfo=UTC),
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.provider_observed_state == RuntimeProviderObservedState.RUNNING
    assert runtime.failure_generation is None
    assert runtime.failure_code is None
    assert runtime.failure_message is None


async def test_runner_state_sink_rejects_workspace_mismatch(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner workspace path mismatch becomes an explicit Runtime failure."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-mismatch")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            3,
            workspace_path="/workspace/provider",
        )
    sink = RuntimeRunnerStateRepositorySink(repo, rdb_session_manager)

    await sink.record_runner_state(_report(runtime_id, "/workspace/runner"))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.FAILED
    assert runtime.workspace_path == "/workspace/provider"
    assert runtime.failure_code == "RUNNER_WORKSPACE_PATH_MISMATCH"


async def test_runner_state_sink_preserves_provider_workspace_path(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Matching Runner report records readiness without changing Provider path."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-ready")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            3,
            workspace_path="/workspace/provider",
        )
    sink = RuntimeRunnerStateRepositorySink(repo, rdb_session_manager)

    await sink.record_runner_state(_report(runtime_id, "/workspace/provider"))

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.READY
    assert runtime.workspace_path == "/workspace/provider"
    assert runtime.failure_code is None


async def test_runner_state_sink_rejects_unsupported_runner_state(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Unsupported Runner states become explicit failures."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-unsupported")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            3,
            workspace_path="/workspace/provider",
        )
    sink = RuntimeRunnerStateRepositorySink(repo, rdb_session_manager)

    await sink.record_runner_state(
        _report(runtime_id, "/workspace/provider", state=SharedRunnerState.BUSY)
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.FAILED
    assert runtime.failure_code == "UNSUPPORTED_RUNNER_STATE"


async def test_runner_state_sink_records_runner_stream_closed_as_disconnected(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Runner stream close makes route unavailability visible in durable state."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-disconnected")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            3,
            workspace_path="/workspace/provider",
        )
    sink = RuntimeRunnerStateRepositorySink(repo, rdb_session_manager)

    await sink.record_runner_state(
        _report(
            runtime_id,
            "/workspace/provider",
            state=SharedRunnerState.UNKNOWN,
            diagnostic={"reason": "runner_stream_closed"},
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.DISCONNECTED
    assert runtime.failure_code is None


async def test_runner_state_sink_accepts_latest_report_even_with_lower_generation(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Durable state follows the latest Runner report, not stored generation values."""
    repo = AgentRuntimeRepository()
    async with rdb_session_manager() as session:
        runtime_id = await _create_runtime(session, "runner-sink-lower-generation")
        await repo.record_provider_observed_state(
            session,
            runtime_id,
            RuntimeProviderObservedState.RUNNING,
            3,
            workspace_path="/workspace/provider",
        )
        await repo.record_runner_state(
            session,
            runtime_id,
            RuntimeRunnerState.READY,
            2,
        )
    sink = RuntimeRunnerStateRepositorySink(repo, rdb_session_manager)

    await sink.record_runner_state(
        _report(
            runtime_id,
            "/workspace/provider",
            state=SharedRunnerState.UNKNOWN,
            runner_generation=1,
            diagnostic={"reason": "runner_stream_closed"},
        )
    )

    async with rdb_session_manager() as session:
        runtime = await repo.get_by_id(session, runtime_id)
    assert runtime is not None
    assert runtime.runner_state == RuntimeRunnerState.DISCONNECTED
    assert runtime.runner_generation == 1


async def _create_runtime(session: AsyncSession, slug: str) -> str:
    workspace_repo = WorkspaceRepository()
    result = await workspace_repo.create(
        session,
        WorkspaceCreate(name=f"{slug} workspace", handle=f"{slug}-ws"),
    )
    assert isinstance(result, Success)
    workspace_id = await workspace_repo.resolve_id(session, f"{slug}-ws")
    assert workspace_id is not None

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name=f"{slug} agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model-id",
        ),
    )
    session.add(agent)
    await session.flush()

    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent.id)
    return runtime.id


def _report(
    runtime_id: str,
    workspace_path: str,
    *,
    state: SharedRunnerState = SharedRunnerState.READY,
    runner_generation: int = 1,
    diagnostic: dict[str, str] | None = None,
) -> RunnerStateReport:
    return RunnerStateReport(
        runtime_id=runtime_id,
        runner_id="runner-1",
        runner_generation=runner_generation,
        runner_state=state,
        capabilities=("bash", "file.read"),
        active_operation_ids=(),
        health="ok",
        diagnostic=diagnostic or {},
        workspace_path=workspace_path,
        reported_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
