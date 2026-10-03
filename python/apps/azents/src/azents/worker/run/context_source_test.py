"""Paired context budgets share a single captured source across refresh races."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Literal
from unittest.mock import Mock

import pytest
from azcommon.result import Result, Success

import azents.worker.run.executor as executor_module
from azents.core.agent import AgentModelSelection
from azents.core.enums import AgentRunStatus, LLMProvider
from azents.core.inference_profile import (
    AppliedModelRoute,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.model_operation import (
    ModelOperationKind,
    ModelOperationState,
    build_model_operation,
)
from azents.core.worker_model_profile import (
    ModelCandidateChainExhausted,
    ModelTargetNotFound,
    RequestedProfileSelection,
)
from azents.engine.context.window import resolve_model_input_tokens
from azents.engine.events.engine_events import RunComplete
from azents.engine.run.contracts import RunContext, RunRequest, ToolkitBinding
from azents.engine.run.emit import Emit, ephemeral
from azents.engine.run.input import InvokeInput
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.engine.run.provider_failure import model_provider_failure
from azents.engine.run.resolve import (
    ResolvedModelCandidateRuntime,
)
from azents.engine.run.types import PollMessages
from azents.repos.agent.data import Agent
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelMetadata,
    ContextModelRequest,
)
from azents.repos.worker_executor_model import WorkerExecutorModelOperationRepository
from azents.repos.worker_executor_model_data import FreshModelPreparation
from azents.services.model_metadata import ModelMetadataService
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)
from azents.worker.run import executor_test as fixtures
from azents.worker.run.executor import RunExecutor, RunInputPollResult
from azents.worker.session.supervisor import ToolAdmissionBarrier


def _context(identifier: str, *, main: int, compaction: int) -> CapturedContextSource:
    del identifier
    return CapturedContextSource(
        models=tuple(
            ContextModelMetadata(
                provider=LLMProvider.OPENAI,
                model_identifier=model_id,
                max_input_tokens=context_window,
            )
            for model_id, context_window in (
                ("gpt-main", main),
                ("gpt-main-fallback", main),
                ("gpt-compaction", compaction),
                ("gpt-compaction-fallback", compaction),
            )
        )
    )


def _assert_captured(
    actual: CapturedContextSource,
    expected: CapturedContextSource | None,
) -> None:
    if expected is None:
        assert actual.models == ()
    else:
        assert actual.models
        assert all(model in expected.models for model in actual.models)


def _pair_agent() -> Agent:
    main = make_test_model_selection(model_identifier="gpt-main")
    compaction = make_test_model_selection(model_identifier="gpt-compaction")
    options = [
        *make_test_selectable_model_options(main, label="default"),
        *make_test_selectable_model_options(compaction, label="lightweight"),
    ]
    options[0].candidates.append(
        options[0]
        .candidates[0]
        .model_copy(
            update={
                "model_selection": make_test_model_selection(
                    model_identifier="gpt-main-fallback"
                )
            }
        )
    )
    options[1].candidates.append(
        options[1]
        .candidates[0]
        .model_copy(
            update={
                "model_selection": make_test_model_selection(
                    model_identifier="gpt-compaction-fallback"
                )
            }
        )
    )
    return fixtures._default_agent().model_copy(
        update={
            "model_selection": main,
            "lightweight_model_selection": compaction,
            "selectable_model_options": options,
            "main_model_label": "default",
            "lightweight_model_label": "lightweight",
        }
    )


class _TrackedSelectionOperations(fixtures._CompletedModels):
    """Observe completed operation boundaries without a fake SQL scope."""

    open_operations = 0

    async def prepare_fresh(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        owner_generation: int,
        selected: RequestedProfileSelection,
        override: RequestedProfileSelection | None,
        replace_operation: bool,
    ) -> Result[
        FreshModelPreparation | None, ModelTargetNotFound | ModelCandidateChainExhausted
    ]:
        self.open_operations += 1
        try:
            return await super().prepare_fresh(
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
                owner_generation=owner_generation,
                selected=selected,
                override=override,
                replace_operation=replace_operation,
            )
        finally:
            self.open_operations -= 1


class _RefreshingSourceRepository(ModelMetadataReadRepository):
    """Publish the next source immediately after each authoritative read."""

    def __init__(
        self,
        snapshots: tuple[CapturedContextSource | None, ...],
        selection_transaction_open: Callable[[], bool],
    ) -> None:
        self.snapshots = snapshots
        self.selection_transaction_open = selection_transaction_open
        self.captures = 0

    async def capture_for_context(
        self, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        assert not self.selection_transaction_open()
        selected = self.snapshots[min(self.captures, len(self.snapshots) - 1)]
        self.captures += 1
        if selected is None:
            return CapturedContextSource(models=())
        return CapturedContextSource(
            models=tuple(
                model
                for model in selected.models
                if any(
                    model.provider == request.provider
                    and model.model_identifier == request.model_identifier
                    for request in requests
                )
            )
        )


def _install_sources(
    executor: RunExecutor,
    snapshots: tuple[CapturedContextSource | None, ...],
) -> _RefreshingSourceRepository:
    assert isinstance(executor, fixtures._TestRunExecutor)
    operations = _TrackedSelectionOperations(
        executor.test_agent_state,
        executor.test_session_state,
        executor.test_run_state,
    )
    executor.model_operation_repository = Mock(
        spec=WorkerExecutorModelOperationRepository,
        wraps=operations,
    )
    repository = _RefreshingSourceRepository(
        snapshots, lambda: operations.open_operations != 0
    )
    executor.model_metadata_service = ModelMetadataService(repository=repository)
    return repository


def _input_limit(
    metadata: ModelMetadataService,
    context_source: CapturedContextSource,
    selection: AgentModelSelection,
    *,
    user_cap: int | None,
) -> int:
    window = selection.normalized_capabilities.context_window
    return resolve_model_input_tokens(
        window.default_input_tokens,
        window.max_input_tokens,
        metadata.maximum_input_tokens(
            context_source,
            provider=selection.provider,
            model_identifier=selection.model_identifier,
        ),
        user_cap,
    ).effective_input_tokens


@dataclasses.dataclass(frozen=True)
class _ResolverCalls:
    frozen: list[CapturedContextSource]
    runtime: list[CapturedContextSource]


def _install_resolvers(
    monkeypatch: pytest.MonkeyPatch,
    executor: RunExecutor,
    agent: Agent,
    *,
    concurrent_primary_edit: bool,
) -> _ResolverCalls:
    calls = _ResolverCalls(frozen=[], runtime=[])

    async def request_for(
        selection: AgentModelSelection,
        context_source: CapturedContextSource,
    ) -> RunRequest:
        initial = await fixtures._resolve_success()
        assert isinstance(initial, Success)
        assert isinstance(initial.value, RunRequest)
        return dataclasses.replace(
            initial.value,
            model=selection.model_identifier,
            provider=selection.provider,
            model_capabilities=selection.normalized_capabilities,
            max_input_tokens=_input_limit(
                executor.model_metadata_service,
                context_source,
                selection,
                user_cap=None,
            ),
            compaction_model="provisional-lightweight",
            compaction_max_input_tokens=128_000,
            context_window_tokens=None,
        )

    async def frozen(
        *args: object,
        context_source: CapturedContextSource | None,
        resolved_model_selection: AgentModelSelection,
        **kwargs: object,
    ) -> Success[RunRequest]:
        del args, kwargs
        assert context_source is not None
        if concurrent_primary_edit:
            live_selection = make_test_model_selection(
                model_identifier="concurrent-main-edit"
            )
            agent.model_selection = live_selection
            agent.selectable_model_options[0].candidates[
                0
            ].model_selection = live_selection
            assert resolved_model_selection.model_identifier != (
                live_selection.model_identifier
            )
        calls.frozen.append(context_source)
        return Success(await request_for(resolved_model_selection, context_source))

    async def runtime(
        *,
        context_source: CapturedContextSource | None,
        selection: AgentModelSelection,
        **kwargs: object,
    ) -> Success[ResolvedModelCandidateRuntime]:
        del kwargs
        assert context_source is not None
        calls.runtime.append(context_source)
        return Success(
            ResolvedModelCandidateRuntime(
                provider=selection.provider,
                provider_integration_id=selection.llm_provider_integration_id,
                model=selection.model_identifier,
                credential_kwargs={},
                effective_input_tokens=_input_limit(
                    executor.model_metadata_service,
                    context_source,
                    selection,
                    user_cap=None,
                ),
            )
        )

    monkeypatch.setattr(
        executor_module, "resolve_invoke_input_with_resolved_profile", frozen
    )
    monkeypatch.setattr(executor_module, "resolve_model_candidate_runtime", runtime)
    return calls


@pytest.mark.parametrize("branch", ["primary", "frozen", "fallback"])
@pytest.mark.parametrize("absent", [False, True])
async def test_fresh_pair_does_not_recapture_after_source_publication(
    monkeypatch: pytest.MonkeyPatch,
    branch: Literal["primary", "frozen", "fallback"],
    absent: bool,
) -> None:
    """Every candidate branch and runtime correction sees the identical view."""
    agent = _pair_agent()
    lifecycle = fixtures._SessionLifecycle()
    if branch == "fallback":
        foreground = build_model_operation(
            option=agent.selectable_model_options[0],
            profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=None,
                enabled_execution_options=[],
            ),
            kind=ModelOperationKind.FOREGROUND,
            operation_id="f" * 32,
            recorded_at=datetime.datetime.now(datetime.UTC),
        ).model_copy(update={"cursor": 1})
        lifecycle.run_state.run = dataclasses.replace(
            lifecycle.run_state.run,
            model_operation_state=ModelOperationState(
                foreground=foreground, compaction=None
            ),
        )
    executor = fixtures._executor(session_lifecycle=lifecycle, agent=agent)
    initial = None if absent else _context("A", main=100_000, compaction=64_000)
    repository = _install_sources(
        executor, (initial, _context("B", main=32_000, compaction=200_000))
    )
    calls = _install_resolvers(
        monkeypatch, executor, agent, concurrent_primary_edit=branch == "frozen"
    )
    prepared = await executor._prepare_fresh_main_model_turn(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        invoke_input=InvokeInput(
            agent_id="agent-001", session_id="session-001", messages=[]
        ),
        override=None,
    )
    assert isinstance(prepared, Success)
    assert repository.captures == 1
    assert len(calls.runtime) == 1
    received = calls.frozen + calls.runtime
    assert all(source is received[0] for source in received)
    _assert_captured(received[0], initial)
    expected_main, expected_compaction = (
        (128_000, 128_000) if absent else (100_000, 64_000)
    )
    assert prepared.value.run_request.max_input_tokens == expected_main
    assert prepared.value.run_request.compaction_max_input_tokens == expected_compaction
    assert (
        prepared.value.inference_state.effective_context_window_tokens
        == expected_compaction
    )
    assert (
        prepared.value.inference_state.effective_auto_compaction_threshold_tokens
        == int(expected_compaction * 0.9)
    )
    if branch == "fallback":
        assert len(calls.frozen) == 1
        assert prepared.value.run_request.model == "gpt-main-fallback"
    elif branch == "frozen":
        assert len(calls.frozen) == 1
        assert agent.model_selection.model_identifier == "concurrent-main-edit"
        assert prepared.value.run_request.model == "gpt-main"
    else:
        assert len(calls.frozen) == 1
        assert prepared.value.run_request.model == "gpt-main"


async def test_fresh_known_pair_never_reads_fallback_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared capture preserves the existing saved-maximum short circuit."""
    agent = _pair_agent()
    main_window = (
        agent.selectable_model_options[0]
        .candidates[0]
        .model_selection.normalized_capabilities.context_window
    )
    compaction_window = (
        agent.selectable_model_options[1]
        .candidates[0]
        .model_selection.normalized_capabilities.context_window
    )
    main_window.max_input_tokens = 100_000
    compaction_window.max_input_tokens = 64_000
    executor = fixtures._executor(agent=agent)
    repository = _install_sources(
        executor, (_context("unread", main=32_000, compaction=200_000),)
    )
    calls = _install_resolvers(
        monkeypatch, executor, agent, concurrent_primary_edit=False
    )
    prepared = await executor._prepare_fresh_main_model_turn(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        invoke_input=InvokeInput(
            agent_id="agent-001", session_id="session-001", messages=[]
        ),
        override=None,
    )
    assert isinstance(prepared, Success)
    assert repository.captures == 0
    assert calls.frozen[0].models == ()
    assert calls.runtime[0] is calls.frozen[0]
    assert prepared.value.run_request.max_input_tokens == 100_000
    assert prepared.value.run_request.compaction_max_input_tokens == 64_000


