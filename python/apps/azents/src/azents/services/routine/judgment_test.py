"""The hosted judgment call keeps provider I/O outside database transactions."""

import asyncio
import dataclasses
import datetime
import json
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal
from unittest.mock import AsyncMock

import httpx2
import pytest
from openai import AsyncOpenAI

from azents.core.enums import EventKind
from azents.core.inference_profile import InferenceProfileFailureCode
from azents.core.llm_catalog import ModelCapabilities
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.core.routine import ROUTINE_TICK_INTERVAL, RoutineUnavailable
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
)
from azents.core.tools import TurnContext
from azents.core.worker_model_profile import (
    ProfileResolutionFailure,
    ProfileResolutionRuntimeError,
)
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.engine.events.openai_responses import (
    OpenAIResponsesClient,
    OpenAISDKResponsesClient,
)
from azents.engine.events.types import RoutineJudgmentPayload, UserMessagePayload
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.routine_judgment_context import RoutineJudgmentContext
from azents.engine.routine_judgment_context_test import UnusedFileDownloader, request
from azents.engine.routine_judgment_test import history
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.retry_policy import FailedRunRetryPolicy
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution.data import EventCreate
from azents.repos.routine.judgment_inbox_test import promote, repository, subject
from azents.repos.routine.persistence_test import _operations
from azents.services.mailbox import TurnEffect
from azents.services.mailbox_test import _mailbox_item_service
from azents.services.routine.judgment import RoutineJudgmentService
from azents.testing.model_selection import make_test_model_selection
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.provider_native_envelopes import core_native_response


