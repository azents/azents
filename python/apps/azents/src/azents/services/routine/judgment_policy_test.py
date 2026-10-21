"""Shared model failure policy stays inside one Judge settlement and owner."""

import asyncio
import dataclasses
from unittest.mock import AsyncMock

import pytest

from azents.core.routine import RoutineScope
from azents.core.routine_judgment_test import candidate
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.tools import TurnContext
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.engine.events.routine_judgment_test import _observation
from azents.engine.events.types import RoutineJudgmentPayload
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.routine_judgment_context import RoutineJudgmentContext
from azents.engine.routine_judgment_context_test import UnusedFileDownloader, request
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    model_provider_failure,
)
from azents.engine.run.retry_policy import FailedRunRetryPolicy
from azents.repos.routine.judgment_inbox import (
    RoutineJudgmentInboxRepository,
    RoutineJudgmentInput,
    RoutineJudgmentSettlement,
)
from azents.services.routine.judgment import RoutineJudgmentService
from azents.testing.model_selection import make_test_model_selection
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.worker.run.executor_test import _action_execution


def provider_error(status: int) -> ModelProviderFailure:
    return model_provider_failure(
        operation="routine_judgment",
        provider="openai",
        model="primary",
        integration="integration",
        provider_message="Synthetic provider failure",
        status_code=status,
        provider_code="insufficient_quota" if status == 429 else None,
        provider_error_type=None,
        provider_error_param=None,
    )


def context_for(model: str) -> RoutineJudgmentContext:
    selection = make_test_model_selection(model_identifier=model)
    return RoutineJudgmentContext(
        request=request(selection),
        model_selection=selection,
        model_target_label="default",
        turn=TurnContext(
            workspace_id="workspace",
            model=model,
            run_id="host-run",
            session_id="judgment-session",
            publish_event=AsyncMock(),
        ),
        admit_dispatch=AsyncMock(),
        advance_after_quota=AsyncMock(return_value=None),
    )


@pytest.mark.parametrize("status", [401, 403, 400, 500])
async def test_classified_nonquota_failure_uses_shared_retry_budget_without_fallback(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    advance = AsyncMock(return_value=None)
    context = dataclasses.replace(context_for("primary"), advance_after_quota=advance)
    await run_policy_case(
        monkeypatch,
        context,
        [provider_error(status), completed()],
        expected_models=["primary", "primary"],
    )
    advance.assert_not_awaited()


def completed() -> RoutineJudgmentPayload:
    payload = _observation().payload
    assert isinstance(payload, RoutineJudgmentPayload)
    return payload


async def run_policy_case(
    monkeypatch: pytest.MonkeyPatch,
    context: RoutineJudgmentContext,
    attempts: list[object],
    *,
    expected_models: list[str],
) -> None:
    repository = AsyncMock(spec=RoutineJudgmentInboxRepository)
    action = RoutineJudgmentAction(judgment_id="judgment-1")
    repository.capture.return_value = RoutineJudgmentInput(
        action=action, candidates=(candidate(),)
    )
    repository.settle.return_value = RoutineJudgmentSettlement(None, None)
    models: list[str] = []
    remaining = list(attempts)

    async def call_once(*args: object, **kwargs: object) -> RoutineJudgmentPayload:
        current = kwargs["context"]
        assert isinstance(current, RoutineJudgmentContext)
        models.append(current.request.model)
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, RoutineJudgmentPayload)
        return outcome

    monkeypatch.setattr(RoutineJudgmentService, "_call_once", call_once)
    service = RoutineJudgmentService(
        repository=repository,
        sdk_factories=get_model_sdk_factories(),
        watchdog=make_test_model_stream_watchdog(),
        model_file_service=UnusedFileDownloader(),
        retry_policy=FailedRunRetryPolicy(1, 0, 1, 0),
    )
    await service.execute(
        scope=RoutineScope(
            workspace_id="workspace", agent_id="agent", session_id="judgment-session"
        ),
        action=action,
        execution=_action_execution(),
        owner=SessionExecutionOwner(session_id="judgment-session", owner_generation=1),
        prepare_context=AsyncMock(return_value=context),
    )
    assert models == expected_models
    repository.settle.assert_awaited_once()
    assert repository.settle.await_args.kwargs["model"] == expected_models[-1]
    saved = repository.settle.await_args.kwargs["outcome"]
    assert isinstance(saved, RoutineJudgmentPayload)
    last = attempts[-1]
    assert saved.status == (
        last.status if isinstance(last, RoutineJudgmentPayload) else "failed"
    )


async def test_quota_moves_to_next_candidate_before_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = context_for("primary")
    fallback = context_for("fallback")
    advance = AsyncMock(return_value=fallback)
    primary = dataclasses.replace(primary, advance_after_quota=advance)
    await run_policy_case(
        monkeypatch,
        primary,
        [provider_error(429), completed()],
        expected_models=["primary", "fallback"],
    )
    advance.assert_awaited_once()


async def test_exhausted_quota_settles_failure_without_retrying_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    advance = AsyncMock(return_value=None)
    primary = dataclasses.replace(context_for("primary"), advance_after_quota=advance)
    await run_policy_case(
        monkeypatch, primary, [provider_error(429)], expected_models=["primary"]
    )
    advance.assert_awaited_once()


async def test_cancellation_is_never_settled_or_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = AsyncMock(spec=RoutineJudgmentInboxRepository)
    action = RoutineJudgmentAction(judgment_id="judgment-1")
    repository.capture.return_value = RoutineJudgmentInput(action, (candidate(),))
    monkeypatch.setattr(
        RoutineJudgmentService,
        "_call_once",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    service = RoutineJudgmentService(
        repository,
        get_model_sdk_factories(),
        make_test_model_stream_watchdog(),
        UnusedFileDownloader(),
        FailedRunRetryPolicy(1, 0, 1, 0),
    )
    with pytest.raises(asyncio.CancelledError):
        await service.execute(
            scope=RoutineScope("workspace", "agent", "judgment-session"),
            action=action,
            execution=_action_execution(),
            owner=SessionExecutionOwner("judgment-session", 1),
            prepare_context=AsyncMock(return_value=context_for("primary")),
        )
    repository.settle.assert_not_awaited()


async def test_shared_retry_exhaustion_records_one_failed_judgment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_policy_case(
        monkeypatch,
        context_for("primary"),
        [provider_error(500), provider_error(500)],
        expected_models=["primary", "primary"],
    )


async def test_invalid_output_does_not_invent_a_fallback_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = completed().model_copy(
        update={"status": "failed", "decision": None, "error": "Invalid output."}
    )
    await run_policy_case(
        monkeypatch, context_for("primary"), [failed], expected_models=["primary"]
    )
