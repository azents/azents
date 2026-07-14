"""InputBufferService tests."""

import dataclasses
import datetime
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    AgentSessionRunState,
    EventKind,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    InputBufferKind,
    LLMProvider,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import GoalAction, SkillAction
from azents.engine.events.types import (
    AgentMessagePayload,
    FileOutputPart,
    SkillLoadedPayload,
    UserMessagePayload,
)
from azents.engine.tools.goal import GoalStateStore
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillProjectionSnapshot,
    SkillProjectionState,
    SkillStateStore,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.input_buffer import RDBInputBuffer
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer, InputBufferCreate
from azents.repos.model_file.data import ModelFile
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.exchange_file import (
    ExchangeFileDownload,
    ExchangeFileError,
    ExchangeFileService,
    FileAccessDenied,
    FileNotFound,
    SessionNotFound,
)
from azents.services.model_file import (
    ModelFileCreateError,
    ModelFileInvalidImage,
    ModelFileService,
)
from azents.testing.model_selection import make_test_model_selection_dict

from .input_buffer import (
    InputBufferEnqueue,
    InputBufferPreparationStaleError,
    InputBufferService,
    TurnEffect,
    fold_turn_eligibility,
)


@pytest.mark.parametrize(
    ("initial", "effects", "expected"),
    [
        (False, [TurnEffect.NEUTRAL], False),
        (False, [TurnEffect.NEUTRAL, TurnEffect.ELIGIBLE], True),
        (True, [TurnEffect.NEUTRAL], True),
        (False, [TurnEffect.ELIGIBLE, TurnEffect.FAILED], False),
        (False, [TurnEffect.FAILED, TurnEffect.ELIGIBLE], True),
        (True, [TurnEffect.FAILED], False),
    ],
)
def test_fold_turn_eligibility(
    initial: bool,
    effects: list[TurnEffect],
    expected: bool,
) -> None:
    """FIFO effects deterministically control the next turn boundary."""
    eligible = initial
    for effect in effects:
        eligible = fold_turn_eligibility(eligible, effect)
    assert eligible is expected


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="InputBufferService test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create Agent for tests."""

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.OPENAI,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="InputBufferService test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


async def _create_fixture(
    rdb_session_manager: SessionManager[AsyncSession],
    slug: str,
) -> tuple[str, str]:
    """Create fixture satisfying InputBuffer FK."""
    async with rdb_session_manager() as session:
        workspace_id = await _create_workspace(session, f"{slug}-ws")
        user = await UserRepository().create(
            session,
            UserCreate(email=f"{slug}@example.com"),
        )
        agent_id = await _create_agent(session, workspace_id, slug)
        runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
        agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
            session,
            workspace_id=runtime.workspace_id,
            agent_id=runtime.agent_id,
        )
        return agent_session.id, user.id


async def _create_buffer(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    content: str,
    model_target_label: str | None = None,
    reasoning_effort: ModelReasoningEffort | None = None,
    attachments: list[str] | None = None,
    file_parts: list[FileOutputPart] | None = None,
) -> str:
    """Create InputBuffer for tests."""
    async with rdb_session_manager() as session:
        created = await InputBufferRepository().create(
            session,
            InputBufferCreate(
                session_id=session_id,
                kind=InputBufferKind.USER_MESSAGE,
                requested_model_target_label=model_target_label,
                requested_reasoning_effort=reasoning_effort,
                actor_user_id=user_id,
                content=content,
                idempotency_key=None,
                metadata={"source": "chat"},
                action=None,
                attachments=attachments if attachments is not None else [],
                file_parts=file_parts if file_parts is not None else [],
            ),
        )
        return created.id