@pytest.mark.parametrize(
    "kind",
    [
        "action",
        "no_action",
        "invalid",
        "provider_failure",
        "empty",
        "closed_admission",
        "unsupported_structured",
        "profile_failure",
        "stale_context",
        "unexpected_preparation",
        "input_during_call",
    ],
)
async def test_hosted_judgment_dispatch_and_settlement_use_existing_inbox(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    kind: Literal[
        "action",
        "no_action",
        "invalid",
        "provider_failure",
        "empty",
        "closed_admission",
        "unsupported_structured",
        "profile_failure",
        "stale_context",
        "unexpected_preparation",
        "input_during_call",
    ],
) -> None:
    act = kind in {"action", "input_during_call"}
    open_scopes = 0

    @asynccontextmanager
    async def observed_session() -> AsyncGenerator[WriteSession, None]:
        nonlocal open_scopes
        async with rdb_session_manager() as session:
            open_scopes += 1
            try:
                yield session
            finally:
                open_scopes -= 1

    scope = await subject(observed_session)
    repo = repository(observed_session)
    admitted = await repo.admit_tick(
        scope=scope, now=datetime.datetime.now(datetime.UTC)
    )
    assert admitted is not None
    async with observed_session() as session:
        initial_check = await repo.states.get_check(session, scope=scope)
        assert initial_check is not None
    action = RoutineJudgmentAction.model_validate(admitted.mailbox_item.action)
    execution = await promote(
        observed_session, scope=scope, action=action, buffer_id=admitted.mailbox_item.id
    )
    async with observed_session() as session:
        definitions = await repo.definitions.list_for_session(session, scope=scope)
        await repo.events.append(
            session,
            EventCreate(
                session_id=scope.session_id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(
                    sender_user_id=None,
                    content="Obsolete history before the current head.",
                ).model_dump(mode="json"),
            ),
        )
        for index, event in enumerate(history()):
            appended = await repo.events.append(
                session,
                EventCreate(
                    session_id=scope.session_id,
                    kind=event.kind,
                    payload=event.payload.model_dump(mode="json"),
                ),
            )
            if index == 0:
                target = await session.write_session.get(
                    RDBAgentSession, scope.session_id
                )
                assert target is not None
                target.model_input_head_event_id = appended.id
    if kind == "empty":
        await _operations(observed_session).delete(
            scope=scope, slug=definitions[0].slug, owner=None
        )
    wire: list[bytes] = []
    clients: list[httpx2.AsyncClient] = []
    reached = asyncio.Event()
    release = asyncio.Event()

    async def respond(native_request: httpx2.Request) -> httpx2.Response:
        assert open_scopes == 0
        wire.append(native_request.content)
        if kind == "input_during_call":
            reached.set()
            await release.wait()
        if kind == "provider_failure":
            return httpx2.Response(
                503,
                json={
                    "error": {
                        "message": "Synthetic provider unavailable",
                        "type": "server_error",
                    }
                },
            )
        native = core_native_response(
            protocol="responses",
            model="fixture",
            text="invalid Structured output"
            if kind == "invalid"
            else json.dumps(
                {"decisions": [{"routine_id": definitions[0].id, "act": act}]}
            ),
        )
        return httpx2.Response(
            200, headers={"content-type": native.content_type}, content=native.body
        )

    def openai_factory(*, config: OpenAIResponsesClientConfig) -> OpenAIResponsesClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
        clients.append(client)
        return OpenAISDKResponsesClient(
            AsyncOpenAI(
                api_key="synthetic-unused",
                base_url="https://fixture.invalid/v1",
                max_retries=0,
                http_client=client,
            ),
            websocket_headers=config.default_headers,
        )

    selection = make_test_model_selection(model_identifier="fixture").model_copy(
        update={
            "normalized_capabilities": ModelCapabilities(
                structured_response=kind != "unsupported_structured"
            )
        }
    )
    owner = SessionExecutionOwner(session_id=scope.session_id, owner_generation=0)

    async def admit_dispatch() -> None:
        assert open_scopes == 0
        if kind == "closed_admission":
            raise asyncio.CancelledError("Ordinary dispatch admission closed.")

    async def prepare_context() -> RoutineJudgmentContext:
        assert open_scopes == 0
        assert kind != "empty"
        if kind == "profile_failure":
            raise ProfileResolutionRuntimeError(
                ProfileResolutionFailure(
                    code=InferenceProfileFailureCode.MODEL_TARGET_NOT_FOUND,
                    message="The selected model is no longer available.",
                )
            )
        if kind == "unexpected_preparation":
            raise ValueError("Unexpected fixture preparation defect.")
        return RoutineJudgmentContext(
            request=dataclasses.replace(
                request(selection),
                session_id=scope.session_id,
                agent_id=scope.agent_id,
                workspace_id=scope.workspace_id,
                toolkits=[],
            ),
            model_selection=selection,
            model_target_label="default",
            admit_dispatch=admit_dispatch,
            advance_after_quota=AsyncMock(return_value=None),
            turn=TurnContext(
                workspace_id=scope.workspace_id,
                model="fixture",
                run_id="host-run",
                publish_event=publish,
                session_id=scope.session_id,
                resource_authority=SessionResourceAuthority(
                    workspace_id=scope.workspace_id,
                    agent_id=scope.agent_id,
                    session_id=scope.session_id,
                    root_session_id=scope.session_id,
                    run_id="host-run",
                    run_index=1,
                    owner_generation=99 if kind == "stale_context" else 0,
                ),
            ),
        )

    service = RoutineJudgmentService(
        repository=repo,
        sdk_factories=dataclasses.replace(
            get_model_sdk_factories(), openai_responses=openai_factory
        ),
        watchdog=make_test_model_stream_watchdog(),
        model_file_service=UnusedFileDownloader(),
        retry_policy=FailedRunRetryPolicy(0, 0, 1, 0),
    )
    request_started_at = datetime.datetime.now(datetime.UTC)
    call = service.execute(
        scope=scope,
        action=action,
        execution=execution,
        owner=owner,
        prepare_context=prepare_context,
    )
    if kind in {"stale_context", "unexpected_preparation"}:
        with pytest.raises(
            RoutineUnavailable if kind == "stale_context" else ValueError
        ):
            await call
        assert wire == [] and clients == []
        async with observed_session() as session:
            check = await repo.states.get_check(session, scope=scope)
            assert check is not None
            assert check.state.queued_judgment_id == action.judgment_id
        await service.cancel(execution=execution, owner=owner)
        return
    if kind == "closed_admission":
        with pytest.raises(asyncio.CancelledError):
            await call
        assert wire == [] and clients == []
        await service.cancel(execution=execution, owner=owner)
        async with observed_session() as session:
            check = await repo.states.get_check(session, scope=scope)
            assert check is not None and check.state.source_inputs
            assert check.state.queued_judgment_id is None
            assert check.state.last_action_at is None
        return
    if kind == "input_during_call":
        async with asyncio.timeout(10), asyncio.TaskGroup() as tasks:
            running = tasks.create_task(call)
            await reached.wait()
            assert not running.done()
            async with observed_session() as session:
                later_input = await repo.events.append(
                    session,
                    EventCreate(
                        session_id=scope.session_id,
                        kind=EventKind.USER_MESSAGE,
                        payload=UserMessagePayload(
                            sender_user_id=None,
                            content="Input received during the held judgment.",
                        ).model_dump(mode="json"),
                    ),
                )
            assert (
                await repo.admit_tick(
                    scope=scope,
                    now=datetime.datetime.now(datetime.UTC) + ROUTINE_TICK_INTERVAL,
                )
                is None
            )
            assert not running.done() and len(wire) == 1
            release.set()
        settled = running.result()
        assert settled.admission is not None
        async with observed_session() as session:
            retained = await repo.events.get_by_id(session, event_id=later_input.id)
            assert retained is not None and retained.payload == later_input.payload
        assert b"Input received during the held judgment." not in wire[0]
    else:
        settled = await call
    if kind == "empty":
        assert wire == [] and clients == []
        assert settled.observation is None and settled.admission is None
        async with observed_session() as session:
            assert (
                await repo.actions.get_by_id(session, action_execution_id=execution.id)
                is None
            )
        return
    preparation_failed = kind in {"unsupported_structured", "profile_failure"}
    assert len(wire) == (0 if preparation_failed else 1)
    if preparation_failed:
        assert clients == []
    assert all(client.is_closed for client in clients)
    assert settled.observation is not None
    payload = settled.observation.payload
    assert isinstance(payload, RoutineJudgmentPayload)
    assert payload.status == (
        "failed"
        if kind in {"invalid", "provider_failure"} or preparation_failed
        else "completed"
    )
    if kind == "provider_failure" or preparation_failed:
        assert payload.usage is None
    else:
        assert payload.usage is not None and payload.usage.total_tokens > 0
    assert (settled.admission is not None) == act
    assert "run_id" not in payload.model_dump()
    if wire:
        time_match = re.search(rb"Current time: ([0-9T:.+-]+)", wire[0])
        assert time_match is not None
        current_time = datetime.datetime.fromisoformat(time_match[1].decode())
        assert current_time.utcoffset() == datetime.timedelta(0)
        assert request_started_at <= current_time <= datetime.datetime.now(datetime.UTC)
        assert b'"tools"' not in wire[0]
        assert b"Watch official launch announcements." in wire[0]
        assert b"Only notify about confirmed news." in wire[0]
        assert b"Obsolete history before the current head." not in wire[0]
    async with observed_session() as session:
        check = await repo.states.get_check(session, scope=scope)
        assert check is not None and check.state.queued_judgment_id is None
        assert bool(check.state.source_inputs) == (
            payload.status == "failed" or kind == "input_during_call"
        )
        assert (check.state.last_action_at is not None) == act
        assert (
            await repo.actions.get_by_id(session, action_execution_id=execution.id)
            is None
        )
        if preparation_failed:
            assert check.state.source_inputs == initial_check.state.source_inputs
            assert check.state.last_action_at == initial_check.state.last_action_at
            if kind == "profile_failure":
                assert settled.observation.provider is None
                assert settled.observation.model is None
            else:
                assert settled.observation.provider == selection.provider.value
                assert settled.observation.model == selection.model_identifier
    if preparation_failed:
        next_tick = await repo.admit_tick(
            scope=scope,
            now=datetime.datetime.now(datetime.UTC) + ROUTINE_TICK_INTERVAL,
        )
        assert next_tick is not None and next_tick.created
        next_action = RoutineJudgmentAction.model_validate(
            next_tick.mailbox_item.action
        )
        assert next_action.judgment_id != action.judgment_id