@pytest.mark.parametrize("absent", [False, True])
@pytest.mark.parametrize("threshold", [None, 7_000])
@pytest.mark.parametrize("user_cap", [None, 50_000])
async def test_prepare_compaction_refreshes_the_pair_without_a_derived_user_cap(
    monkeypatch: pytest.MonkeyPatch,
    absent: bool,
    threshold: int | None,
    user_cap: int | None,
) -> None:
    """An old resolved window/threshold is not new explicit user intent."""
    agent = _pair_agent()
    executor = fixtures._executor(agent=agent)
    initial = None if absent else _context("A", main=100_000, compaction=64_000)
    repository = _install_sources(
        executor, (initial, _context("B", main=32_000, compaction=200_000))
    )
    calls = _install_resolvers(
        monkeypatch, executor, agent, concurrent_primary_edit=False
    )
    main = agent.selectable_model_options[0].candidates[0]
    previous = await fixtures._resolve_success()
    assert isinstance(previous, Success)
    assert isinstance(previous.value, RunRequest)
    old_state = SessionInferenceState(
        model_target_label="default",
        model_selection=main.model_selection,
        model_settings=main.settings.model_copy(
            update={"context_window_tokens": user_cap}
        ),
        reasoning_effort=None,
        enabled_execution_options=[],
        effective_context_window_tokens=20_000,
        effective_auto_compaction_threshold_tokens=18_000,
        resolved_at=datetime.datetime.now(datetime.UTC),
        applied_model_route=AppliedModelRoute(
            operation_id="f" * 32,
            operation_kind="foreground",
            candidate_ordinal=1,
            candidate_role="primary",
            provider=main.model_selection.provider,
            llm_provider_integration_id=(
                main.model_selection.llm_provider_integration_id
            ),
            model_identifier=main.model_selection.model_identifier,
            model_display_name=main.model_selection.model_display_name,
            effective_context_window_tokens=20_000,
            effective_auto_compaction_threshold_tokens=18_000,
        ),
    )
    original_state = old_state.model_dump(mode="json")
    current = dataclasses.replace(
        previous.value,
        model=main.model_selection.model_identifier,
        model_capabilities=main.model_selection.normalized_capabilities,
        max_input_tokens=20_000,
        compaction_max_input_tokens=20_000,
        context_window_tokens=20_000,
        auto_compaction_threshold_tokens=threshold or 18_000,
        inference_state=old_state,
    )
    prepared = await executor._prepare_compaction_model_request(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        current_request=current,
    )
    expected_main, expected_compaction = (
        (128_000, 128_000) if absent else (100_000, 64_000)
    )
    if user_cap is not None:
        expected_main = min(expected_main, user_cap)
    expected_effective = min(expected_main, expected_compaction)
    assert repository.captures == 1
    assert len(calls.runtime) == 1
    _assert_captured(calls.runtime[0], initial)
    assert prepared.max_input_tokens == expected_main
    assert prepared.compaction_max_input_tokens == expected_compaction
    assert prepared.context_window_tokens == user_cap
    assert prepared.effective_max_input_tokens == expected_effective
    assert prepared.auto_compaction_threshold_tokens == (
        threshold if threshold is not None else int(expected_effective * 0.9)
    )
    assert old_state.model_dump(mode="json") == original_state
    if threshold is not None:
        assert prepared.inference_state is old_state
    else:
        refreshed_state = prepared.inference_state
        assert refreshed_state is not None
        assert refreshed_state is not old_state
        assert refreshed_state.model_selection is old_state.model_selection
        assert refreshed_state.model_settings is old_state.model_settings
        assert refreshed_state.resolved_at == old_state.resolved_at
        assert refreshed_state.effective_context_window_tokens == expected_effective
        assert refreshed_state.effective_auto_compaction_threshold_tokens == int(
            expected_effective * 0.9
        )
        route = refreshed_state.applied_model_route
        assert route is not None
        assert route is not old_state.applied_model_route
        assert route.operation_id == "f" * 32
        assert route.effective_context_window_tokens == expected_effective
        assert route.effective_auto_compaction_threshold_tokens == int(
            expected_effective * 0.9
        )


