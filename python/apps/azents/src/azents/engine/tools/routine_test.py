"""Real Routine tool invocation with ordinary Run and committed database state."""

import dataclasses
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from azents.core.enums import AgentRunStatus, EventKind
from azents.core.routine import RoutineDeliveryStatus, RoutineObjectiveOutcome
from azents.core.tools import TurnContext
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.routine import RoutineToolkit
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.routine.completion_test import Fixture, fixture, work
from azents.repos.routine.notification import RoutineNotificationOperations
from azents.repos.routine.persistence_test import _operations
from azents.repos.session_primary_channel import SessionPrimaryChannelRepository
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.routine.notification import RoutineNotificationService


def _parse(value: str | FunctionToolResult) -> dict[str, Any]:
    """Prove that Routine tools return text without a terminal Run command."""
    assert isinstance(value, str)
    return json.loads(value)


def _toolkit(manager: SessionManager[WriteSession], f: Fixture) -> RoutineToolkit:
    return RoutineToolkit(
        operations=_operations(manager),
        completion=f.repository,
        notifications=RoutineNotificationService(
            operations=RoutineNotificationOperations(
                session_manager=manager,
                primary=SessionPrimaryChannelRepository(),
                channels=AsyncMock(spec=ExternalChannelWorkRepository),
                events=EventTranscriptRepository(),
                execution_authority=f.repository.execution_authority,
            ),
            completion=f.repository,
            channels=AsyncMock(spec=ExternalChannelActionService),
        ),
        scope=f.scope,
    )


def _context(f: Fixture, publish: AsyncMock) -> TurnContext:
    return TurnContext(
        workspace_id=f.scope.workspace_id,
        model="fixture",
        run_id=f.authority.run_id,
        run_index=f.authority.run_index,
        session_id=f.scope.session_id,
        publish_event=publish,
        resource_authority=f.authority,
    )


@pytest.mark.parametrize("notify", [False, True])
async def test_result_tool_settles_one_item_without_terminalizing_host(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    notify: bool,
) -> None:
    f = await fixture(rdb_session_manager)
    toolkit = _toolkit(rdb_session_manager, f)
    publish = AsyncMock()
    toolkit.bind_execution_owner(f.authority.execution_owner)
    tools = {
        t.spec.name: t
        for t in (await toolkit.update_context(_context(f, publish))).tools
    }
    item = f.states[0]
    args = {
        "slug": item.context.candidate.slug,
        "execution_id": item.context.execution_id,
        "work": work(notify=notify, outcome=RoutineObjectiveOutcome.FAILED).model_dump(
            mode="json"
        ),
    }
    result = await tools["record_routine_result"].handler(json.dumps(args))
    assert isinstance(result, str)
    output = _parse(result)
    assert output["created"] is True
    assert output["execution"]["phase"] == "completed"
    assert output["execution"]["delivery_status"] == (
        RoutineDeliveryStatus.DELIVERED
        if notify
        else RoutineDeliveryStatus.NOT_REQUESTED
    )
    assert (
        len(await f.repository.list_started(scope=f.scope, authority=f.authority)) == 1
    )
    async with rdb_session_manager() as session:
        run = await f.repository.runs.get_by_id(session, f.authority.run_id)
        assert run is not None and run.status is AgentRunStatus.RUNNING
    if notify:
        event = publish.call_args.args[0]
        assert event.kind is EventKind.ROUTINE_NOTIFICATION
        assert event.payload.content == args["work"]["message"]
        # The notification Event and saved completion must already be committed.
        async with rdb_session_manager() as session:
            assert (
                await EventTranscriptRepository().get_by_external_id(
                    session,
                    f.scope.session_id,
                    f"routine-notification:{item.context.execution_id}",
                )
                is not None
            )
    else:
        publish.assert_not_called()
    repeated = await tools["record_routine_result"].handler(json.dumps(args))
    assert _parse(repeated)["created"] is False
    assert publish.call_count == int(notify)