async def test_real_mailbox_promotes_judgment_without_inference_preparation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    repo = repository(rdb_session_manager)
    admission = await repo.admit_tick(
        scope=scope, now=datetime.datetime.now(datetime.UTC)
    )
    assert admission is not None
    mailbox = _mailbox_item_service(rdb_session_manager)
    pending = await mailbox.peek_pending_inference_profile(scope.session_id)
    assert pending.exists and not pending.requires_inference
    assert pending.requested_inference_profile is None
    promoted = await mailbox.flush_session_mailbox_items(
        session_id=scope.session_id,
        owner_generation=0,
        model=None,
        required_inference_profile=None,
        expected_buffer_id=admission.mailbox_item.id,
        prepared_inference_state=None,
        profile_resolution_failure=None,
        active_run_id=None,
        include_action_messages=True,
    )
    assert promoted.turn_effect is TurnEffect.NEUTRAL
    assert promoted.user_messages == [] and promoted.events == []
    assert promoted.deleted_buffer_ids == [admission.mailbox_item.id]
    assert promoted.operation_action is not None
    assert isinstance(promoted.operation_action.action, RoutineJudgmentAction)
    assert promoted.operation_action.execution is not None
    assert promoted.operation_action.execution.owner_generation == 0


async def publish(event: PublishedEvent) -> None:
    raise AssertionError("Judgment does not emit ordinary turn events.")