async def test_prepare_compaction_preserves_explicit_no_state_cap_and_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _pair_agent()
    executor = fixtures._executor(agent=agent)
    repository = _install_sources(
        executor,
        (
            _context("A", main=100_000, compaction=64_000),
            _context("B", main=32_000, compaction=200_000),
        ),
    )
    _install_resolvers(monkeypatch, executor, agent, concurrent_primary_edit=False)
    previous = await fixtures._resolve_success()
    assert isinstance(previous, Success)
    assert isinstance(previous.value, RunRequest)
    current = dataclasses.replace(
        previous.value,
        model="gpt-main",
        max_input_tokens=20_000,
        context_window_tokens=50_000,
        auto_compaction_threshold_tokens=7_000,
        inference_state=None,
    )
    prepared = await executor._prepare_compaction_model_request(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        current_request=current,
    )
    assert repository.captures == 1
    assert prepared.max_input_tokens == 50_000
    assert prepared.compaction_max_input_tokens == 64_000
    assert prepared.effective_max_input_tokens == 50_000
    assert prepared.context_window_tokens == 50_000
    assert prepared.auto_compaction_threshold_tokens == 7_000


class _CompactionQuotaEngine(fixtures._Engine):
    def __init__(
        self,
        *,
        quota_failures: int,
        prepare_before_quota: bool,
    ) -> None:
        self.requests: list[RunRequest] = []
        self.prepared: list[RunRequest] = []
        self.quota_failures = quota_failures
        self.prepare_before_quota = prepare_before_quota

    def run(
        self,
        request: RunRequest,
        context: object,
        *,
        poll_messages: PollMessages | None = None,
        check_stop: object = None,
    ) -> AsyncIterator[Emit]:
        del poll_messages, check_stop
        assert isinstance(context, RunContext)
        self.requests.append(request)
        compaction_model = request.compaction_model
        assert compaction_model is not None

        async def events() -> AsyncIterator[Emit]:
            if self.prepare_before_quota and len(self.requests) == 1:
                prepare_compaction = context.prepare_compaction_request
                assert prepare_compaction is not None
                self.prepared.append(await prepare_compaction(request))
            if len(self.requests) <= self.quota_failures:
                raise model_provider_failure(
                    operation="compaction",
                    provider=request.provider.value,
                    model=compaction_model,
                    integration=request.compaction_provider_integration_id,
                    provider_message="Quota exceeded.",
                    status_code=402,
                    provider_code="billing_limit",
                    provider_error_type="billing_error",
                    provider_error_param=None,
                )
            yield ephemeral(RunComplete(run_id=context.run_id))

        return events()


