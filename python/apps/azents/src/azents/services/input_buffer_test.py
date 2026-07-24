"""InputBufferService tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    EventKind,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    InputBufferKind,
    InputBufferSchedulingMode,
    LLMProvider,
    ModelFileStatus,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.vfs import make_vfs_projection, make_vfs_source_revision
from azents.engine.events.action_messages import GoalAction, SkillAction
from azents.engine.events.types import (
    AgentMessagePayload,
    FileOutputPart,
    SkillLoadedPayload,
    UserMessagePayload,
)
from azents.engine.run.resolve import (
    materialize_admitted_input_exchange_file_attachments,
)
from azents.engine.tools.goal import GoalStateStore
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillProjectionSnapshot,
    SkillProjectionState,
    SkillStateStore,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.input_buffer import RDBInputBuffer
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.external_channel.data import (
    ExternalChannelInvocationProjectionItem,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
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
    ModelFileOversized,
    ModelFileService,
)
from azents.services.vfs import VfsResolvedFile
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_model_settings,
)

from .input_buffer import (
    EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY,
    ExternalChannelInvocationInputBufferProcessor,
    InputBufferEnqueue,
    InputBufferOwnerGenerationStaleError,
    InputBufferPreparationContext,
    InputBufferPreparationStaleError,
    InputBufferService,
    PreparedInputBufferFiles,
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
        agent_session = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=runtime.workspace_id,
                agent_id=runtime.agent_id,
            )
        ).session
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
                scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
                requested_model_target_label=model_target_label,
                requested_reasoning_effort=reasoning_effort,
                sender_user_id=user_id,
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
                scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
                requested_model_target_label="Fast",
                requested_reasoning_effort=ModelReasoningEffort.HIGH,
                sender_user_id=user_id,
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
    content: str,
    scheduling_mode: InputBufferSchedulingMode,
) -> str:
    """Create agent_message InputBuffer for tests."""
    async with rdb_session_manager() as session:
        created = await InputBufferRepository().create(
            session,
            InputBufferCreate(
                session_id=session_id,
                kind=InputBufferKind.AGENT_MESSAGE,
                scheduling_mode=scheduling_mode,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
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


async def _create_agent_result_buffer(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    session_id: str,
    content: str,
    source_session_agent_id: str,
    target_session_agent_id: str,
    source_run_id: str,
    source_run_index: int,
    source_terminal_result_event_id: str,
) -> str:
    """Create terminal agent_result InputBuffer for tests."""
    async with rdb_session_manager() as session:
        created = await InputBufferRepository().create(
            session,
            InputBufferCreate(
                session_id=session_id,
                kind=InputBufferKind.AGENT_MESSAGE,
                scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
                content=content,
                idempotency_key=f"agent_result:{source_run_id}",
                metadata={
                    "source": "agent_mailbox",
                    "message_kind": "agent_result",
                    "source_session_agent_id": source_session_agent_id,
                    "source_path": "/root/reviewer",
                    "target_session_agent_id": target_session_agent_id,
                    "target_path": "/root",
                    "source_run_id": source_run_id,
                    "source_run_index": str(source_run_index),
                    "run_status": "completed",
                    "source_terminal_result_event_id": source_terminal_result_event_id,
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


async def _create_child_session_agent(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    parent_session_id: str,
    name: str = "reviewer",
) -> tuple[str, str]:
    """Create a direct child and return parent and child SessionAgent IDs."""
    async with rdb_session_manager() as session:
        repository = AgentSessionRepository()
        parent = await repository.get_session_agent_by_session_id(
            session,
            parent_session_id,
        )
        assert parent is not None
        child = await repository.create_child_session_agent(
            session,
            parent_session_agent_id=parent.id,
            name=name,
            agent_type="default",
            title=None,
            last_task_message=None,
        )
    return parent.id, child.id


async def _create_terminal_child_run(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    child_session_agent_id: str,
    terminal_result_event_id: str,
) -> tuple[str, int]:
    """Create one completed Run owned by a child SessionAgent."""
    async with rdb_session_manager() as session:
        session_repository = AgentSessionRepository()
        child = await session_repository.get_session_agent_by_id(
            session,
            child_session_agent_id,
        )
        assert child is not None
        run_repository = AgentRunRepository()
        run = await run_repository.create_pending(
            session,
            session_id=child.agent_session_id,
            parent_agent_run_id=None,
        )
        completed = await run_repository.mark_terminal(
            session,
            run.id,
            AgentRunStatus.COMPLETED,
            ended_at=tznow(),
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message="Completed child result",
        )
    return completed.id, completed.run_index


class _VfsService:
    """VFS resolver test double for managed Skill action promotion."""

    def __init__(self) -> None:
        revision = make_vfs_source_revision(
            source_id="release:azents",
            source_kind="global_release",
            namespace="azents",
            entries=[
                (
                    "azents://skills/azents/review/SKILL.md",
                    b"---\nname: review\ndescription: Review code.\n---\nManaged body",
                    "text/markdown",
                )
            ],
        )
        self.projection = make_vfs_projection([revision])
        self.run_ids: list[str] = []

    async def resolve_file(self, **kwargs: object) -> VfsResolvedFile:
        """Resolve from the configured immutable projection."""
        self.run_ids.append(str(kwargs["run_id"]))
        entry = self.projection.find(str(kwargs["uri"]))
        if entry is None:
            raise AssertionError("Missing VFS Skill fixture")
        return VfsResolvedFile(
            projection_revision_id=self.projection.revision_id,
            projection_hash=self.projection.projection_hash,
            entry=entry,
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
        retention_root_session_id="session-root",
        retention_bound_at=tznow(),
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
        download_result: Result[ExchangeFileDownload, ExchangeFileError] | None = None,
    ) -> None:
        """Store metadata resolve result."""
        self.metadata_result = metadata_result
        self.download_result = download_result
        self.resolve_attachment_metadata_for_agent_called = False
        self.resolve_attachment_for_agent_called = False
        self.resolve_admitted_input_attachment_metadata_called = False
        self.resolve_admitted_input_attachment_called = False
        self.admitted_download_exception: Exception | None = None

    async def resolve_attachment_metadata_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Return configured metadata resolve result."""
        del uri, agent_id, session_id, user_id
        self.resolve_attachment_metadata_for_agent_called = True
        if self.metadata_result is None:
            return Failure(FileNotFound())
        return self.metadata_result

    async def resolve_attachment_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Record Download attempt and return the configured result."""
        del uri, agent_id, session_id, user_id
        self.resolve_attachment_for_agent_called = True
        if self.download_result is None:
            return Failure(FileNotFound())
        return self.download_result

    async def resolve_admitted_input_attachment_metadata(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Return configured root-claim authorized metadata result."""
        del uri, agent_id, session_id
        self.resolve_admitted_input_attachment_metadata_called = True
        if self.metadata_result is None:
            return Failure(FileNotFound())
        return self.metadata_result

    async def resolve_admitted_input_attachment(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Return configured root-claim authorized download result."""
        del uri, agent_id, session_id
        self.resolve_admitted_input_attachment_called = True
        if self.admitted_download_exception is not None:
            raise self.admitted_download_exception
        if self.download_result is None:
            return Failure(FileNotFound())
        return self.download_result


class _ModelFileService(ModelFileService):
    """ModelFileService for input materialization tests."""

    def __init__(
        self,
        result: Result[ModelFile, ModelFileCreateError] | None = None,
    ) -> None:
        """Store the configured creation result."""
        self.result = result or Failure(
            cast(ModelFileCreateError, ModelFileInvalidImage())
        )
        self.create_for_agent_pending_input_called = False
        self.create_for_admitted_input_called = False
        self.discarded_model_file_ids: list[str] = []

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
        """Record ModelFile materialization and return the configured result."""
        del agent_id, session_id, user_id, filename, media_type, body, metadata
        self.create_for_agent_pending_input_called = True
        return self.result

    async def create_for_admitted_input(
        self,
        *,
        agent_id: str,
        session_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Result[ModelFile, ModelFileCreateError]:
        """Record internal admitted-input materialization."""
        del agent_id, session_id, filename, media_type, body, metadata
        self.create_for_admitted_input_called = True
        return self.result

    async def discard_pending_input(
        self,
        *,
        model_file_ids: Sequence[str],
    ) -> int:
        """Record ModelFiles discarded after failed promotion."""
        self.discarded_model_file_ids.extend(model_file_ids)
        return len(model_file_ids)


class _DeletingExchangeFileService(_ExchangeFileService):
    """Delete the prepared FIFO head while attachment metadata is resolving."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        session_id: str,
        buffer_id: str,
        metadata_result: Result[
            ExchangeFile,
            SessionNotFound | FileNotFound | FileAccessDenied,
        ],
        download_result: Result[ExchangeFileDownload, ExchangeFileError] | None = None,
    ) -> None:
        """Store the row mutation performed by the external resolution phase."""
        super().__init__(metadata_result, download_result)
        self.session_manager = session_manager
        self.session_id = session_id
        self.buffer_id = buffer_id

    async def resolve_attachment_metadata_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Mutate FIFO state through another session before returning metadata."""
        async with self.session_manager() as session:
            await InputBufferRepository().delete_by_session_and_id(
                session,
                self.session_id,
                self.buffer_id,
            )
        return await super().resolve_attachment_metadata_for_agent(
            uri=uri,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def resolve_admitted_input_attachment_metadata(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Mutate FIFO state before root-claim metadata resolution returns."""
        async with self.session_manager() as session:
            await InputBufferRepository().delete_by_session_and_id(
                session,
                self.session_id,
                self.buffer_id,
            )
        return await super().resolve_admitted_input_attachment_metadata(
            uri=uri,
            agent_id=agent_id,
            session_id=session_id,
        )


