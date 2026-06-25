"""InputBufferService tests."""

import datetime

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionRunState,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    InputBufferKind,
    LLMProvider,
)
from azents.engine.events.types import FileOutputPart, UserMessagePayload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.input_buffer import RDBInputBuffer
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBufferCreate
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

from .input_buffer import InputBufferEnqueue, InputBufferService


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
        agent_session = await AgentSessionRepository().ensure_active(
            session,
            runtime.id,
        )
        return agent_session.id, user.id


async def _create_buffer(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    session_id: str,
    user_id: str,
    content: str,
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
                actor_user_id=user_id,
                content=content,
                idempotency_key=None,
                metadata={"source": "chat"},
                attachments=attachments if attachments is not None else [],
                file_parts=file_parts if file_parts is not None else [],
            ),
        )
        return created.id


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
) -> InputBufferService:
    """Create InputBufferService for tests."""
    return InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=exchange_file_service or _ExchangeFileService(),
        model_file_service=model_file_service or _ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
    )


class TestInputBufferService:
    """Validate InputBufferService behavior."""

    async def test_enqueue_creates_buffer_and_marks_session_running(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Enqueue owns both pending row creation and running transition."""
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
                    actor_user_id=user_id,
                    content="wake me",
                    idempotency_key="client-request-001",
                    metadata={"source": "test"},
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
        assert after.run_state == AgentSessionRunState.RUNNING

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
        )
        service = _input_buffer_service(rdb_session_manager)

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
        )

        assert result.claimed_count == 1
        assert result.inserted_count == 1
        assert result.deduped_count == 0
        assert len(result.user_messages) == 1
        assert len(result.events) == 1
        assert result.events[0].external_id == buffer_id
        promoted = result.user_messages[0]
        assert promoted.external_id == buffer_id
        assert promoted.payload.content == "buffered message"
        async with rdb_session_manager() as session:
            remaining = await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBInputBuffer)
                .where(RDBInputBuffer.id == buffer_id)
            )
        assert remaining == 0

    async def test_flush_preserves_exchange_attachment_payload(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Attachment URI is restored as same event payload as direct path."""
        session_id, user_id = await _create_fixture(
            rdb_session_manager,
            "input-buffer-promote-attachment",
        )
        file_id = "1234567890abcdef1234567890abcdef"
        thumbnail_file_id = "abcdef1234567890abcdef1234567890"
        attachment_uri = "exchange://exchange/workspace-001/session/report.txt"
        thumbnail_uri = "exchange://exchange/workspace-001/previews/report-thumb.jpg"
        await _create_buffer(
            rdb_session_manager,
            session_id=session_id,
            user_id=user_id,
            content="buffered with file",
            attachments=[attachment_uri],
        )
        exchange_file_service = _ExchangeFileService(
            Success(
                _exchange_file(
                    file_id=file_id,
                    user_id=user_id,
                    object_key=attachment_uri.removeprefix("exchange://"),
                    preview_thumbnail_file_id=thumbnail_file_id,
                    preview_thumbnail_uri=thumbnail_uri,
                )
            )
        )
        service = _input_buffer_service(
            rdb_session_manager,
            exchange_file_service=exchange_file_service,
        )

        result = await service.flush_session_input_buffers(
            session_id=session_id,
            model="gpt-5.4",
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
        await _create_buffer(
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
            model="gpt-5.4",
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
        )

        assert result.claimed_count == 0
        assert result.user_messages == []
        assert result.events == []