@pytest.mark.parametrize("absent", [False, True])
async def test_compaction_quota_transition_recomputes_both_limits_from_one_view(
    monkeypatch: pytest.MonkeyPatch,
    absent: bool,
) -> None:
    agent = _pair_agent()
    engine = _CompactionQuotaEngine(quota_failures=1, prepare_before_quota=False)
    lifecycle = fixtures._SessionLifecycle()
    executor = fixtures._executor(
        session_lifecycle=lifecycle,
        engine=engine,
        agent=agent,
        failed_run_max_retries=0,
    )
    old = _context("old", main=64_000, compaction=128_000)
    new = None if absent else _context("A", main=100_000, compaction=80_000)
    repository = _install_sources(
        executor, (old, new, _context("B", main=32_000, compaction=200_000))
    )
    calls = _install_resolvers(
        monkeypatch, executor, agent, concurrent_primary_edit=False
    )

    async def resolve_tools(*args: object, **kwargs: object) -> list[ToolkitBinding]:
        del args, kwargs
        return []

    async def poll_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            user_messages=[],
            requested_inference_profile=None,
            promoted_event_ids=[],
            has_actionable_work=True,
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
        )

    monkeypatch.setattr(executor_module, "resolve_agent_tools", resolve_tools)
    monkeypatch.setattr(executor, "poll_run_inputs", poll_inputs)
    result = await executor.execute(
        fixtures._message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=fixtures._noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )
    assert result.terminal_run_status is AgentRunStatus.COMPLETED
    assert repository.captures == 2
    assert len(calls.runtime) == 2
    _assert_captured(calls.runtime[0], old)
    _assert_captured(calls.runtime[1], new)
    assert len(engine.requests) == 2
    refreshed = engine.requests[1]
    expected_main, expected_compaction = (
        (128_000, 128_000) if absent else (100_000, 80_000)
    )
    assert refreshed.compaction_model == "gpt-compaction-fallback"
    assert refreshed.max_input_tokens == expected_main
    assert refreshed.compaction_max_input_tokens == expected_compaction
    assert refreshed.context_window_tokens is None
    assert refreshed.effective_max_input_tokens == expected_compaction
    assert refreshed.auto_compaction_threshold_tokens == int(expected_compaction * 0.9)
    assert lifecycle.retry_states == []