class _CancellingSecondAttachmentExchangeFileService(_ExchangeFileService):
    """Cancel while resolving the second attachment."""

    def __init__(
        self,
        *,
        metadata_result: Result[
            ExchangeFile,
            SessionNotFound | FileNotFound | FileAccessDenied,
        ],
        download_result: Result[ExchangeFileDownload, ExchangeFileError],
    ) -> None:
        """Store successful first-attachment results."""
        super().__init__(metadata_result, download_result)
        self.metadata_calls = 0

    async def resolve_attachment_metadata_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Return the first attachment and cancel during the second."""
        self.metadata_calls += 1
        if self.metadata_calls == 2:
            raise asyncio.CancelledError
        return await super().resolve_attachment_metadata_for_agent(
            uri=uri,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def resolve_admitted_input_attachment_metadata(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Return the first attachment and cancel during the second."""
        self.metadata_calls += 1
        if self.metadata_calls == 2:
            raise asyncio.CancelledError
        return await super().resolve_admitted_input_attachment_metadata(
            uri=uri,
            agent_id=agent_id,
            session_id=session_id,
        )


def _input_buffer_service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    exchange_file_service: ExchangeFileService | None = None,
    model_file_service: ModelFileService | None = None,
    event_transcript_repository: EventTranscriptRepository | None = None,
    vfs_projection_service: object | None = None,
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
        vfs_projection_service=vfs_projection_service,  # pyright: ignore[reportArgumentType]
        external_channel_repository=ExternalChannelRepository(),
    )


@asynccontextmanager
async def _unit_session_manager() -> AsyncIterator[AsyncSession]:
    """Yield a DB-session placeholder for preparation-only unit tests."""
    yield AsyncMock(spec=AsyncSession)


