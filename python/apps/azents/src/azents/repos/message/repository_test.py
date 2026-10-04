"""Message repository pagination tests."""

import json

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    EventKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    LLMProvider,
)
from azents.core.json_value import JSONValue
from azents.core.workspace import WorkspaceCreate
from azents.engine.events.types import (
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    ExternalChannelMessagePayload,
    NativeArtifact,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.message import MessageRepository
from azents.repos.workspace import WorkspaceRepository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_JSON_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(
    dict[str, JSONValue]
)


def _native_artifact() -> NativeArtifact:
    """Create one valid native artifact for repository fixtures."""
    compat_key = build_native_compat_key(
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-test",
        schema_version="1",
    )
    return NativeArtifact(
        compat_key=compat_key,
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-test",
        schema_version="1",
        item={"type": "test"},
    )


async def _create_agent_session(session: AsyncSession) -> str:
    """Create an AgentSession for message repository tests."""
    handle = "message-pagination"
    await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Message pagination test", handle=handle),
    )
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="message-pagination-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    model_selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="message-pagination-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Message pagination test agent",
        model_selection=model_selection,
        lightweight_model_selection=model_selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(model_selection),
            lightweight_model_selection=(model_selection),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    runtime.workspace_path = "/workspace/agent"
    session.add(runtime)
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            agent_id=agent.id,
            title=None,
        ),
    )
    return agent_session.id


async def _create_events(session: AsyncSession, session_id: str) -> list[str]:
    """Create five ordered durable events and one reverted event."""
    ids = [f"{order:032x}" for order in range(1, 6)]
    for order, event_id in enumerate(ids, start=1):
        payload = _JSON_PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(
                sender_user_id=None, content=f"event-{order}"
            ).model_dump(mode="json")
        )
        event = RDBEvent(
            session_id=session_id,
            kind=EventKind.USER_MESSAGE,
            payload=payload,
        )
        event.id = event_id
        session.add(event)

    reverted = RDBEvent(
        session_id=session_id,
        kind=EventKind.USER_MESSAGE,
        payload=_JSON_PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(sender_user_id=None, content="reverted").model_dump(
                mode="json"
            )
        ),
        reverted=True,
    )
    reverted.id = f"{6:032x}"
    session.add(reverted)
    await session.flush()
    return ids


class TestMessageRepositoryPagination:
    """Bidirectional event pagination reports both boundary directions."""

    async def test_default_before_and_after_pages_have_directional_flags(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        session_id = await _create_agent_session(rdb_session)
        event_ids = await _create_events(rdb_session, session_id)
        repo = MessageRepository()

        latest, has_more, has_newer = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            limit=2,
        )
        assert [event.id for event in latest] == event_ids[3:5]
        assert has_more is True
        assert has_newer is False

        older, has_more, has_newer = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            limit=2,
            before=event_ids[3],
        )
        assert [event.id for event in older] == event_ids[1:3]
        assert has_more is True
        assert has_newer is True

        newer, has_more, has_newer = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            limit=2,
            after=event_ids[1],
        )
        assert [event.id for event in newer] == event_ids[2:4]
        assert has_more is True
        assert has_newer is True

    async def test_empty_boundary_pages_still_report_opposite_direction(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        session_id = await _create_agent_session(rdb_session)
        event_ids = await _create_events(rdb_session, session_id)
        repo = MessageRepository()

        (
            before_oldest,
            has_more,
            has_newer,
        ) = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            before=event_ids[0],
        )
        assert before_oldest == []
        assert has_more is False
        assert has_newer is True

        (
            after_newest,
            has_more,
            has_newer,
        ) = await repo.list_events_by_session_id_paginated(
            rdb_session,
            session_id,
            after=event_ids[-1],
        )
        assert after_newest == []
        assert has_more is True
        assert has_newer is False