async def _create_action_buffer(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    content: str,
    action: GoalAction | SkillAction,
) -> str:
    """Create action InputBuffer for tests."""
    async with rdb_session_manager() as session:
        created = await InputBufferRepository().create(
            session,
            InputBufferCreate(
                session_id=session_id,
                kind=InputBufferKind.ACTION_MESSAGE,
                requested_model_target_label="Fast",
                requested_reasoning_effort=ModelReasoningEffort.HIGH,
                actor_user_id=user_id,
                content=content,
                idempotency_key=None,
                metadata={"source": "chat"},
                action=action.model_dump(mode="json"),
                attachments=[],
                file_parts=[],
            ),
        )
        return created.id


async def _create_agent_message_buffer(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    content: str,
) -> str:
    """Create agent_message InputBuffer for tests."""
    async with rdb_session_manager() as session:
        created = await InputBufferRepository().create(
            session,
            InputBufferCreate(
                session_id=session_id,
                kind=InputBufferKind.AGENT_MESSAGE,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                actor_user_id=user_id,
                content=content,
                idempotency_key=None,
                metadata={
                    "source": "agent_mailbox",
                    "message_kind": "followup_task",
                    "source_session_agent_id": "source-agent",
                    "source_path": "/root",
                    "target_session_agent_id": "target-agent",
                    "target_path": "/root/child",
                },
                action=None,
                attachments=[],
                file_parts=[],
            ),
        )
        return created.id


def _skill_item() -> SkillProjectionItem:
    """Create projected Skill item for tests."""
    return SkillProjectionItem(
        id="skill-1",
        source_kind="project_claude",
        project_id="project-1",
        project_path="/workspace/agent/app",
        skill_dir_path="/workspace/agent/app/.claude/skills/review",
        skill_path="/workspace/agent/app/.claude/skills/review/SKILL.md",
        slug="review",
        name="review",
        description="Review code.",
        frontmatter={"name": "review", "description": "Review code."},
        body="# Review\nFollow this checklist.",
        content_hash="hash-1",
        source_label="app",
        relative_hint=".claude/skills/review",
    )


async def _agent_id_for_session(
    rdb_session_manager: SessionManager[AsyncSession],
    session_id: str,
) -> str:
    """Return agent ID for a test session."""
    async with rdb_session_manager() as session:
        agent_session = await AgentSessionRepository().get_by_id(session, session_id)
    assert agent_session is not None
    return agent_session.agent_id


def _exchange_file(
    *,
    file_id: str,
    user_id: str,
    object_key: str = "exchange/workspace-001/session/report.txt",
    preview_thumbnail_file_id: str | None = None,
    preview_thumbnail_uri: str | None = None,
) -> ExchangeFile:
    """Create ExchangeFile domain model for tests."""
    return ExchangeFile(
        id=file_id,
        workspace_id="workspace-001",
        agent_id="agent-001",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key=object_key,
        filename="report.txt",
        media_type="text/plain",
        size_bytes=11,
        sha256="sha256",
        created_by_user_id=user_id,
        preview_thumbnail_file_id=preview_thumbnail_file_id,
        preview_thumbnail_uri=preview_thumbnail_uri,
        preview_title="report.txt",
        preview_summary=None,
        preview_thumbnail_media_type=None,
        preview_thumbnail_width=None,
        preview_thumbnail_height=None,
        preview_generated_at=None,
        expires_at=tznow() + datetime.timedelta(days=30),
        expired_at=None,
        blob_deleted_at=None,
        created_at=tznow(),
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(
        self,
        metadata_result: (
            Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]
            | None
        ) = None,
    ) -> None:
        """Store metadata resolve result."""
        self.metadata_result = metadata_result
        self.resolve_attachment_for_agent_called = False

    async def resolve_attachment_metadata_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Return configured metadata resolve result."""
        del uri, agent_id, user_id
        if self.metadata_result is None:
            return Failure(FileNotFound())
        return self.metadata_result

    async def resolve_attachment_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Record Download attempt and treat as failure."""
        del uri, agent_id, user_id
        self.resolve_attachment_for_agent_called = True
        return Failure(FileNotFound())