async def test_create_list_inspect_keep_exact_content_without_checking_immediately(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    toolkit = _toolkit(rdb_session_manager, f)
    toolkit.bind_execution_owner(f.authority.execution_owner)
    tools = {
        tool.spec.name: tool
        for tool in (await toolkit.update_context(_context(f, AsyncMock()))).tools
    }
    content = {
        "title": "Exact title",
        "objective": "  Preserve this exact objective.  ",
        "sources": [],
    }
    created = _parse(await tools["create_routine"].handler(json.dumps(content)))
    assert created["content"] == content
    listed = _parse(await tools["list_routines"].handler("{}"))
    assert len(listed["routines"]) == 3
    inspected = _parse(
        await tools["inspect_routine"].handler(
            json.dumps(
                {
                    "slug": created["slug"],
                    "record_limit": 10,
                }
            )
        )
    )
    assert inspected["routine"]["definition"]["content"] == content
    assert inspected["routine"]["records"] == []
    async with rdb_session_manager() as session:
        check = await f.repository.states.get_check(session, scope=f.scope)
        assert check is not None and check.state.queued_judgment_id is None
        assert (
            len(await f.repository.states.list_executions(session, scope=f.scope)) == 2
        )


async def test_management_tools_compare_exact_content_and_preserve_admitted_context(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    toolkit = _toolkit(rdb_session_manager, f)
    toolkit.bind_execution_owner(f.authority.execution_owner)
    tools = {
        t.spec.name: t
        for t in (await toolkit.update_context(_context(f, AsyncMock()))).tools
    }
    definition = f.definitions[0]
    update = {
        "slug": definition.slug,
        "expected": definition.content.model_dump(mode="json"),
        "changes": {"objective": "Changed future objective."},
    }
    result = _parse(await tools["update_routine"].handler(json.dumps(update)))
    assert result["content"]["objective"] == "Changed future objective."
    with pytest.raises(FunctionToolError, match="content changed"):
        await tools["update_routine"].handler(json.dumps(update))
    await tools["delete_routine"].handler(json.dumps({"slug": definition.slug}))
    context = _parse(
        await tools["read_routine_context"].handler(
            json.dumps(
                {
                    "slug": definition.slug,
                    "execution_id": f.states[0].context.execution_id,
                }
            )
        )
    )
    assert context["candidate"]["content"]["objective"] == definition.content.objective
    result = _parse(
        await tools["record_routine_result"].handler(
            json.dumps(
                {
                    "slug": definition.slug,
                    "execution_id": f.states[0].context.execution_id,
                    "work": work(
                        notify=False, outcome=RoutineObjectiveOutcome.FINISHED
                    ).model_dump(mode="json"),
                }
            )
        )
    )
    assert result["execution"]["phase"] == "completed"
    assert await toolkit.operations.get(scope=f.scope, slug=definition.slug) is None


async def test_every_tool_rejects_missing_subagent_or_changed_run_authority(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    toolkit = _toolkit(rdb_session_manager, f)
    context = _context(f, AsyncMock())
    tools = {t.spec.name: t for t in (await toolkit.update_context(context)).tools}
    with pytest.raises(FunctionToolError, match="authority"):
        await tools["list_routines"].handler("{}")
    toolkit.bind_execution_owner(f.authority.execution_owner)
    await toolkit.update_context(
        dataclasses.replace(
            context,
            resource_authority=dataclasses.replace(
                f.authority, root_session_id="other"
            ),
        )
    )
    with pytest.raises(FunctionToolError, match="root Session"):
        await tools["list_routines"].handler("{}")
    await toolkit.update_context(
        dataclasses.replace(context, run_index=context.run_index + 1)
    )
    with pytest.raises(FunctionToolError, match="authority"):
        await tools["list_routines"].handler("{}")


async def test_tool_schemas_use_top_level_objects_and_runtime_notification_rules(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    toolkit = _toolkit(rdb_session_manager, f)
    toolkit.bind_execution_owner(f.authority.execution_owner)
    tools = {
        t.spec.name: t
        for t in (await toolkit.update_context(_context(f, AsyncMock()))).tools
    }
    assert len(tools) == 7
    for tool in tools.values():
        assert tool.spec.input_schema["type"] == "object"
        assert not ({"oneOf", "anyOf"} & tool.spec.input_schema.keys())
    item = f.states[0]
    for notify, message in [(False, "Forbidden message"), (True, None)]:
        invalid = work(notify=False, outcome=RoutineObjectiveOutcome.FAILED).model_dump(
            mode="json"
        )
        invalid.update(notify=notify, message=message)
        with pytest.raises(FunctionToolError):
            await tools["record_routine_result"].handler(
                json.dumps(
                    {
                        "slug": item.context.candidate.slug,
                        "execution_id": item.context.execution_id,
                        "work": invalid,
                    }
                )
            )
    assert (
        len(await f.repository.list_started(scope=f.scope, authority=f.authority)) == 2
    )