async def test_prepare_attachment_creates_model_file_part_before_fifo_lock() -> None:
    """An attachment-only buffer gains rich input during external preparation."""
    session_id = "session-001"
    user_id = "user-001"
    agent_id = "agent-001"
    attachment_uri = "exchange://exchange/workspace-001/session/image.png"
    buffer = InputBuffer(
        id="buffer-001",
        session_id=session_id,
        kind=InputBufferKind.USER_MESSAGE,
        scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        requested_model_target_label="Quality",
        requested_reasoning_effort=None,
        sender_user_id=None,
        content="inspect the image",
        idempotency_key="request-001",
        metadata={"source": "chat"},
        action=None,
        attachments=[attachment_uri],
        file_parts=[],
        created_at=tznow(),
    )
    exchange_file = _exchange_file(
        file_id="1234567890abcdef1234567890abcdef",
        user_id=user_id,
        object_key=attachment_uri.removeprefix("exchange://"),
    )
    exchange_file_service = _ExchangeFileService(
        Success(exchange_file),
        Success(ExchangeFileDownload(file=exchange_file, body=b"image")),
    )
    model_file = ModelFile(
        id="model-file-from-attachment",
        workspace_id="workspace-001",
        session_id=session_id,
        agent_id=agent_id,
        name="image.jpg",
        media_type="image/jpeg",
        kind="image",
        size_bytes=5,
        created_run_index=1,
        storage_key="model-files/image.jpg",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="jpeg",
        sha256="sha256",
        metadata={"source_kind": "user_upload"},
        created_at=tznow(),
    )
    model_file_service = _ModelFileService(Success(model_file))
    input_buffer_repository = AsyncMock(spec=InputBufferRepository)
    input_buffer_repository.list_for_flush.return_value = [buffer]
    agent_session_repository = AsyncMock(spec=AgentSessionRepository)
    agent_session_repository.get_by_id.return_value = SimpleNamespace(agent_id=agent_id)
    service = InputBufferService(
        session_manager=cast(
            SessionManager[AsyncSession],
            _unit_session_manager,
        ),
        input_buffer_repository=cast(
            InputBufferRepository,
            input_buffer_repository,
        ),
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        event_transcript_repository=cast(
            EventTranscriptRepository,
            AsyncMock(spec=EventTranscriptRepository),
        ),
        agent_run_repository=cast(
            AgentRunRepository,
            AsyncMock(spec=AgentRunRepository),
        ),
        action_execution_repository=cast(
            ActionExecutionRepository,
            AsyncMock(spec=ActionExecutionRepository),
        ),
        external_channel_repository=cast(ExternalChannelRepository, object()),
        vfs_projection_service=None,
    )

    prepared = await service._prepare_input_buffer_attachments(  # pyright: ignore[reportPrivateUsage]  # Verify the pre-lock attachment preparation boundary directly.
        session_id=session_id,
        expected_buffer_id=buffer.id,
        include_action_messages=True,
    )

    assert prepared.attachments[0].uri == attachment_uri
    assert prepared.file_parts[0].model_file_id == model_file.id
    assert prepared.created_model_file_ids == [model_file.id]
    assert exchange_file_service.resolve_admitted_input_attachment_called
    assert model_file_service.create_for_admitted_input_called


async def test_admitted_attachment_download_failure_is_terminal() -> None:
    """A deterministic missing object becomes an unavailable attachment."""
    attachment_uri = "exchange://exchange/workspace-001/session/report.txt"
    exchange_file = _exchange_file(
        file_id="1234567890abcdef1234567890abcdef",
        user_id="user-001",
        object_key=attachment_uri.removeprefix("exchange://"),
    )
    exchange_file_service = _ExchangeFileService(
        Success(exchange_file),
        Failure(FileNotFound()),
    )
    model_file_service = _ModelFileService()

    materialized = await materialize_admitted_input_exchange_file_attachments(
        [attachment_uri],
        agent_id="agent-001",
        session_id="session-001",
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
    )

    assert materialized.file_parts == []
    assert materialized.attachments[0].availability == "unavailable"
    assert not model_file_service.create_for_admitted_input_called


@pytest.mark.parametrize(
    "error",
    [
        ModelFileOversized(max_bytes=4, actual_bytes=5),
        ModelFileInvalidImage(),
    ],
)
async def test_admitted_attachment_model_file_failure_is_terminal(
    error: ModelFileCreateError,
) -> None:
    """Deterministic rich-input conversion failures do not request retry."""
    attachment_uri = "exchange://exchange/workspace-001/session/report.txt"
    exchange_file = _exchange_file(
        file_id="1234567890abcdef1234567890abcdef",
        user_id="user-001",
        object_key=attachment_uri.removeprefix("exchange://"),
    )
    materialized = await materialize_admitted_input_exchange_file_attachments(
        [attachment_uri],
        agent_id="agent-001",
        session_id="session-001",
        exchange_file_service=_ExchangeFileService(
            Success(exchange_file),
            Success(ExchangeFileDownload(file=exchange_file, body=b"input")),
        ),
        model_file_service=_ModelFileService(Failure(error)),
    )

    assert materialized.file_parts == []
    assert materialized.attachments[0].availability == "available"