class _RowLockCheckingExchangeFileService(_ExchangeFileService):
    """Attachment resolver that verifies no AgentSession row lock is held."""

    def __init__(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        *,
        session_id: str,
        metadata_result: Result[
            ExchangeFile,
            SessionNotFound | FileNotFound | FileAccessDenied,
        ],
    ) -> None:
        """Store the lock probe and attachment result."""
        super().__init__(metadata_result)
        self.rdb_session_manager = rdb_session_manager
        self.session_id = session_id
        self.lock_check_count = 0

    async def resolve_attachment_metadata_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Acquire the session row NOWAIT before resolving attachment metadata."""
        async with self.rdb_session_manager() as session:
            query = (
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == self.session_id)
                .with_for_update(nowait=True)
            )
            locked = (await session.execute(query)).scalar_one_or_none()
            assert locked is not None
        self.lock_check_count += 1
        return await super().resolve_attachment_metadata_for_agent(
            uri=uri,
            agent_id=agent_id,
            user_id=user_id,
        )


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Store whether called."""
        self.create_for_agent_pending_input_called = False

    async def create_for_agent_pending_input(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Result[ModelFile, ModelFileCreateError]:
        """Record call and treat as failure."""
        del agent_id, session_id, user_id, filename, media_type, body, metadata
        self.create_for_agent_pending_input_called = True
        return Failure(ModelFileInvalidImage())


def _input_buffer_service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    exchange_file_service: ExchangeFileService | None = None,
    model_file_service: _ModelFileService | None = None,
    event_transcript_repository: EventTranscriptRepository | None = None,
) -> InputBufferService:
    """Create InputBufferService for tests."""
    return InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=exchange_file_service or _ExchangeFileService(),
        model_file_service=model_file_service or _ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=(
            event_transcript_repository or EventTranscriptRepository()
        ),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
    )