@pytest.mark.parametrize("explicit_threshold", [None, 7_000])
async def test_successive_prepare_transitions_keep_threshold_provenance(
    monkeypatch: pytest.MonkeyPatch,
    explicit_threshold: int | None,
) -> None:
    """An inherited 18k becomes 72k then 28.8k, never a new explicit cap."""
    agent = _pair_agent()
    executor = fixtures._executor(agent=agent)
    repository = _install_sources(
        executor,
        (
            _context("A", main=100_000, compaction=80_000),
            _context("B", main=40_000, compaction=32_000),
            _context("unread", main=900_000, compaction=900_000),
        ),
    )
    calls = _install_resolvers(
        monkeypatch, executor, agent, concurrent_primary_edit=False
    )
    previous = await fixtures._resolve_success()
    assert isinstance(previous, Success)
    assert isinstance(previous.value, RunRequest)
    main = agent.selectable_model_options[0].candidates[0]
    original_state = SessionInferenceState(
        model_target_label="default",
        model_selection=main.model_selection,
        model_settings=main.settings,
        reasoning_effort=None,
        enabled_execution_options=[],
        effective_context_window_tokens=20_000,
        effective_auto_compaction_threshold_tokens=18_000,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    original_values = original_state.model_dump(mode="json")
    current = dataclasses.replace(
        previous.value,
        model="gpt-main",
        max_input_tokens=20_000,
        compaction_max_input_tokens=20_000,
        context_window_tokens=20_000,
        auto_compaction_threshold_tokens=explicit_threshold or 18_000,
        inference_state=original_state,
    )
    first = await executor._prepare_compaction_model_request(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        current_request=current,
    )
    second = await executor._prepare_compaction_model_request(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        current_request=first,
    )
    assert repository.captures == 2
    assert len(calls.runtime) == 2
    assert first.max_input_tokens == 100_000
    assert first.compaction_max_input_tokens == 80_000
    assert second.max_input_tokens == 40_000
    assert second.compaction_max_input_tokens == 32_000
    assert first.auto_compaction_threshold_tokens == (
        explicit_threshold if explicit_threshold is not None else 72_000
    )
    assert second.auto_compaction_threshold_tokens == (
        explicit_threshold if explicit_threshold is not None else 28_800
    )
    assert original_state.model_dump(mode="json") == original_values
    if explicit_threshold is None:
        assert first.inference_state is not original_state
        assert second.inference_state is not first.inference_state
        assert second.inference_state is not None
        assert (
            second.inference_state.effective_auto_compaction_threshold_tokens == 28_800
        )
        assert second.inference_state.model_settings is original_state.model_settings
    else:
        assert first.inference_state is second.inference_state is original_state


async def test_no_state_automatic_threshold_keeps_derive_at_use_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _pair_agent()
    executor = fixtures._executor(agent=agent)
    repository = _install_sources(
        executor,
        (
            _context("A", main=100_000, compaction=80_000),
            _context("B", main=40_000, compaction=32_000),
        ),
    )
    _install_resolvers(monkeypatch, executor, agent, concurrent_primary_edit=False)
    previous = await fixtures._resolve_success()
    assert isinstance(previous, Success)
    assert isinstance(previous.value, RunRequest)
    current = dataclasses.replace(
        previous.value,
        model="gpt-main",
        inference_state=None,
        context_window_tokens=None,
        auto_compaction_threshold_tokens=None,
    )
    first = await executor._prepare_compaction_model_request(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        current_request=current,
    )
    second = await executor._prepare_compaction_model_request(
        agent_id="agent-001",
        session_id="session-001",
        run_id="run-001",
        owner_generation=1,
        current_request=first,
    )
    assert repository.captures == 2
    assert first.effective_max_input_tokens == 80_000
    assert second.effective_max_input_tokens == 32_000
    assert first.auto_compaction_threshold_tokens is None
    assert second.auto_compaction_threshold_tokens is None


@pytest.mark.parametrize("prepare_before_quota", [False, True])
async def test_two_compaction_quota_transitions_use_current_derived_provenance(
    monkeypatch: pytest.MonkeyPatch,
    prepare_before_quota: bool,
) -> None:
    """Sequential quota and prepare-to-quota paths keep each pair coherent."""
    agent = _pair_agent()
    option = agent.selectable_model_options[1]
    option.candidates.append(
        option.candidates[1].model_copy(
            update={
                "model_selection": make_test_model_selection(
                    model_identifier="gpt-compaction"
                )
            }
        )
    )
    # Distinct integrations make the third candidate a different quota identity.
    option.candidates[2].model_selection = make_test_model_selection(
        model_identifier="gpt-compaction", integration_id="third-integration"
    )
    engine = _CompactionQuotaEngine(
        quota_failures=2, prepare_before_quota=prepare_before_quota
    )
    lifecycle = fixtures._SessionLifecycle()
    executor = fixtures._executor(
        session_lifecycle=lifecycle,
        engine=engine,
        agent=agent,
        failed_run_max_retries=0,
    )
    old = _context("old", main=64_000, compaction=128_000)
    first = _context("A", main=100_000, compaction=80_000)
    second = _context("B", main=40_000, compaction=32_000)
    sources = (
        (old, first, first, second) if prepare_before_quota else (old, first, second)
    )
    repository = _install_sources(
        executor, (*sources, _context("unread", main=900_000, compaction=900_000))
    )
    calls = _install_resolvers(
        monkeypatch, executor, agent, concurrent_primary_edit=False
    )

    async def resolve_tools(*args: object, **kwargs: object) -> list[ToolkitBinding]:
        del args, kwargs
        return []

    async def poll_inputs(*args: object, **kwargs: object) -> RunInputPollResult:
        del args, kwargs
        return RunInputPollResult(
            user_messages=[],
            requested_inference_profile=None,
            promoted_event_ids=[],
            has_actionable_work=True,
            context_invalidated=False,
            complete_run=False,
            suppress_parent_result=False,
        )

    monkeypatch.setattr(executor_module, "resolve_agent_tools", resolve_tools)
    monkeypatch.setattr(executor, "poll_run_inputs", poll_inputs)
    result = await executor.execute(
        fixtures._message(),
        poll_fn=None,
        check_stop=None,
        prepare_toolkits=None,
        shutdown_event=asyncio.Event(),
        dispatch_event=fixtures._noop_dispatch_event,
        owner_generation=1,
        tool_admission_barrier=ToolAdmissionBarrier(),
        model_transport_state=InMemoryModelTransportState(websocket_enabled=False),
    )
    assert result.terminal_run_status is AgentRunStatus.COMPLETED
    assert repository.captures == len(sources)
    assert len(engine.requests) == 3
    assert engine.requests[1].max_input_tokens == 100_000
    assert engine.requests[1].compaction_max_input_tokens == 80_000
    assert engine.requests[1].auto_compaction_threshold_tokens == 72_000
    assert engine.requests[2].max_input_tokens == 40_000
    assert engine.requests[2].compaction_max_input_tokens == 32_000
    assert engine.requests[2].auto_compaction_threshold_tokens == 28_800
    _assert_captured(calls.runtime[-2], first)
    _assert_captured(calls.runtime[-1], second)
    assert engine.requests[0].inference_state is not None
    assert engine.requests[0].inference_state.effective_context_window_tokens == 64_000
    assert lifecycle.retry_states == []
    if prepare_before_quota:
        assert len(engine.prepared) == 1
        assert engine.prepared[0].max_input_tokens == 100_000
        assert engine.prepared[0].compaction_max_input_tokens == 80_000
        assert engine.prepared[0].auto_compaction_threshold_tokens == 72_000


async def test_compaction_context_uses_saved_semantic_model_not_dispatch_encoding() -> (
    None
):
    """Source identity remains independent of the current transport encoding."""
    executor = fixtures._executor()
    selection = make_test_model_selection(
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier="anthropic.claude-fixture-v1:0",
    )
    previous = await fixtures._resolve_success()
    assert isinstance(previous, Success)
    assert isinstance(previous.value, RunRequest)
    settings = _pair_agent().selectable_model_options[0].candidates[0].settings
    state = SessionInferenceState(
        model_target_label="default",
        model_selection=selection,
        model_settings=settings,
        reasoning_effort=None,
        enabled_execution_options=[],
        effective_context_window_tokens=20_000,
        effective_auto_compaction_threshold_tokens=18_000,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    source = CapturedContextSource(
        models=(
            ContextModelMetadata(
                provider=LLMProvider.AWS_BEDROCK,
                model_identifier="anthropic.claude-fixture-v1:0",
                max_input_tokens=100_000,
            ),
        )
    )
    request = dataclasses.replace(
        previous.value,
        provider=selection.provider,
        model="bedrock/converse/anthropic.claude-fixture-v1:0",
        model_capabilities=selection.normalized_capabilities,
        max_input_tokens=20_000,
        compaction_max_input_tokens=80_000,
        context_window_tokens=20_000,
        auto_compaction_threshold_tokens=18_000,
        inference_state=state,
    )
    refreshed = executor._with_shared_compaction_context(request, context_source=source)
    assert refreshed.max_input_tokens == 100_000
    assert refreshed.effective_max_input_tokens == 80_000
    assert refreshed.auto_compaction_threshold_tokens == 72_000
    assert refreshed.model == request.model
    assert state.model_selection.model_identifier == "anthropic.claude-fixture-v1:0"
    assert state.effective_context_window_tokens == 20_000