async def test_prepare_skips_deferred_action_attachment_materialization() -> None:
    """A deferred action does not create unreferenced ModelFiles."""
    session_id = "session-001"
    buffer = InputBuffer(
        id="buffer-001",
        session_id=session_id,
        kind=InputBufferKind.ACTION_MESSAGE,
        scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        requested_model_target_label="Quality",
        requested_reasoning_effort=None,
        sender_user_id="user-001",
        content="deferred action",
        idempotency_key="request-001",
        metadata={"source": "chat"},
        action=GoalAction().model_dump(mode="json"),
        attachments=["exchange://exchange/workspace-001/session/image.png"],
        file_parts=[],
        created_at=tznow(),
    )
    input_buffer_repository = AsyncMock(spec=InputBufferRepository)
    input_buffer_repository.list_for_flush.return_value = [buffer]
    agent_session_repository = AsyncMock(spec=AgentSessionRepository)
    agent_session_repository.get_by_id.return_value = SimpleNamespace(
        agent_id="agent-001"
    )
    exchange_file_service = _ExchangeFileService()
    model_file_service = _ModelFileService()
    service = InputBufferService(
        session_manager=cast(
            SessionManager[AsyncSession],
            _unit_session_manager,
        ),
        input_buffer_repository=cast(
            InputBufferRepository,
            input_buffer_repository,
        ),
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        event_transcript_repository=cast(
            EventTranscriptRepository,
            AsyncMock(spec=EventTranscriptRepository),
        ),
        agent_run_repository=cast(
            AgentRunRepository,
            AsyncMock(spec=AgentRunRepository),
        ),
        action_execution_repository=cast(
            ActionExecutionRepository,
            AsyncMock(spec=ActionExecutionRepository),
        ),
        external_channel_repository=cast(ExternalChannelRepository, object()),
        vfs_projection_service=None,
    )

    prepared = await service._prepare_input_buffer_attachments(  # pyright: ignore[reportPrivateUsage]  # Verify deferred actions skip external preparation.
        session_id=session_id,
        expected_buffer_id=buffer.id,
        include_action_messages=False,
    )

    assert prepared.attachments == []
    assert prepared.file_parts == []
    assert prepared.created_model_file_ids == []
    assert not exchange_file_service.resolve_attachment_metadata_for_agent_called
    assert not model_file_service.create_for_agent_pending_input_called


async def test_cancelled_promotion_discards_prepared_model_files() -> None:
    """Cancellation preserves the signal after shielded ModelFile cleanup."""
    model_file_service = _ModelFileService()
    service = InputBufferService(
        session_manager=cast(SessionManager[AsyncSession], object()),
        input_buffer_repository=cast(InputBufferRepository, object()),
        exchange_file_service=cast(ExchangeFileService, object()),
        model_file_service=model_file_service,
        agent_session_repository=cast(AgentSessionRepository, object()),
        event_transcript_repository=cast(EventTranscriptRepository, object()),
        agent_run_repository=cast(AgentRunRepository, object()),
        action_execution_repository=cast(ActionExecutionRepository, object()),
        external_channel_repository=cast(ExternalChannelRepository, object()),
        vfs_projection_service=None,
    )
    prepared = PreparedInputBufferFiles(
        attachments=[],
        file_parts=[],
        created_model_file_ids=["model-file-1"],
    )

    with pytest.raises(asyncio.CancelledError):
        async with service._discard_prepared_model_files_on_failure(  # pyright: ignore[reportPrivateUsage]  # Verify cancellation compensation directly.
            prepared
        ):
            raise asyncio.CancelledError

    assert model_file_service.discarded_model_file_ids == ["model-file-1"]