class TestInputBufferService:
    """Validate InputBufferService behavior."""

    async def test_enqueue_creates_buffer_without_marking_session_running(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Enqueue only appends pending rows; producers own wake transitions."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-enqueue-running",
        )
        service = _input_buffer_service(rdb_session_manager)

        async with rdb_session_manager() as session:
            before = await AgentSessionRepository().get_by_id(
                session,
                session_id,
            )
            assert before is not None
            assert before.run_state == AgentSessionRunState.IDLE

            result = await service.enqueue(
                session,
                InputBufferEnqueue(
                    session_id=session_id,
                    kind=InputBufferKind.USER_MESSAGE,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    actor_user_id=user_id,
                    content="wake me",
                    idempotency_key="client-request-001",
                    metadata={"source": "test"},
                    action=None,
                    attachments=[],
                    file_parts=[],
                ),
            )
            after = await AgentSessionRepository().get_by_id(
                session,
                session_id,
            )

        assert result.created is True
        assert result.input_buffer.session_id == session_id
        assert result.input_buffer.content == "wake me"
        assert after is not None
        assert after.run_state == AgentSessionRunState.IDLE

    async def test_enqueue_deduplicates_only_the_same_inference_profile(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """An idempotency key cannot silently reuse another requested profile."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-profile-idempotency",
        )
        service = _input_buffer_service(rdb_session_manager)
        enqueue = InputBufferEnqueue(
            session_id=session_id,
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label="Quality",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            actor_user_id=user_id,
            content="profile-aware input",
            idempotency_key="client-request-profile",
            metadata={"source": "test"},
            action=None,
            attachments=[],
            file_parts=[],
        )

        async with rdb_session_manager() as session:
            created = await service.enqueue(session, enqueue)
            deduplicated = await service.enqueue(session, enqueue)

            assert created.created is True
            assert deduplicated.created is False
            assert deduplicated.input_buffer.id == created.input_buffer.id

            with pytest.raises(
                ValueError,
                match="idempotency key already used for another inference profile",
            ):
                await service.enqueue(
                    session,
                    dataclasses.replace(
                        enqueue,
                        requested_model_target_label="Fast",
                    ),
                )

            with pytest.raises(
                ValueError,
                match="idempotency key already used for another inference profile",
            ):
                await service.enqueue(
                    session,
                    dataclasses.replace(
                        enqueue,
                        requested_reasoning_effort=ModelReasoningEffort.LOW,
                    ),
                )

    async def test_enqueue_rejects_profile_mismatch_from_idempotency_race(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """The atomic create result is checked even when the pre-read misses."""
        repository = AsyncMock(spec=InputBufferRepository)
        repository.get_by_idempotency_key.return_value = None
        repository.create_idempotent.return_value = InputBuffer(
            id="buffer-winner",
            session_id="session-001",
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label="Fast",
            requested_reasoning_effort=ModelReasoningEffort.LOW,
            actor_user_id="user-001",
            content="winner",
            idempotency_key="client-request-race",
            metadata={"source": "test"},
            action=None,
            attachments=[],
            file_parts=[],
            created_at=datetime.datetime.now(datetime.UTC),
        )
        service = InputBufferService(
            session_manager=rdb_session_manager,
            input_buffer_repository=repository,
            exchange_file_service=_ExchangeFileService(),
            model_file_service=_ModelFileService(),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            action_execution_repository=ActionExecutionRepository(),
        )
        enqueue = InputBufferEnqueue(
            session_id="session-001",
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label="Quality",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            actor_user_id="user-001",
            content="loser",
            idempotency_key="client-request-race",
            metadata={"source": "test"},
            action=None,
            attachments=[],
            file_parts=[],
        )

        with pytest.raises(
            ValueError,
            match="idempotency key already used for another inference profile",
        ):
            await service.enqueue(AsyncMock(spec=AsyncSession), enqueue)

    async def test_flush_promotes_buffer_and_deletes_row(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """On flush success, event creation and buffer deletion share result."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-promote",
        )
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="buffered message",
            model_target_label="Quality",
            reasoning_effort=None,
        )
        service = _input_buffer_service(rdb_session_manager)

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.claimed_count == 1
        assert result.inserted_count == 1
        assert result.deduped_count == 0
        assert result.requested_inference_profile == RequestedInferenceProfile(
            model_target_label="Quality",
            reasoning_effort=None,
        )
        assert result.promoted_event_ids == [result.events[0].id]
        assert len(result.user_messages) == 1
        assert len(result.events) == 1
        assert result.events[0].external_id == f"{buffer_id}:user_message"
        event_payload = result.events[0].payload
        assert isinstance(event_payload, UserMessagePayload)
        assert event_payload.requested_inference_profile == RequestedInferenceProfile(
            model_target_label="Quality",
            reasoning_effort=None,
        )
        assert event_payload.applied_inference_profile == AppliedInferenceProfile(
            model_target_label="Quality",
            model_display_name=None,
            reasoning_effort=None,
        )
        promoted = result.user_messages[0]
        assert promoted.external_id == f"{buffer_id}:user_message"
        assert promoted.payload.content == "buffered message"
        assert (
            promoted.payload.requested_inference_profile
            == RequestedInferenceProfile(
                model_target_label="Quality",
                reasoning_effort=None,
            )
        )
        assert promoted.payload.applied_inference_profile == AppliedInferenceProfile(
            model_target_label="Quality",
            model_display_name=None,
            reasoning_effort=None,
        )
        async with rdb_session_manager() as session:
            remaining = await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBInputBuffer)
                .where(RDBInputBuffer.id == buffer_id)
            )
            stored_event = await session.get(RDBEvent, result.events[0].id)
        assert remaining == 0
        assert stored_event is not None
        assert stored_event.payload["requested_inference_profile"] == {
            "model_target_label": "Quality",
            "reasoning_effort": None,
        }

    async def test_flush_rejects_stale_preparation_snapshot(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A changed FIFO head is not consumed with another input's preparation."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-stale-preparation",
        )
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="keep pending",
            model_target_label="Quality",
            reasoning_effort=None,
        )
        service = _input_buffer_service(rdb_session_manager)

        with pytest.raises(InputBufferPreparationStaleError):
            await service.flush_session_input_buffers(
                session_id=session_id,
                model="gpt-5.4",
                required_inference_profile=None,
                expected_buffer_id="another-buffer",
                prepared_inference_state=None,
                prepared_attachments=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )

        async with rdb_session_manager() as session:
            remaining = await InputBufferRepository().get_by_id(session, buffer_id)
        assert remaining is not None

    async def test_flush_rolls_back_inference_state_and_buffer_on_event_failure(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Session inference update, event append, and buffer deletion are atomic."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-atomic-preparation",
        )
        buffer_id = await _create_action_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="Prepare the release",
            action=GoalAction(),
        )
        agent_id = await _agent_id_for_session(rdb_session_manager, session_id)
        prepared_state = SessionInferenceState(
            model_target_label="Fast",
            model_selection=AgentModelSelection.model_validate(
                make_test_model_selection_dict(
                    integration_id="1234567890abcdef1234567890abcdef",
                    provider=LLMProvider.ANTHROPIC,
                    model_identifier="prepared-model",
                )
            ),
            reasoning_effort=ModelReasoningEffort.HIGH,
            effective_context_window_tokens=100_000,
            effective_auto_compaction_threshold_tokens=80_000,
            resolved_at=datetime.datetime.now(datetime.UTC),
        )
        event_repository = EventTranscriptRepository()
        monkeypatch.setattr(
            event_repository,
            "append",
            AsyncMock(side_effect=RuntimeError("event append failed")),
        )
        service = _input_buffer_service(
            rdb_session_manager,
            event_transcript_repository=event_repository,
        )

        with pytest.raises(RuntimeError, match="event append failed"):
            await service.flush_session_input_buffers(
                session_id=session_id,
                model="prepared-model",
                required_inference_profile=RequestedInferenceProfile(
                    model_target_label="Fast",
                    reasoning_effort=ModelReasoningEffort.HIGH,
                ),
                expected_buffer_id=buffer_id,
                prepared_inference_state=prepared_state,
                prepared_attachments=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )

        async with rdb_session_manager() as session:
            agent_session = await AgentSessionRepository().get_by_id(
                session,
                session_id,
            )
            remaining = await InputBufferRepository().get_by_id(session, buffer_id)
        assert agent_session is not None
        goal = await GoalStateStore(session_manager=rdb_session_manager).load(
            agent_id,
            session_id,
        )
        assert agent_session.inference_state is None
        assert remaining is not None
        assert goal.objective is None
        assert goal.status is None

    async def test_flush_associates_events_with_run_before_buffer_delete(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Promotion, run association, and buffer deletion share one transaction."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-run-association",
        )
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="associate atomically",
            model_target_label="Quality",
            reasoning_effort=ModelReasoningEffort.HIGH,
        )
        run_repository = AgentRunRepository()
        async with rdb_session_manager() as session:
            run = await run_repository.create_pending(
                session,
                session_id=session_id,
                parent_agent_run_id=None,
            )

        result = await _input_buffer_service(
            rdb_session_manager
        ).flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Quality",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=run.id,
        )

        async with rdb_session_manager() as session:
            associated_event_ids = await run_repository.list_input_event_ids(
                session,
                run_id=run.id,
            )
            remaining = await session.get(RDBInputBuffer, buffer_id)
        assert associated_event_ids == result.promoted_event_ids
        assert remaining is None

    async def test_flush_processes_only_oldest_buffer(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Each preparation transaction consumes exactly one FIFO head."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-profile-segment",
        )
        first_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="first",
            model_target_label="Fast",
            reasoning_effort=ModelReasoningEffort.HIGH,
        )
        second_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="second",
            model_target_label="Fast",
            reasoning_effort=ModelReasoningEffort.HIGH,
        )
        third_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="third",
            model_target_label="Fast",
            reasoning_effort=ModelReasoningEffort.LOW,
        )

        result = await _input_buffer_service(
            rdb_session_manager
        ).flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=first_id,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.deleted_buffer_ids == [first_id]
        assert result.requested_inference_profile == RequestedInferenceProfile(
            model_target_label="Fast",
            reasoning_effort=ModelReasoningEffort.HIGH,
        )
        assert result.promoted_event_ids == [event.id for event in result.events]
        async with rdb_session_manager() as session:
            remaining_ids = list(
                (
                    await session.execute(
                        sa.select(RDBInputBuffer.id).where(
                            RDBInputBuffer.session_id == session_id
                        )
                    )
                ).scalars()
            )
        assert remaining_ids == [second_id, third_id]

    async def test_processor_does_not_apply_run_profile_filtering(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """FIFO preparation is independent from the previous turn profile."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-profile-mismatch",
        )
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="wait for next run",
            model_target_label="Quality",
            reasoning_effort=None,
        )

        result = await _input_buffer_service(
            rdb_session_manager
        ).flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=None,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.claimed_count == 1
        assert result.requested_inference_profile == RequestedInferenceProfile(
            model_target_label="Quality",
            reasoning_effort=None,
        )
        assert len(result.promoted_event_ids) == 1
        async with rdb_session_manager() as session:
            remaining = await session.get(RDBInputBuffer, buffer_id)
        assert remaining is None

    async def test_flush_promotes_agent_message_payload(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Agent mailbox input is persisted as an agent_message event."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-message",
        )
        buffer_id = await _create_agent_message_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="continue with the next step",
        )
        service = _input_buffer_service(rdb_session_manager)

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.claimed_count == 1
        assert result.inserted_count == 1
        assert result.requested_inference_profile is None
        assert [message.external_id for message in result.user_messages] == [
            f"{buffer_id}:agent_message"
        ]
        event = result.events[0]
        assert event.kind == EventKind.AGENT_MESSAGE
        assert event.external_id == f"{buffer_id}:agent_message"
        assert isinstance(event.payload, AgentMessagePayload)
        assert event.payload.message_kind == "followup_task"
        assert event.payload.source_path == "/root"
        assert event.payload.target_path == "/root/child"
        assert event.payload.content == "continue with the next step"

    async def test_flush_skill_action_loads_skill_before_user_message(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Skill action promotes skill_loaded then the request as user_message."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-skill-action",
        )
        agent_id = await _agent_id_for_session(rdb_session_manager, session_id)
        item = _skill_item()
        await SkillStateStore(session_manager=rdb_session_manager).update(
            agent_id,
            session_id,
            lambda _current: SkillProjectionState(
                active=SkillProjectionSnapshot(items=[item])
            ),
        )
        buffer_id = await _create_action_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="Review this PR",
            action=SkillAction(skill_path=item.skill_path),
        )
        service = _input_buffer_service(rdb_session_manager)

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.inserted_count == 2
        assert [event.kind for event in result.events] == [
            EventKind.SKILL_LOADED,
            EventKind.USER_MESSAGE,
        ]
        skill_event = result.events[0]
        assert skill_event.external_id == f"{buffer_id}:skill_loaded"
        assert isinstance(skill_event.payload, SkillLoadedPayload)
        assert skill_event.payload.skill_path == item.skill_path
        assert skill_event.payload.body == item.body
        assert skill_event.payload.user_message == "Review this PR"
        user_event = result.events[1]
        assert user_event.external_id == f"{buffer_id}:user_message"
        assert isinstance(user_event.payload, UserMessagePayload)
        assert user_event.payload.content == "Review this PR"
        assert [message.external_id for message in result.user_messages] == [
            f"{buffer_id}:user_message"
        ]

    async def test_attachment_preparation_precedes_session_row_lock(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Resolve attachments before the durable flush locks AgentSession."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-promote-attachment",
        )
        file_id = "1234567890abcdef1234567890abcdef"
        thumbnail_file_id = "abcdef1234567890abcdef1234567890"
        attachment_uri = "exchange://exchange/workspace-001/session/report.txt"
        thumbnail_uri = "exchange://exchange/workspace-001/previews/report-thumb.jpg"
        attachment_buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="buffered with file",
            attachments=[attachment_uri],
        )
        exchange_file_service = _RowLockCheckingExchangeFileService(
            rdb_session_manager,
            session_id=session_id,
            metadata_result=Success(
                _exchange_file(
                    file_id=file_id,
                    user_id=user_id,
                    object_key=attachment_uri.removeprefix("exchange://"),
                    preview_thumbnail_file_id=thumbnail_file_id,
                    preview_thumbnail_uri=thumbnail_uri,
                )
            ),
        )
        service = _input_buffer_service(
            rdb_session_manager,
            exchange_file_service=exchange_file_service,
        )

        prepared_attachments = await service.prepare_pending_input_attachments(
            session_id=session_id,
            expected_buffer_id=attachment_buffer_id,
        )
        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=attachment_buffer_id,
            prepared_inference_state=None,
            prepared_attachments=prepared_attachments,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        promoted = result.user_messages[0]
        assert len(promoted.payload.attachments) == 1
        assert promoted.payload.attachments[0].uri == attachment_uri
        assert promoted.payload.attachments[0].preview_summary is not None
        assert promoted.payload.attachments[0].preview_thumbnail_uri == thumbnail_uri
        async with rdb_session_manager() as session:
            event = await EventTranscriptRepository().get_by_external_id(
                session,
                session_id,
                promoted.external_id,
            )
        assert event is not None
        payload = event.payload
        assert isinstance(payload, UserMessagePayload)
        assert payload.content == "buffered with file"
        assert payload.attachments[0].uri == attachment_uri
        assert payload.attachments[0].preview_thumbnail_uri == thumbnail_uri
        assert len(result.events) == 1
        assert result.events[0].id == event.id
        assert exchange_file_service.lock_check_count == 1

    async def test_flush_reuses_buffer_file_parts_without_rematerializing(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """FilePart fixed at creation boundary is not recreated on flush."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-existing-file-part",
        )
        attachment_uri = "exchange://exchange/workspace-001/session/image.jpg"
        existing_part = FileOutputPart(
            model_file_id="model-file-from-input-boundary",
            media_type="image/jpeg",
            name="image.jpg",
            size=123,
            kind="image",
            metadata={"source_kind": "user_upload"},
        )
        image_buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="buffered with image",
            attachments=[attachment_uri],
            file_parts=[existing_part],
        )
        exchange_file_service = _ExchangeFileService(
            Success(
                _exchange_file(
                    file_id="1234567890abcdef1234567890abcdef",
                    user_id=user_id,
                    object_key=attachment_uri.removeprefix("exchange://"),
                )
            )
        )
        model_file_service = _ModelFileService()
        service = _input_buffer_service(
            rdb_session_manager,
            exchange_file_service=exchange_file_service,
            model_file_service=model_file_service,
        )

        prepared_attachments = await service.prepare_pending_input_attachments(
            session_id=session_id,
            expected_buffer_id=image_buffer_id,
        )
        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=image_buffer_id,
            prepared_inference_state=None,
            prepared_attachments=prepared_attachments,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        promoted = result.user_messages[0]
        assert isinstance(promoted.payload.content, list)
        assert promoted.payload.content[1] == existing_part
        assert not model_file_service.create_for_agent_pending_input_called
        assert not exchange_file_service.resolve_attachment_for_agent_called

    async def test_deleted_buffer_is_not_promoted(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Buffer deleted before flush is not promoted to event."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-deleted-before-flush",
        )
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="deleted message",
        )
        async with rdb_session_manager() as session:
            await InputBufferRepository().delete_by_session_and_id(
                session,
                session_id,
                buffer_id,
            )
        service = _input_buffer_service(rdb_session_manager)

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=None,
            prepared_inference_state=None,
            prepared_attachments=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.claimed_count == 0
        assert result.user_messages == []
        assert result.events == []
