"""Event agent execution repository tests."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionEndReason,
    AgentSessionStatus,
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    LLMProvider,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.vfs import make_vfs_projection, make_vfs_source_revision
from azents.engine.events.action_messages import ActionMessagePayload, GoalAction
from azents.engine.events.filters import EventCompactor
from azents.engine.events.types import (
    ActiveToolCall,
    CompactionSummaryPayload,
    Event,
    ExternalChannelMessagePayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
    validate_event_payload,
)
from azents.engine.run.failure import FailedRunAttempt, FailedRunRetryState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.agent_session_unread_run import RDBAgentSessionUnreadRun
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate, EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_model_settings,
)


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Event Runtime test", handle=handle),
    )
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent_runtime(
    session: AsyncSession,
    handle: str = "event-runtime-ws",
) -> tuple[str, str, str]:
    """Create AgentRuntime for tests."""
    workspace_id = await _create_workspace(session, handle)
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Event Runtime test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model-id",
        ),
    )
    session.add(agent)
    await session.flush()

    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id)
    session.add(runtime)
    await session.flush()
    return workspace_id, agent.id, runtime.id


def _model_selection() -> AgentModelSelection:
    """Create resolved model selection fixture."""
    return AgentModelSelection.model_validate(
        make_test_model_selection_dict(
            integration_id="integration-1",
            provider=LLMProvider.ANTHROPIC,
            model_identifier="resolved-model",
        )
    )


def _agent_session_repository() -> AgentSessionRepository:
    """Create AgentSessionRepository for tests."""
    return AgentSessionRepository()


def test_validate_event_payload_accepts_action_message() -> None:
    """Action message is a first-class persisted event payload."""
    payload = ActionMessagePayload(
        action=GoalAction(),
        message="Ship the goal",
    )

    validated = validate_event_payload(
        EventKind.ACTION_MESSAGE,
        payload.model_dump(mode="json"),
    )

    assert isinstance(validated, ActionMessagePayload)
    assert isinstance(validated.action, GoalAction)
    assert validated.message == "Ship the goal"


class TestEventExecutionRepositories:
    """Event execution repository tests."""

    async def test_user_message_default_effort_round_trip(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Preserve explicit null effort in requested and applied profiles."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            handle="event-profile-default-ws",
        )
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        transcript_repo = EventTranscriptRepository()
        requested_profile = RequestedInferenceProfile(
            model_target_label="Quality",
            reasoning_effort=None,
        )
        applied_profile = AppliedInferenceProfile(
            model_target_label="Quality",
            model_display_name="GPT 5.5",
            reasoning_effort=None,
        )

        appended = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(
                    content="Use the default effort",
                    requested_inference_profile=requested_profile,
                    applied_inference_profile=applied_profile,
                ).model_dump(mode="json"),
            ),
        )
        loaded = await transcript_repo.get_by_id(
            rdb_session,
            event_id=appended.id,
        )

        assert loaded is not None
        assert isinstance(loaded.payload, UserMessagePayload)
        assert loaded.payload.requested_inference_profile == requested_profile
        assert loaded.payload.applied_inference_profile == applied_profile
        stored = await rdb_session.get(RDBEvent, appended.id)
        assert stored is not None
        assert stored.payload["requested_inference_profile"] == {
            "model_target_label": "Quality",
            "reasoning_effort": None,
        }
        assert stored.payload["applied_inference_profile"] == {
            "model_target_label": "Quality",
            "model_display_name": "GPT 5.5",
            "reasoning_effort": None,
        }

    async def test_external_message_updates_last_user_input_at(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Treat released external invocations as recent Session input."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            handle="external-last-input-ws",
        )
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        previous_last_user_input_at = event_session.last_user_input_at
        payload = ExternalChannelMessagePayload(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="tenant-1",
            resource_id="resource-1",
            resource_label="C123:1.0",
            resource_type=ExternalChannelResourceType.THREAD,
            binding_id="binding-1",
            invocation_batch_id="batch-1",
            external_message_id="message-1",
            revision_id="revision-1",
            revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
            projection_root_id="external-channel:binding-1:message-1",
            provider_message_key="C123:1.0:1",
            provider_position="1",
            principal_id="principal-1",
            provider_user_id="U1",
            sender_display_name="Alice",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            authorization="authorized_invocation",
            lifecycle=ExternalChannelMessageLifecycle.CURRENT,
            body="hello",
            attachment_metadata={},
            provider_created_at=datetime.datetime(
                2026,
                7,
                22,
                tzinfo=datetime.UTC,
            ),
            provider_updated_at=None,
            original_url=None,
            truncated_context_message_count=0,
            truncated_context_size=0,
            correction_of_revision_id=None,
        )

        appended = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
                payload=payload.model_dump(mode="json"),
            ),
        )
        await rdb_session.refresh(event_session)

        assert event_session.last_user_input_at == appended.created_at
        assert event_session.last_user_input_at != previous_last_user_input_at

    async def test_turn_marker_default_effort_round_trip(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Preserve explicit null effort in durable turn provenance."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            handle="turn-marker-profile-default-ws",
        )
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        transcript_repo = EventTranscriptRepository()
        applied_profile = AppliedInferenceProfile(
            model_target_label="Quality",
            model_display_name="GPT 5.5",
            reasoning_effort=None,
        )
        turn_marker = TurnMarkerPayload(
            run_id="run-1",
            usage=TokenUsagePayload(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                raw={},
            ),
            applied_inference_profile=applied_profile,
        )

        appended = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.TURN_MARKER,
                payload=turn_marker.model_dump(mode="json"),
            ),
        )
        loaded = await transcript_repo.get_by_id(
            rdb_session,
            event_id=appended.id,
        )

        assert loaded is not None
        assert isinstance(loaded.payload, TurnMarkerPayload)
        assert loaded.payload == turn_marker
        stored = await rdb_session.get(RDBEvent, appended.id)
        assert stored is not None
        assert stored.payload["applied_inference_profile"] == {
            "model_target_label": "Quality",
            "model_display_name": "GPT 5.5",
            "reasoning_effort": None,
        }

    async def test_append_read_and_move_head(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Validate transcript append/read and model input head move."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        session_repo = _agent_session_repository()
        transcript_repo = EventTranscriptRepository()
        event_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )

        first = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="first").model_dump(mode="json"),
                external_id="first-user-input",
            ),
        )
        second = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="second").model_dump(mode="json"),
            ),
        )

        events = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
        )
        assert [event.id for event in events] == [first.id, second.id]
        assert [event.model_order for event in events] == [1000, 2000]

        updated = await transcript_repo.update_payload(
            rdb_session,
            first.id,
            UserMessagePayload(content="updated first"),
        )
        assert isinstance(updated.payload, UserMessagePayload)
        assert updated.payload.content == "updated first"

        moved = await session_repo.move_model_input_head(
            rdb_session,
            event_session.id,
            second.id,
        )
        assert moved.model_input_head_event_id == second.id

        from_head = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
            head_event_id=second.id,
        )
        assert [event.id for event in from_head] == [second.id]

    async def test_append_with_external_id_returns_existing_event(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Append with same External ID returns existing event."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        transcript_repo = EventTranscriptRepository()
        create = EventCreate(
            session_id=event_session.id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(content="first").model_dump(mode="json"),
            external_id="dedup-user-input",
        )

        first = await transcript_repo.append(rdb_session, create)
        second = await transcript_repo.append(
            rdb_session,
            create.model_copy(
                update={
                    "payload": UserMessagePayload(content="second").model_dump(
                        mode="json"
                    )
                }
            ),
        )

        assert second.id == first.id
        assert isinstance(second.payload, UserMessagePayload)
        assert second.payload.content == "first"
        result = await rdb_session.execute(
            sa.select(sa.func.count())
            .select_from(RDBEvent)
            .where(
                RDBEvent.session_id == event_session.id,
                RDBEvent.external_id == "dedup-user-input",
            )
        )
        assert result.scalar_one() == 1

    async def test_append_action_message_event_with_external_id(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Action message events validate and append with input-buffer external IDs."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        payload = ActionMessagePayload(
            action=GoalAction(),
            message="Ship the goal",
        )

        event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.ACTION_MESSAGE,
                payload=payload.model_dump(mode="json"),
                external_id="action-buffer-001",
            ),
        )

        assert event.kind == EventKind.ACTION_MESSAGE
        assert event.external_id == "action-buffer-001"
        assert isinstance(event.payload, ActionMessagePayload)
        assert isinstance(event.payload.action, GoalAction)
        assert event.payload.message == "Ship the goal"

    async def test_append_auto_model_order_waits_for_session_lock(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Automatic model_order assignment runs after session row lock."""
        session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)
        async with session_factory() as setup_session:
            workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
                setup_session,
                "event-runtime-lock-ws",
            )
            event_session = await _agent_session_repository().create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            await setup_session.commit()

        transcript_repo = EventTranscriptRepository()
        async with (
            session_factory() as lock_session,
            session_factory() as append_session,
        ):
            lock_tx = await lock_session.begin()
            await lock_session.execute(
                sa.select(RDBAgentSession.id)
                .where(RDBAgentSession.id == event_session.id)
                .with_for_update()
            )

            append_task = asyncio.create_task(
                transcript_repo.append(
                    append_session,
                    EventCreate(
                        session_id=event_session.id,
                        kind=EventKind.USER_MESSAGE,
                        payload=UserMessagePayload(content="blocked").model_dump(
                            mode="json"
                        ),
                        external_id="blocked-user-input",
                    ),
                )
            )
            try:
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(append_task), timeout=0.2)

                await lock_tx.commit()
                event = await asyncio.wait_for(append_task, timeout=2)
                await append_session.commit()

                assert event.model_order == 1000
            finally:
                if lock_tx.is_active:
                    await lock_tx.rollback()
                if not append_task.done():
                    append_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await append_task

    async def test_compaction_releases_session_lock_during_summary(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """Concurrent input commits while the compaction model is running."""
        session_factory = async_sessionmaker(rdb_engine, expire_on_commit=False)

        @asynccontextmanager
        async def session_manager() -> AsyncIterator[AsyncSession]:
            """Commit each compaction persistence stage on clean scope exit."""
            async with session_factory() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
                else:
                    await session.commit()

        transcript_repo = EventTranscriptRepository()
        session_repo = _agent_session_repository()
        async with session_factory() as setup_session:
            workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
                setup_session,
                "event-compaction-lock-ws",
            )
            event_session = await session_repo.create(
                setup_session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            first = await transcript_repo.append(
                setup_session,
                EventCreate(
                    session_id=event_session.id,
                    kind=EventKind.USER_MESSAGE,
                    payload=UserMessagePayload(content="before compaction").model_dump(
                        mode="json"
                    ),
                ),
            )
            await setup_session.commit()

        concurrent_input: Event | None = None

        async def summarize(
            old_events: Sequence[Event],
            summary_budget: object,
        ) -> str:
            """Append input through an independent transaction during summary."""
            nonlocal concurrent_input
            del old_events, summary_budget
            async with session_factory() as input_session:
                concurrent_input = await asyncio.wait_for(
                    transcript_repo.append(
                        input_session,
                        EventCreate(
                            session_id=event_session.id,
                            kind=EventKind.USER_MESSAGE,
                            payload=UserMessagePayload(
                                content="during compaction"
                            ).model_dump(mode="json"),
                        ),
                    ),
                    timeout=2,
                )
                await input_session.commit()
            return "summary"

        summary = await EventCompactor(
            session_manager=session_manager,
            transcript_repo=transcript_repo,
            session_repo=session_repo,
        ).compact(
            session_id=event_session.id,
            transcript=[first],
            compaction_id="compaction-lock-test",
            summarize=summarize,
        )

        assert summary is not None
        assert concurrent_input is not None
        assert summary.model_order < concurrent_input.model_order
        async with session_factory() as read_session:
            current_session = await session_repo.get_by_id(
                read_session,
                event_session.id,
            )
            assert current_session is not None
            model_input = await transcript_repo.list_for_model_input(
                read_session,
                event_session.id,
                head_event_id=current_session.model_input_head_event_id,
            )
        assert [event.id for event in model_input] == [
            summary.id,
            concurrent_input.id,
        ]
        payload = model_input[0].payload
        assert isinstance(payload, CompactionSummaryPayload)

    async def test_model_input_uses_logical_order(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Model input is fetched by model_order, not physical id."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        transcript_repo = EventTranscriptRepository()
        first = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="first").model_dump(mode="json"),
                model_order=2000,
            ),
        )
        second = await transcript_repo.append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="second").model_dump(mode="json"),
                model_order=1000,
            ),
        )

        events = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
        )
        assert [event.id for event in events] == [second.id, first.id]

        recent = await transcript_repo.list_recent_by_session_id(
            rdb_session,
            event_session.id,
            limit=10,
        )
        assert [event.id for event in recent] == [first.id, second.id]

        await transcript_repo.update_model_orders(
            rdb_session,
            event_session.id,
            {first.id: 500, second.id: 1500},
        )
        reordered = await transcript_repo.list_for_model_input(
            rdb_session,
            event_session.id,
        )
        assert [event.id for event in reordered] == [first.id, second.id]

    async def test_pending_run_activation_and_event_association(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Activate a model-independent pending run and retain event associations."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-profile",
        )
        session_repo = _agent_session_repository()
        event_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=event_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="profile input").model_dump(
                    mode="json"
                ),
            ),
        )
        repo = AgentRunRepository()
        pending = await repo.create_pending(
            rdb_session,
            session_id=event_session.id,
            parent_agent_run_id=None,
        )
        await repo.associate_input_events(
            rdb_session,
            run_id=pending.id,
            event_ids=[event.id, event.id],
        )
        activated_at = datetime.datetime.now(datetime.UTC)
        activated = await repo.activate_pending(
            rdb_session,
            run_id=pending.id,
            activated_at=activated_at,
        )

        assert activated.status == AgentRunStatus.RUNNING
        assert activated.started_at == activated_at
        assert await repo.list_input_event_ids(rdb_session, run_id=pending.id) == [
            event.id
        ]

    async def test_child_run_parentage_is_independent_of_session_inference_state(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Keep child run parentage while storing inference state on its Session."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-inherited-profile",
        )
        session_repo = _agent_session_repository()
        parent_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        child_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        inference_state = SessionInferenceState(
            model_target_label="Quality",
            model_selection=_model_selection(),
            model_settings=make_test_model_settings(),
            reasoning_effort=ModelReasoningEffort.HIGH,
            effective_context_window_tokens=128_000,
            effective_auto_compaction_threshold_tokens=115_200,
            resolved_at=datetime.datetime.now(datetime.UTC),
        )
        await session_repo.set_inference_state(
            rdb_session,
            session_id=child_session.id,
            inference_state=inference_state,
        )
        repo = AgentRunRepository()
        parent = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=parent_session.id,
                parent_agent_run_id=None,
            ),
        )
        child = await repo.create_pending(
            rdb_session,
            session_id=child_session.id,
            parent_agent_run_id=parent.id,
        )
        activated = await repo.activate_pending(
            rdb_session,
            run_id=child.id,
            activated_at=datetime.datetime.now(datetime.UTC),
        )
        refreshed_session = await session_repo.get_by_id(
            rdb_session,
            child_session.id,
        )

        assert activated.parent_agent_run_id == parent.id
        assert refreshed_session is not None
        assert refreshed_session.inference_state == inference_state

    async def test_input_event_association_rejects_another_session(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Reject an input event that does not belong to the run session."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-cross-session",
        )
        session_repo = _agent_session_repository()
        run_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        other_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        other_event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=other_session.id,
                kind=EventKind.USER_MESSAGE,
                payload=UserMessagePayload(content="other session").model_dump(
                    mode="json"
                ),
            ),
        )
        repo = AgentRunRepository()
        pending = await repo.create_pending(
            rdb_session,
            session_id=run_session.id,
            parent_agent_run_id=None,
        )

        with pytest.raises(
            ValueError,
            match="Input events must belong to the AgentRun session",
        ):
            await repo.associate_input_events(
                rdb_session,
                run_id=pending.id,
                event_ids=[other_event.id],
            )

        assert await repo.list_input_event_ids(rdb_session, run_id=pending.id) == []

    async def test_agent_run_vfs_projection_is_set_once(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Persist the first immutable VFS projection and retain it on retry."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-vfs-projection",
        )
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create_pending(
            rdb_session,
            session_id=event_session.id,
            parent_agent_run_id=None,
        )
        first = make_vfs_projection(
            [
                make_vfs_source_revision(
                    source_id="release:azents",
                    source_kind="global_release",
                    namespace="azents",
                    entries=[
                        (
                            "azents://skills/test/sample/SKILL.md",
                            b"first",
                            "text/markdown",
                        )
                    ],
                )
            ]
        )
        second = make_vfs_projection(
            [
                make_vfs_source_revision(
                    source_id="release:azents",
                    source_kind="global_release",
                    namespace="azents",
                    entries=[
                        (
                            "azents://skills/test/sample/SKILL.md",
                            b"second",
                            "text/markdown",
                        )
                    ],
                )
            ]
        )

        saved = await repo.set_vfs_projection_if_unset(
            rdb_session,
            run_id=run.id,
            session_id=event_session.id,
            projection=first,
        )
        retained = await repo.set_vfs_projection_if_unset(
            rdb_session,
            run_id=run.id,
            session_id=event_session.id,
            projection=second,
        )
        refreshed = await repo.get_by_id(rdb_session, run.id)

        assert saved == first
        assert retained == first
        assert refreshed is not None
        assert refreshed.vfs_projection == first

    async def test_agent_run_vfs_projection_rejects_session_mismatch(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Reject projection writes through another Session identity."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-vfs-permission",
        )
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create_pending(
            rdb_session,
            session_id=event_session.id,
            parent_agent_run_id=None,
        )
        projection = make_vfs_projection([])

        with pytest.raises(ValueError, match="not found in session"):
            await repo.set_vfs_projection_if_unset(
                rdb_session,
                run_id=run.id,
                session_id="another-session",
                projection=projection,
            )

    async def test_agent_run_phase_and_terminal_update(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Validate Agent run phase and terminal state updates."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                parent_agent_run_id=None,
            ),
        )
        assert run.run_index == 1

        waiting = await repo.update_phase(
            rdb_session,
            run.id,
            AgentRunPhase.WAITING_FOR_MODEL,
        )
        assert waiting.model_call_started_at is not None

        streaming = await repo.update_phase(
            rdb_session,
            run.id,
            AgentRunPhase.STREAMING_MODEL,
        )
        assert streaming.model_call_started_at == waiting.model_call_started_at

        active_call = ActiveToolCall(
            call_id="call-1",
            name="read_text",
            arguments='{"path":"README.md"}',
            started_at=datetime.datetime.now(datetime.UTC),
            owner_generation=1,
            wire_dialect="json_function",
        )
        executing = await repo.update_phase(
            rdb_session,
            run.id,
            AgentRunPhase.EXECUTING_TOOLS,
            active_tool_calls=[active_call],
        )
        assert executing.phase == AgentRunPhase.EXECUTING_TOOLS
        assert executing.active_tool_calls == [active_call]
        assert executing.model_call_started_at is None

        running = await repo.get_running_by_session_id(
            rdb_session,
            session_id=event_session.id,
        )
        assert running is not None
        assert running.id == run.id

        completed = await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
            terminal_result_event_id="0123456789abcdef0123456789abcdef",
            terminal_result_message="Completed subtask summary",
        )
        assert completed.status == AgentRunStatus.COMPLETED
        assert completed.phase == AgentRunPhase.IDLE
        assert completed.active_tool_calls == []
        assert completed.terminal_result_event_id == "0123456789abcdef0123456789abcdef"
        assert completed.terminal_result_message == "Completed subtask summary"
        assert (
            await repo.get_running_by_session_id(
                rdb_session,
                session_id=event_session.id,
            )
            is None
        )

    async def test_failed_run_lookup_by_terminal_result_event(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Resolve a manual retry source from its failed terminal event."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-manual-retry-source",
        )
        session_repo = _agent_session_repository()
        event_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        other_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                parent_agent_run_id=None,
            ),
        )
        terminal_event_id = "fedcba9876543210fedcba9876543210"
        await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.FAILED,
            ended_at=datetime.datetime.now(datetime.UTC),
            terminal_result_event_id=terminal_event_id,
        )

        found = await repo.get_failed_by_terminal_result_event_id(
            rdb_session,
            session_id=event_session.id,
            terminal_result_event_id=terminal_event_id,
        )
        wrong_session = await repo.get_failed_by_terminal_result_event_id(
            rdb_session,
            session_id=other_session.id,
            terminal_result_event_id=terminal_event_id,
        )

        assert found is not None
        assert found.id == run.id
        assert wrong_session is None

    async def test_completed_run_records_pending_idle_continuation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Completed Run atomically records its durable idle boundary."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-idle-boundary",
        )
        agent_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        completed = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )

        await repo.mark_terminal(
            rdb_session,
            completed.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        rdb_agent_session = await rdb_session.get(RDBAgentSession, agent_session.id)
        assert rdb_agent_session is not None
        await rdb_session.refresh(rdb_agent_session)
        assert rdb_agent_session.pending_idle_continuation_run_id == completed.id

        pending = await repo.create_pending(
            rdb_session,
            session_id=agent_session.id,
            parent_agent_run_id=None,
        )
        await repo.activate_pending(
            rdb_session,
            run_id=pending.id,
            activated_at=datetime.datetime.now(datetime.UTC),
        )

        await rdb_session.refresh(rdb_agent_session)
        assert rdb_agent_session.pending_idle_continuation_run_id is None

    async def test_noncompleted_run_does_not_record_pending_idle_continuation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Noncompleted terminal states cannot create idle continuation work."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-no-idle-boundary",
        )
        agent_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )

        await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.FAILED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        rdb_agent_session = await rdb_session.get(RDBAgentSession, agent_session.id)
        assert rdb_agent_session is not None
        assert rdb_agent_session.pending_idle_continuation_run_id is None

    async def test_archived_session_cannot_consume_pending_idle_continuation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A stale completed boundary cannot reactivate an archived Session."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-archived-idle-boundary",
        )
        session_repository = _agent_session_repository()
        agent_session = await session_repository.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        run_repository = AgentRunRepository()
        completed = await run_repository.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )
        await run_repository.mark_terminal(
            rdb_session,
            completed.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        await session_repository.archive(
            rdb_session,
            agent_session.id,
            ended_at=datetime.datetime.now(datetime.UTC),
            end_reason=AgentSessionEndReason.DELETED,
        )

        consumed = await session_repository.consume_pending_idle_continuation(
            rdb_session,
            session_id=agent_session.id,
            run_id=completed.id,
            continue_running=True,
        )

        rdb_agent_session = await rdb_session.get(RDBAgentSession, agent_session.id)
        assert rdb_agent_session is not None
        await rdb_session.refresh(rdb_agent_session)
        assert consumed is False
        assert rdb_agent_session.status is AgentSessionStatus.ARCHIVED
        assert rdb_agent_session.pending_idle_continuation_run_id == completed.id

    async def test_agent_run_retry_state_updates_and_clears_on_terminal(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """AgentRun retry_state is persisted while running and cleared at terminal."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(
            rdb_session,
            "event-runtime-retry-state",
        )
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                parent_agent_run_id=None,
            ),
        )
        now = datetime.datetime.now(datetime.UTC)
        retry_state = FailedRunRetryState.from_attempt(
            FailedRunAttempt(
                user_message="temporary failure",
                internal_message="RuntimeError('temporary failure')",
                error_type="RuntimeError",
                source="engine",
                visibility="internal",
                attempt_number=1,
                occurred_at=now,
            ),
            max_retries=10,
            backoff_seconds=1,
            next_retry_at=now + datetime.timedelta(seconds=1),
        )

        waiting = await repo.update_phase(
            rdb_session,
            run.id,
            AgentRunPhase.WAITING_FOR_MODEL,
        )
        assert waiting.model_call_started_at is not None

        updated = await repo.update_retry_state(rdb_session, run.id, retry_state)

        assert updated.retry_state == retry_state
        assert updated.model_call_started_at is None
        running = await repo.get_running_by_session_id(
            rdb_session,
            session_id=event_session.id,
        )
        assert running is not None
        assert running.retry_state == retry_state

        completed = await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.FAILED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        assert completed.retry_state is None

    async def test_agent_run_create_closes_stale_running_runs(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Creating a new run closes remaining running projection in same session."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        stale = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                parent_agent_run_id=None,
                phase=AgentRunPhase.WAITING_FOR_MODEL,
            ),
        )
        current = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                parent_agent_run_id=None,
            ),
        )

        closed = await repo.get_by_id(rdb_session, stale.id)
        assert closed is not None
        assert closed.status == AgentRunStatus.CANCELLED
        assert closed.phase == AgentRunPhase.IDLE
        running = await repo.get_running_by_session_id(
            rdb_session,
            session_id=event_session.id,
        )
        assert running is not None
        assert running.id == current.id

    async def test_mark_terminal_if_running_does_not_overwrite_terminal_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Worker fallback does not overwrite terminal run state."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        event_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=event_session.id,
                parent_agent_run_id=None,
            ),
        )
        await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.INTERRUPTED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        after_fallback = await repo.mark_terminal_if_running(
            rdb_session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        assert after_fallback is not None
        assert after_fallback.status == AgentRunStatus.INTERRUPTED

    async def test_terminal_transition_records_and_idempotently_acknowledges_unread_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A terminal Run creates one boundary that replay cannot recreate."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        agent_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        run = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )

        await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        boundary = await rdb_session.get(RDBAgentSessionUnreadRun, agent_session.id)
        assert boundary is not None
        assert boundary.run_id == run.id
        assert boundary.run_index == run.run_index

        acknowledged = await repo.acknowledge_unread_terminal_run(
            rdb_session,
            session_id=agent_session.id,
            run_id=run.id,
        )
        assert acknowledged is not None
        assert await rdb_session.get(RDBAgentSessionUnreadRun, agent_session.id) is None

        await repo.mark_terminal(
            rdb_session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        assert await rdb_session.get(RDBAgentSessionUnreadRun, agent_session.id) is None

    async def test_acknowledging_older_run_preserves_newer_unread_boundary(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Acknowledgement through Run N cannot clear terminal Run N+1."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        agent_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        repo = AgentRunRepository()
        first = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )
        await repo.mark_terminal(
            rdb_session,
            first.id,
            AgentRunStatus.COMPLETED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        second = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )
        await repo.mark_terminal(
            rdb_session,
            second.id,
            AgentRunStatus.CANCELLED,
            ended_at=datetime.datetime.now(datetime.UTC),
        )

        await repo.acknowledge_unread_terminal_run(
            rdb_session,
            session_id=agent_session.id,
            run_id=first.id,
        )

        boundary = await rdb_session.get(RDBAgentSessionUnreadRun, agent_session.id)
        assert boundary is not None
        assert boundary.run_id == second.id
        assert boundary.run_index == second.run_index

    async def test_agent_run_index_increments_per_session(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Agent run index increments within session scope."""
        workspace_id, agent_id, __runtime_id = await _create_agent_runtime(rdb_session)
        first_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        second_session = await _agent_session_repository().create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
            ),
        )
        await _agent_session_repository().archive(
            rdb_session,
            second_session.id,
            ended_at=datetime.datetime.now(datetime.UTC),
            end_reason=AgentSessionEndReason.DELETED,
        )
        repo = AgentRunRepository()

        first = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=first_session.id,
                parent_agent_run_id=None,
            ),
        )
        second = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=first_session.id,
                parent_agent_run_id=None,
            ),
        )
        other = await repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=second_session.id,
                parent_agent_run_id=None,
            ),
        )

        assert first.run_index == 1
        assert second.run_index == 2
        assert other.run_index == 1