async def test_cancelled_attachment_preparation_discards_partial_model_files() -> None:
    """Cancellation during a later attachment discards earlier ModelFiles."""
    attachment_uri = "exchange://exchange/workspace-001/session/image.png"
    exchange_file = _exchange_file(
        file_id="1234567890abcdef1234567890abcdef",
        user_id="user-001",
        object_key=attachment_uri.removeprefix("exchange://"),
    )
    exchange_file_service = _CancellingSecondAttachmentExchangeFileService(
        metadata_result=Success(exchange_file),
        download_result=Success(
            ExchangeFileDownload(file=exchange_file, body=b"image")
        ),
    )
    model_file = ModelFile(
        id="model-file-from-first-attachment",
        workspace_id="workspace-001",
        session_id="session-001",
        agent_id="agent-001",
        name="image.jpg",
        media_type="image/jpeg",
        kind="image",
        size_bytes=5,
        created_run_index=1,
        storage_key="model-files/image.jpg",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="jpeg",
        sha256="sha256",
        metadata={"source_kind": "user_upload"},
        created_at=tznow(),
    )
    model_file_service = _ModelFileService(Success(model_file))

    with pytest.raises(asyncio.CancelledError):
        await materialize_admitted_input_exchange_file_attachments(
            [attachment_uri, f"{attachment_uri}.second"],
            agent_id="agent-001",
            session_id="session-001",
            exchange_file_service=exchange_file_service,
            model_file_service=model_file_service,
        )

    assert model_file_service.discarded_model_file_ids == [model_file.id]


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
                    scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    sender_user_id=user_id,
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

    async def test_pending_queries_separate_mailbox_from_wake_intent(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Queue-only mailbox input is pending without requesting a wake."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-pending-query",
        )
        await _create_agent_message_buffer(
            rdb_session_manager,
            session_id=session_id,
            content="queued note",
            scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
        )
        service = _input_buffer_service(rdb_session_manager)

        assert await service.has_pending_session_input_buffers(session_id)
        assert await service.has_pending_agent_messages(session_id)
        assert not await service.has_pending_wake_session_input_buffers(session_id)

        await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="wake now",
        )

        assert await service.has_pending_wake_session_input_buffers(session_id)

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
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
            requested_model_target_label="Quality",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            sender_user_id=user_id,
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
                match="idempotency key already used for another scheduling mode",
            ):
                await service.enqueue(
                    session,
                    dataclasses.replace(
                        enqueue,
                        scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
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
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
            requested_model_target_label="Fast",
            requested_reasoning_effort=ModelReasoningEffort.LOW,
            sender_user_id="user-001",
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
            vfs_projection_service=None,
            external_channel_repository=ExternalChannelRepository(),
        )
        enqueue = InputBufferEnqueue(
            session_id="session-001",
            kind=InputBufferKind.USER_MESSAGE,
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
            requested_model_target_label="Quality",
            requested_reasoning_effort=ModelReasoningEffort.HIGH,
            sender_user_id="user-001",
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
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
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
                owner_generation=0,
                model="gpt-5.4",
                required_inference_profile=None,
                expected_buffer_id="another-buffer",
                prepared_inference_state=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )

        async with rdb_session_manager() as session:
            remaining = await InputBufferRepository().get_by_id(session, buffer_id)
        assert remaining is not None

    async def test_flush_rejects_superseded_owner_generation(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A stale Worker cannot promote the current owner's FIFO head."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-stale-owner",
        )
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="keep pending",
            model_target_label="Quality",
            reasoning_effort=None,
        )

        with pytest.raises(InputBufferOwnerGenerationStaleError):
            await _input_buffer_service(
                rdb_session_manager
            ).flush_session_input_buffers(
                session_id=session_id,
                owner_generation=1,
                model="gpt-5.4",
                required_inference_profile=None,
                expected_buffer_id=buffer_id,
                prepared_inference_state=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )

        async with rdb_session_manager() as session:
            remaining = await InputBufferRepository().get_by_id(session, buffer_id)
        assert remaining is not None

    async def test_flush_resolves_attachments_before_locking_fifo_head(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Attachment resolution cannot self-deadlock on the claimed buffer."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-attachment-revalidation",
        )
        attachment_uri = "exchange://exchange/workspace-001/session/report.txt"
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="resolve before lock",
            attachments=[attachment_uri],
        )
        exchange_file = _exchange_file(
            file_id="1234567890abcdef1234567890abcdef",
            user_id=user_id,
            object_key=attachment_uri.removeprefix("exchange://"),
        )
        exchange_file_service = _DeletingExchangeFileService(
            session_manager=rdb_session_manager,
            session_id=session_id,
            buffer_id=buffer_id,
            metadata_result=Success(exchange_file),
            download_result=Success(
                ExchangeFileDownload(file=exchange_file, body=b"hello world")
            ),
        )
        model_file = ModelFile(
            id="model-file-created-before-stale-lock",
            workspace_id="workspace-001",
            session_id=session_id,
            agent_id=await _agent_id_for_session(
                rdb_session_manager,
                session_id,
            ),
            name="report.txt",
            media_type="text/plain",
            kind="text",
            size_bytes=11,
            created_run_index=1,
            storage_key="model-files/report.txt",
            status=ModelFileStatus.AVAILABLE,
            normalized_format="original",
            sha256="sha256",
            metadata={"source_kind": "user_upload"},
            created_at=tznow(),
        )
        model_file_service = _ModelFileService(Success(model_file))
        service = _input_buffer_service(
            rdb_session_manager,
            exchange_file_service=exchange_file_service,
            model_file_service=model_file_service,
        )

        with pytest.raises(InputBufferPreparationStaleError):
            async with asyncio.timeout(2):
                await service.flush_session_input_buffers(
                    session_id=session_id,
                    owner_generation=0,
                    model="gpt-5.4",
                    required_inference_profile=None,
                    expected_buffer_id=buffer_id,
                    prepared_inference_state=None,
                    profile_resolution_failure=None,
                    active_run_id=None,
                )
        assert model_file_service.discarded_model_file_ids == [model_file.id]

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
            model_settings=make_test_model_settings(),
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
                owner_generation=0,
                model="prepared-model",
                required_inference_profile=RequestedInferenceProfile(
                    model_target_label="Fast",
                    reasoning_effort=ModelReasoningEffort.HIGH,
                ),
                expected_buffer_id=buffer_id,
                prepared_inference_state=prepared_state,
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
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Quality",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
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
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=first_id,
            prepared_inference_state=None,
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
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=None,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
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
        session_id, _user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-message",
        )
        buffer_id = await _create_agent_message_buffer(
            rdb_session_manager,
            session_id=session_id,
            content="continue with the next step",
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        )
        service = _input_buffer_service(rdb_session_manager)

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
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

    async def test_flush_promotes_and_acknowledges_agent_result(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Promotion persists metadata and advances the direct child cursor."""
        session_id, _user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-result",
        )
        parent_id, child_id = await _create_child_session_agent(
            rdb_session_manager,
            parent_session_id=session_id,
        )
        terminal_event_id = "terminal-event".rjust(32, "0")
        source_run_id, source_run_index = await _create_terminal_child_run(
            rdb_session_manager,
            child_session_agent_id=child_id,
            terminal_result_event_id=terminal_event_id,
        )
        buffer_id = await _create_agent_result_buffer(
            rdb_session_manager,
            session_id=session_id,
            content="No blocking issues.",
            source_session_agent_id=child_id,
            target_session_agent_id=parent_id,
            source_run_id=source_run_id,
            source_run_index=source_run_index,
            source_terminal_result_event_id=terminal_event_id,
        )

        result = await _input_buffer_service(
            rdb_session_manager
        ).flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        event = result.events[0]
        assert event.kind == EventKind.AGENT_MESSAGE
        assert isinstance(event.payload, AgentMessagePayload)
        assert event.payload.message_kind == "agent_result"
        assert event.payload.source_run_id == source_run_id
        assert event.payload.source_run_index == source_run_index
        assert event.payload.run_status is AgentRunStatus.COMPLETED
        assert event.payload.source_terminal_result_event_id == terminal_event_id
        assert event.payload.content == "No blocking issues."
        assert result.changed_session_agent_ids == [child_id]
        async with rdb_session_manager() as session:
            child = await AgentSessionRepository().get_session_agent_by_id(
                session,
                child_id,
            )
        assert child is not None
        assert child.parent_observed_run_index == source_run_index
        assert child.parent_observed_event_id == terminal_event_id

    async def test_agent_result_acknowledgment_is_monotonic(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Older terminal results cannot regress a consumed child cursor."""
        session_id, _user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-result-monotonic",
        )
        parent_id, child_id = await _create_child_session_agent(
            rdb_session_manager,
            parent_session_id=session_id,
        )
        service = _input_buffer_service(rdb_session_manager)
        runs: dict[int, tuple[str, str]] = {}
        for expected_run_index in (1, 2, 3):
            terminal_event_id = str(expected_run_index + 100).rjust(32, "0")
            source_run_id, source_run_index = await _create_terminal_child_run(
                rdb_session_manager,
                child_session_agent_id=child_id,
                terminal_result_event_id=terminal_event_id,
            )
            assert source_run_index == expected_run_index
            runs[source_run_index] = (source_run_id, terminal_event_id)

        async def promote(source_run_index: int) -> list[str]:
            source_run_id, terminal_event_id = runs[source_run_index]
            buffer_id = await _create_agent_result_buffer(
                rdb_session_manager,
                session_id=session_id,
                content=f"Result {source_run_index}",
                source_session_agent_id=child_id,
                target_session_agent_id=parent_id,
                source_run_id=source_run_id,
                source_run_index=source_run_index,
                source_terminal_result_event_id=terminal_event_id,
            )
            result = await service.flush_session_input_buffers(
                session_id=session_id,
                owner_generation=0,
                model="gpt-5.4",
                required_inference_profile=None,
                expected_buffer_id=buffer_id,
                prepared_inference_state=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )
            return result.changed_session_agent_ids

        assert await promote(2) == [child_id]
        assert await promote(1) == []
        assert await promote(3) == [child_id]
        async with rdb_session_manager() as session:
            child = await AgentSessionRepository().get_session_agent_by_id(
                session,
                child_id,
            )
        assert child is not None
        assert child.parent_observed_run_index == 3
        assert child.parent_observed_event_id == str(103).rjust(32, "0")

    async def test_agent_result_acknowledgment_requires_direct_parent(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A payload cannot acknowledge a child outside its direct parent."""
        session_id, _user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-result-parent-scope",
        )
        _parent_id, child_id = await _create_child_session_agent(
            rdb_session_manager,
            parent_session_id=session_id,
        )
        terminal_event_id = "misdirected-event".rjust(32, "0")
        source_run_id, source_run_index = await _create_terminal_child_run(
            rdb_session_manager,
            child_session_agent_id=child_id,
            terminal_result_event_id=terminal_event_id,
        )
        buffer_id = await _create_agent_result_buffer(
            rdb_session_manager,
            session_id=session_id,
            content="Misdirected result",
            source_session_agent_id=child_id,
            target_session_agent_id="another-parent",
            source_run_id=source_run_id,
            source_run_index=source_run_index,
            source_terminal_result_event_id=terminal_event_id,
        )

        result = await _input_buffer_service(
            rdb_session_manager
        ).flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.changed_session_agent_ids == []
        async with rdb_session_manager() as session:
            child = await AgentSessionRepository().get_session_agent_by_id(
                session,
                child_id,
            )
        assert child is not None
        assert child.parent_observed_run_index is None
        assert child.parent_observed_event_id is None

    async def test_agent_result_acknowledgment_requires_matching_terminal_run(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Tampered terminal metadata cannot advance the child cursor."""
        session_id, _user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-result-run-scope",
        )
        parent_id, child_id = await _create_child_session_agent(
            rdb_session_manager,
            parent_session_id=session_id,
        )
        terminal_event_id = "verified-event".rjust(32, "0")
        source_run_id, source_run_index = await _create_terminal_child_run(
            rdb_session_manager,
            child_session_agent_id=child_id,
            terminal_result_event_id=terminal_event_id,
        )
        buffer_id = await _create_agent_result_buffer(
            rdb_session_manager,
            session_id=session_id,
            content="Tampered result",
            source_session_agent_id=child_id,
            target_session_agent_id=parent_id,
            source_run_id=source_run_id,
            source_run_index=source_run_index + 100,
            source_terminal_result_event_id=terminal_event_id,
        )

        result = await _input_buffer_service(
            rdb_session_manager
        ).flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.changed_session_agent_ids == []
        async with rdb_session_manager() as session:
            child = await AgentSessionRepository().get_session_agent_by_id(
                session,
                child_id,
            )
        assert child is not None
        assert child.parent_observed_run_index is None
        assert child.parent_observed_event_id is None

    async def test_agent_result_acknowledgment_rolls_back_with_promotion(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed promotion cannot commit its child observation cursor."""
        session_id, _user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-agent-result-rollback",
        )
        parent_id, child_id = await _create_child_session_agent(
            rdb_session_manager,
            parent_session_id=session_id,
        )
        terminal_event_id = "rollback-event".rjust(32, "0")
        source_run_id, source_run_index = await _create_terminal_child_run(
            rdb_session_manager,
            child_session_agent_id=child_id,
            terminal_result_event_id=terminal_event_id,
        )
        buffer_id = await _create_agent_result_buffer(
            rdb_session_manager,
            session_id=session_id,
            content="Rollback result",
            source_session_agent_id=child_id,
            target_session_agent_id=parent_id,
            source_run_id=source_run_id,
            source_run_index=source_run_index,
            source_terminal_result_event_id=terminal_event_id,
        )
        service = _input_buffer_service(rdb_session_manager)
        monkeypatch.setattr(
            service.input_buffer_repository,
            "delete_claimed_by_ids",
            AsyncMock(side_effect=RuntimeError("delete failed")),
        )

        with pytest.raises(RuntimeError, match="delete failed"):
            await service.flush_session_input_buffers(
                session_id=session_id,
                owner_generation=0,
                model="gpt-5.4",
                required_inference_profile=None,
                expected_buffer_id=buffer_id,
                prepared_inference_state=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )

        async with rdb_session_manager() as session:
            child = await AgentSessionRepository().get_session_agent_by_id(
                session,
                child_id,
            )
            remaining = await InputBufferRepository().get_by_id(session, buffer_id)
        assert child is not None
        assert child.parent_observed_run_index is None
        assert child.parent_observed_event_id is None
        assert remaining is not None

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
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
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

    async def test_flush_managed_skill_action_uses_active_run_vfs(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Managed Skill action snapshots the exact current run VFS body."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-managed-skill-action",
        )
        async with rdb_session_manager() as session:
            run = await AgentRunRepository().create_pending(
                session,
                session_id=session_id,
                parent_agent_run_id=None,
            )
        uri = "azents://skills/azents/review/SKILL.md"
        buffer_id = await _create_action_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="Review this change",
            action=SkillAction(skill_path=uri),
        )
        vfs_service = _VfsService()
        service = _input_buffer_service(
            rdb_session_manager,
            vfs_projection_service=vfs_service,
        )

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=RequestedInferenceProfile(
                model_target_label="Fast",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=run.id,
        )

        assert vfs_service.run_ids == [run.id]
        assert [event.kind for event in result.events] == [
            EventKind.SKILL_LOADED,
            EventKind.USER_MESSAGE,
        ]
        skill_event = result.events[0]
        assert isinstance(skill_event.payload, SkillLoadedPayload)
        assert skill_event.payload.skill_path == uri
        assert skill_event.payload.body.endswith("Managed body")
        projected_entry = vfs_service.projection.find(uri)
        assert projected_entry is not None
        assert skill_event.payload.content_hash == projected_entry.content_hash

    async def test_flush_preserves_exchange_attachment_payload(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Attachment promotion also creates rich model input FilePart."""
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
        exchange_file = _exchange_file(
            file_id=file_id,
            user_id=user_id,
            object_key=attachment_uri.removeprefix("exchange://"),
            preview_thumbnail_file_id=thumbnail_file_id,
            preview_thumbnail_uri=thumbnail_uri,
        )
        exchange_file_service = _ExchangeFileService(
            Success(exchange_file),
            Success(ExchangeFileDownload(file=exchange_file, body=b"hello world")),
        )
        model_file = ModelFile(
            id="model-file-from-attachment",
            workspace_id="workspace-001",
            session_id=session_id,
            agent_id=await _agent_id_for_session(
                rdb_session_manager,
                session_id,
            ),
            name="report.txt",
            media_type="text/plain",
            kind="text",
            size_bytes=11,
            created_run_index=1,
            storage_key="model-files/report.txt",
            status=ModelFileStatus.AVAILABLE,
            normalized_format="original",
            sha256="sha256",
            metadata={"source_kind": "user_upload"},
            created_at=tznow(),
        )
        model_file_service = _ModelFileService(Success(model_file))
        service = _input_buffer_service(
            rdb_session_manager,
            exchange_file_service=exchange_file_service,
            model_file_service=model_file_service,
        )

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=attachment_buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        promoted = result.user_messages[0]
        assert isinstance(promoted.payload.content, list)
        promoted_file_part = promoted.payload.content[1]
        assert isinstance(promoted_file_part, FileOutputPart)
        assert promoted_file_part.model_file_id == model_file.id
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
        assert isinstance(payload.content, list)
        event_file_part = payload.content[1]
        assert isinstance(event_file_part, FileOutputPart)
        assert event_file_part.model_file_id == model_file.id
        assert payload.attachments[0].uri == attachment_uri
        assert payload.attachments[0].preview_thumbnail_uri == thumbnail_uri
        assert len(result.events) == 1
        assert result.events[0].id == event.id
        assert exchange_file_service.resolve_admitted_input_attachment_called
        assert model_file_service.create_for_admitted_input_called

    async def test_attachment_preparation_failure_preserves_buffer_for_retry(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """A transient admitted download failure leaves the FIFO input durable."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-attachment-retry",
        )
        attachment_uri = "exchange://exchange/workspace-001/session/retry.txt"
        buffer_id = await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="retry this attachment",
            attachments=[attachment_uri],
        )
        exchange_file = _exchange_file(
            file_id="fedcba0987654321fedcba0987654321",
            user_id=user_id,
            object_key=attachment_uri.removeprefix("exchange://"),
        )
        exchange_file_service = _ExchangeFileService(
            Success(exchange_file),
            Success(ExchangeFileDownload(file=exchange_file, body=b"retry")),
        )
        exchange_file_service.admitted_download_exception = RuntimeError(
            "temporary object storage outage"
        )
        model_file = ModelFile(
            id="model-file-from-retried-attachment",
            workspace_id="workspace-001",
            session_id=session_id,
            agent_id=await _agent_id_for_session(
                rdb_session_manager,
                session_id,
            ),
            name="retry.txt",
            media_type="text/plain",
            kind="text",
            size_bytes=5,
            created_run_index=1,
            storage_key="model-files/retry.txt",
            status=ModelFileStatus.AVAILABLE,
            normalized_format="original",
            sha256="sha256",
            metadata={"source_kind": "user_upload"},
            created_at=tznow(),
        )
        model_file_service = _ModelFileService(Success(model_file))
        service = _input_buffer_service(
            rdb_session_manager,
            exchange_file_service=exchange_file_service,
            model_file_service=model_file_service,
        )

        with pytest.raises(RuntimeError, match="temporary object storage outage"):
            await service.flush_session_input_buffers(
                session_id=session_id,
                owner_generation=0,
                model="gpt-5.4",
                required_inference_profile=None,
                expected_buffer_id=buffer_id,
                prepared_inference_state=None,
                profile_resolution_failure=None,
                active_run_id=None,
            )
        async with rdb_session_manager() as session:
            preserved = await InputBufferRepository().get_by_id(session, buffer_id)
        assert preserved is not None

        exchange_file_service.admitted_download_exception = None
        promoted = await service.flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert promoted.deleted_buffer_ids == [buffer_id]
        assert promoted.user_messages[0].payload.attachments[0].uri == attachment_uri
        async with rdb_session_manager() as session:
            consumed = await InputBufferRepository().get_by_id(session, buffer_id)
        assert consumed is None

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

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=image_buffer_id,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        promoted = result.user_messages[0]
        assert isinstance(promoted.payload.content, list)
        assert promoted.payload.content[1] == existing_part
        assert not model_file_service.create_for_admitted_input_called
        assert (
            not exchange_file_service.resolve_admitted_input_attachment_metadata_called
        )
        assert not exchange_file_service.resolve_admitted_input_attachment_called

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
            owner_generation=0,
            model="gpt-5.4",
            required_inference_profile=None,
            expected_buffer_id=None,
            prepared_inference_state=None,
            profile_resolution_failure=None,
            active_run_id=None,
        )

        assert result.claimed_count == 0
        assert result.user_messages == []
        assert result.events == []


async def test_external_invocation_projection() -> None:
    """Project one batch contiguously with an authorized trigger boundary."""

    def at(second: int) -> datetime.datetime:
        return datetime.datetime(
            2026,
            7,
            22,
            0,
            0,
            second,
            tzinfo=datetime.UTC,
        )

    source_attachment_metadata: dict[str, object] = {
        "files": [
            {
                "provider": "slack",
                "provider_file_id": "F123",
                "name": "report.csv",
                "title": "Report",
                "media_type": "text/csv",
                "declared_size": 1024,
                "mode": "hosted",
                "external": False,
                "file_access": None,
                "supported": True,
                "unsupported_reason": None,
            }
        ],
        "files_truncated": False,
    }

    class _ProjectionRepository:
        async def list_invocation_projection_items(
            self,
            session: AsyncSession,
            *,
            batch_id: str,
        ) -> list[ExternalChannelInvocationProjectionItem]:
            del session
            assert batch_id == "batch-1"
            first = ExternalChannelInvocationProjectionItem(
                batch_id="batch-1",
                binding_id="binding-1",
                trigger_message_id="message-2",
                truncation_message_count=2,
                truncation_size=128,
                sequence=0,
                message_id="message-1",
                revision_id="revision-1",
                revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
                revision_body="Context",
                attachment_metadata=source_attachment_metadata,
                reference_mappings=None,
                provider_occurred_at=at(1),
                resource_id="resource-1",
                provider_resource_key="C123:1.0",
                resource_type=ExternalChannelResourceType.THREAD,
                resource_labels={"channel_id": "C123", "thread_ts": "1.0"},
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="T1",
                provider_message_key="C123:1.0:1",
                provider_position="1",
                principal_id="principal-1",
                provider_user_id="U1",
                sender_display_name="Alice",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                provider_created_at=at(1),
                provider_updated_at=None,
                original_url="https://slack.example/message",
                correction_of_revision_id=None,
            )
            return [
                first,
                first.model_copy(
                    update={
                        "sequence": 1,
                        "message_id": "message-2",
                        "revision_id": "revision-2",
                        "revision_body": "Invoke",
                        "provider_message_key": "C123:1.0:2",
                        "provider_position": "2",
                        "provider_occurred_at": at(2),
                        "provider_created_at": at(2),
                    }
                ),
            ]

    input_buffer = InputBuffer(
        id="buffer-1",
        session_id="session-1",
        kind=InputBufferKind.EXTERNAL_CHANNEL_INVOCATION,
        scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        sender_user_id=None,
        content="",
        idempotency_key="external-channel-invocation:batch-1",
        metadata={EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY: "batch-1"},
        action=None,
        attachments=[],
        file_parts=[],
        created_at=at(0),
    )
    service = cast(
        InputBufferService,
        SimpleNamespace(external_channel_repository=_ProjectionRepository()),
    )
    processor = ExternalChannelInvocationInputBufferProcessor(service)

    outcome = await processor.process(
        InputBufferPreparationContext(
            session=cast(AsyncSession, object()),
            session_id="session-1",
            active_run_id=None,
            required_inference_profile=None,
            prepared_inference_state=None,
            prepared_files=PreparedInputBufferFiles(
                attachments=[],
                file_parts=[],
                created_model_file_ids=[],
            ),
        ),
        input_buffer,
    )

    assert outcome.turn_effect is TurnEffect.ELIGIBLE
    assert [item.external_id for item in outcome.promoted] == [
        "external-channel:binding-1:message-1:revision-1",
        "external-channel:binding-1:message-2:revision-2",
    ]
    assert outcome.promoted[0].payload["authorization"] == "context_only"
    assert outcome.promoted[1].payload["authorization"] == "authorized_invocation"
    assert outcome.promoted[0].payload["invocation_batch_id"] == "batch-1"
    projected_metadata = outcome.promoted[0].payload["attachment_metadata"]
    assert isinstance(projected_metadata, dict)
    projected_files = projected_metadata["files"]
    assert isinstance(projected_files, list)
    assert isinstance(projected_files[0], dict)
    assert projected_files[0]["file"] == "external-file:v1:slack:binding-1:F123"
    source_files = source_attachment_metadata["files"]
    assert isinstance(source_files, list)
    assert isinstance(source_files[0], dict)
    assert "file" not in source_files[0]