async def test_historical_memory_retrieval_bounds_semantic_lanes_independently(
    rdb_session: AsyncSession,
) -> None:
    """Higher semantic evidence survives newer lower-tier lane rows."""
    session_id = await _create_agent_session(rdb_session)
    fixtures = (
        (
            EventKind.USER_MESSAGE,
            UserMessagePayload(
                sender_user_id=None,
                content="older human evidence",
            ),
        ),
        (
            EventKind.ASSISTANT_MESSAGE,
            AssistantMessagePayload(
                content="assistant evidence",
                native_artifact=_native_artifact(),
            ),
        ),
        (
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="conversation-call",
                name="channel_action",
                arguments=json.dumps(
                    {
                        "mode": "finish",
                        "binding": "binding-1",
                        "message": "published answer",
                    }
                ),
                wire_dialect="json_function",
                native_artifact=_native_artifact(),
            ),
        ),
        (
            EventKind.CLIENT_TOOL_RESULT,
            ClientToolResultPayload(
                call_id="conversation-call",
                name="channel_action",
                wire_dialect="json_function",
                status="completed",
                output=json.dumps(
                    {
                        "outcomes": [
                            {
                                "operation": "reply",
                                "part": 0,
                                "status": "delivered",
                            }
                        ]
                    }
                ),
            ),
        ),
        (
            EventKind.AGENT_MESSAGE,
            AgentMessagePayload(
                message_kind="send_message",
                source_session_agent_id="source",
                source_path="/source",
                target_session_agent_id="target",
                target_path="/target",
                content="newer other-agent evidence",
            ),
        ),
        (
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="generic-call",
                name="generic_tool",
                arguments="{}",
                wire_dialect="json_function",
                native_artifact=_native_artifact(),
            ),
        ),
        (
            EventKind.EXTERNAL_CHANNEL_MESSAGE,
            ExternalChannelMessagePayload(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="tenant-1",
                resource_id="resource-1",
                resource_label="#history",
                resource_type=ExternalChannelResourceType.THREAD,
                binding_id="binding-1",
                invocation_batch_id="batch-1",
                external_message_id="context-1",
                projection_root_id="external-channel:binding-1:context-1",
                provider_message_key="slack:tenant-1:context-1",
                provider_position="0001",
                principal_id="principal-1",
                provider_user_id="user-1",
                sender_display_name="Alice",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                prompt_role="context",
                body="newer context-only row",
                attachment_metadata={},
                provider_created_at=None,
                provider_updated_at=None,
                original_url=None,
                truncated_context_message_count=0,
                truncated_context_size=0,
            ),
        ),
        (
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="ignored-conversation-call",
                name="channel_action",
                arguments=json.dumps(
                    {
                        "mode": "ignore",
                        "binding": "binding-1",
                    }
                ),
                wire_dialect="json_function",
                native_artifact=_native_artifact(),
            ),
        ),
        (
            EventKind.ASSISTANT_MESSAGE,
            AssistantMessagePayload(
                content="",
                native_artifact=_native_artifact(),
            ),
        ),
    )
    event_ids: list[str] = []
    for index, (kind, payload) in enumerate(fixtures, start=1):
        event_id = f"{index:032x}"
        event_ids.append(event_id)
        row = RDBEvent(
            session_id=session_id,
            kind=kind,
            payload=_JSON_PAYLOAD_ADAPTER.validate_python(
                payload.model_dump(mode="json")
            ),
        )
        row.id = event_id
        rdb_session.add(row)
    await rdb_session.flush()

    events = await MessageRepository().list_historical_memory_events_by_tier(
        rdb_session,
        session_id=session_id,
        tail_event_id=event_ids[-1],
        per_tier_limit=1,
    )

    selected_ids = [event.id for event in events]
    assert selected_ids == [
        event_ids[0],
        event_ids[1],
        event_ids[2],
        event_ids[3],
        event_ids[4],
        event_ids[5],
        event_ids[7],
    ]
    assert event_ids[6] not in selected_ids
    assert event_ids[8] not in selected_ids


async def test_historical_memory_retrieval_stops_after_ineligible_row_budget(
    rdb_session: AsyncSession,
) -> None:
    """Long empty histories return fewer results instead of scanning unboundedly."""
    session_id = await _create_agent_session(rdb_session)
    valid = RDBEvent(
        session_id=session_id,
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=_JSON_PAYLOAD_ADAPTER.validate_python(
            AssistantMessagePayload(
                content="too old for the scan budget",
                native_artifact=_native_artifact(),
            ).model_dump(mode="json")
        ),
    )
    valid.id = f"{1:032x}"
    rdb_session.add(valid)
    for index in range(2, 53):
        row = RDBEvent(
            session_id=session_id,
            kind=EventKind.ASSISTANT_MESSAGE,
            payload=_JSON_PAYLOAD_ADAPTER.validate_python(
                AssistantMessagePayload(
                    content="",
                    native_artifact=_native_artifact(),
                ).model_dump(mode="json")
            ),
        )
        row.id = f"{index:032x}"
        rdb_session.add(row)
    await rdb_session.flush()

    events = await MessageRepository().list_historical_memory_events_by_tier(
        rdb_session,
        session_id=session_id,
        tail_event_id=f"{52:032x}",
        per_tier_limit=1,
    )

    assert events == []


async def test_registered_tool_scan_stops_after_ignored_call_budget(
    rdb_session: AsyncSession,
) -> None:
    """Ignored calls cannot trigger a complete-history search for conversation."""
    session_id = await _create_agent_session(rdb_session)
    valid = RDBEvent(
        session_id=session_id,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=_JSON_PAYLOAD_ADAPTER.validate_python(
            ClientToolCallPayload(
                call_id="old-valid-call",
                name="channel_action",
                arguments=json.dumps(
                    {
                        "mode": "finish",
                        "binding": "binding-1",
                        "message": "too old for the scan budget",
                    }
                ),
                wire_dialect="json_function",
                native_artifact=_native_artifact(),
            ).model_dump(mode="json")
        ),
    )
    valid.id = f"{1:032x}"
    rdb_session.add(valid)
    for index in range(2, 53):
        row = RDBEvent(
            session_id=session_id,
            kind=EventKind.CLIENT_TOOL_CALL,
            payload=_JSON_PAYLOAD_ADAPTER.validate_python(
                ClientToolCallPayload(
                    call_id=f"ignored-call-{index}",
                    name="channel_action",
                    arguments=json.dumps(
                        {
                            "mode": "ignore",
                            "binding": "binding-1",
                        }
                    ),
                    wire_dialect="json_function",
                    native_artifact=_native_artifact(),
                ).model_dump(mode="json")
            ),
        )
        row.id = f"{index:032x}"
        rdb_session.add(row)
    await rdb_session.flush()

    events = await MessageRepository().list_historical_memory_events_by_tier(
        rdb_session,
        session_id=session_id,
        tail_event_id=f"{52:032x}",
        per_tier_limit=1,
    )

    assert [event.id for event in events] == [f"{52:032x}"]
