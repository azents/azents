"""ExchangeFileService tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentType,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    WorkspaceUserRole,
)
from azents.repos.agent.data import Agent
from azents.repos.agent_session.data import AgentSession
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.workspace_user.data import WorkspaceUser
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)

from . import (
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileUnavailable,
    SessionNotFound,
    exchange_object_key_from_uri,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


class _FakeExchangeFileRepository:
    """ExchangeFile repository for tests."""

    def __init__(self) -> None:
        self.files: dict[str, ExchangeFile] = {}
        self.next_id = 1
        self.fail_create = False

    async def create(
        self,
        session: AsyncSession,
        create: ExchangeFileCreate,
    ) -> ExchangeFile:
        """Store create input as domain model as-is."""
        del session
        if self.fail_create:
            msg = "metadata write failed"
            raise RuntimeError(msg)
        file_id = create.id or f"{self.next_id:032x}"
        self.next_id += 1
        file = ExchangeFile(
            id=file_id,
            workspace_id=create.workspace_id,
            agent_id=create.agent_id,
            origin_type=create.origin_type,
            status=ExchangeFileStatus.AVAILABLE,
            object_key=f"exchange/{create.workspace_id}/files/{file_id}/original",
            filename=create.filename,
            media_type=create.media_type,
            size_bytes=create.size_bytes,
            sha256=create.sha256,
            created_by_user_id=create.created_by_user_id,
            preview_thumbnail_file_id=None,
            preview_thumbnail_uri=None,
            preview_title=create.preview_title,
            preview_summary=create.preview_summary,
            preview_thumbnail_media_type=create.preview_thumbnail_media_type,
            preview_thumbnail_width=create.preview_thumbnail_width,
            preview_thumbnail_height=create.preview_thumbnail_height,
            preview_generated_at=create.preview_generated_at,
            expires_at=create.expires_at,
            expired_at=None,
            blob_deleted_at=None,
            created_at=_NOW,
        )
        self.files[file.id] = file
        return file

    async def get_by_id(
        self,
        session: AsyncSession,
        file_id: str,
    ) -> ExchangeFile | None:
        """Fetch file by ID."""
        del session
        return self.files.get(file_id)

    async def get_by_object_key(
        self,
        session: AsyncSession,
        object_key: str,
    ) -> ExchangeFile | None:
        """Fetch file by object key."""
        del session
        for file in self.files.values():
            if file.object_key == object_key:
                return file
        return None

    async def delete_by_id(
        self,
        session: AsyncSession,
        file_id: str,
    ) -> None:
        """Delete file metadata."""
        del session
        self.files.pop(file_id, None)

    async def set_preview_thumbnail_file_id(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        preview_thumbnail_file_id: str,
        preview_thumbnail_media_type: str,
        preview_thumbnail_width: int,
        preview_thumbnail_height: int,
        preview_generated_at: datetime.datetime,
    ) -> ExchangeFile:
        """Link preview thumbnail to original file."""
        del session
        file = self.files[file_id]
        updated = file.model_copy(
            update={
                "preview_thumbnail_file_id": preview_thumbnail_file_id,
                "preview_thumbnail_uri": self.files[preview_thumbnail_file_id].uri,
                "preview_thumbnail_media_type": preview_thumbnail_media_type,
                "preview_thumbnail_width": preview_thumbnail_width,
                "preview_thumbnail_height": preview_thumbnail_height,
                "preview_generated_at": preview_generated_at,
            }
        )
        self.files[file_id] = updated
        return updated

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[ExchangeFile]:
        """Mark expiration-target file as expired."""
        del session
        expired: list[ExchangeFile] = []
        for file in list(self.files.values()):
            if len(expired) >= limit:
                break
            if file.status == ExchangeFileStatus.AVAILABLE and file.expires_at <= now:
                updated = file.model_copy(
                    update={
                        "status": ExchangeFileStatus.EXPIRED,
                        "expired_at": now,
                    }
                )
                self.files[file.id] = updated
                expired.append(updated)
        return expired

    async def expire_file_family(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        expired_at: datetime.datetime,
    ) -> list[ExchangeFile]:
        """Mark original and preview thumbnail as expired."""
        del session
        file = self.files.get(file_id)
        if file is None:
            return []
        ids = [file.id]
        if file.preview_thumbnail_file_id is not None:
            ids.append(file.preview_thumbnail_file_id)
        expired: list[ExchangeFile] = []
        for id_ in ids:
            current = self.files[id_]
            updated = current.model_copy(
                update={
                    "status": ExchangeFileStatus.EXPIRED,
                    "expired_at": expired_at,
                }
            )
            self.files[id_] = updated
            expired.append(updated)
        return expired

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record successful object deletion before metadata removal."""
        del session
        current = self.files.get(file_id)
        if current is not None:
            self.files[file_id] = current.model_copy(
                update={"blob_deleted_at": blob_deleted_at}
            )


class _FakeS3Service:
    """S3 service for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.fail_delete = False
        self.fail_delete_at: int | None = None
        self.delete_attempt_count = 0
        self.fail_upload_after_write_at: int | None = None
        self.upload_count = 0
        self.session_tracker: _SessionTracker | None = None
        self.after_upload: Callable[[], None] | None = None

    def _assert_no_active_session(self) -> None:
        """Ensure external I/O never runs while a DB session is open."""
        if self.session_tracker is not None:
            assert self.session_tracker.active_sessions == 0

    async def upload(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        """Store object."""
        del bucket, content_type
        self._assert_no_active_session()
        self.upload_count += 1
        self.objects[key] = body
        if self.after_upload is not None:
            self.after_upload()
        if self.fail_upload_after_write_at == self.upload_count:
            msg = "upload failed after write"
            raise RuntimeError(msg)

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """Fetch object bytes."""
        del bucket
        self._assert_no_active_session()
        return self.objects.get(key)

    async def delete(self, bucket: str, key: str) -> None:
        """Delete object."""
        del bucket
        self._assert_no_active_session()
        self.delete_attempt_count += 1
        if self.fail_delete or self.fail_delete_at == self.delete_attempt_count:
            msg = "delete failed"
            raise RuntimeError(msg)
        self.deleted_keys.append(key)
        self.objects.pop(key, None)


class _SessionTracker:
    """Track open DB session scopes in service tests."""

    def __init__(
        self,
        *,
        exit_exception_call: int | None = None,
        exit_exception: BaseException | None = None,
    ) -> None:
        self.active_sessions = 0
        self.entries = 0
        self.exit_exception_call = exit_exception_call
        self.exit_exception = exit_exception

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield one fake session while tracking its lifetime."""
        self.entries += 1
        entry = self.entries
        self.active_sessions += 1
        try:
            yield cast(AsyncSession, object())
        finally:
            self.active_sessions -= 1
        if entry == self.exit_exception_call and self.exit_exception is not None:
            raise self.exit_exception


class _WorkspaceS3Config:
    """workspace S3 config for tests."""

    bucket = "test-bucket"


class _FileLifecycleConfig:
    """File lifecycle config for tests."""

    exchange_file_ttl = datetime.timedelta(days=30)


class _Config:
    """Config for tests."""

    workspace_s3 = _WorkspaceS3Config()
    file_lifecycle = _FileLifecycleConfig()


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Session manager for tests."""
    yield cast(AsyncSession, object())


def _make_agent_session() -> AgentSession:
    """Create AgentSession for tests."""
    return AgentSession(
        owner_generation=0,
        inference_state=None,
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        handle="test-session-handle",
        session_kind=AgentSessionKind.ROOT,
        status=AgentSessionStatus.ACTIVE,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=_NOW,
        end_reason=None,
        started_at=_NOW,
        ended_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_agent() -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection()
    return Agent(
        id="agent-1",
        workspace_id="workspace-1",
        name="Test Agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_options(selection),
        main_model_label="default",
        lightweight_model_label="default",
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        type=AgentType.PUBLIC,
        runtime_provider_id=None,
        shell_enabled=True,
        memory_enabled=True,
        max_turns=None,
        avatar=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_workspace_user() -> WorkspaceUser:
    """Create WorkspaceUser for tests."""
    return WorkspaceUser(
        id="workspace-user-1",
        workspace_id="workspace-1",
        user_id="user-1",
        name="tester",
        locale="ko-KR",
        role=WorkspaceUserRole.MEMBER,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service(
    *,
    workspace_user: WorkspaceUser | None,
    agent: Agent | None = None,
    agent_session: AgentSession | None = None,
) -> tuple[ExchangeFileService, _FakeExchangeFileRepository, _FakeS3Service]:
    """Create ExchangeFileService for tests."""
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = (
        agent if agent is not None else _make_agent()
    )

    agent_session_repository = AsyncMock()
    agent_session_repository.get_by_id.return_value = (
        agent_session if agent_session is not None else _make_agent_session()
    )
    agent_session_repository.lock_by_id.return_value = (
        agent_session if agent_session is not None else _make_agent_session()
    )

    workspace_user_repository = AsyncMock()
    workspace_user_repository.get_by_workspace_and_user.return_value = workspace_user
    workspace_user_repository.lock_by_workspace_and_user.return_value = workspace_user

    exchange_file_repository = _FakeExchangeFileRepository()
    s3_service = _FakeS3Service()
    service = ExchangeFileService(
        exchange_file_repository=cast(Any, exchange_file_repository),
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
        workspace_user_repository=workspace_user_repository,
        session_manager=_session_manager,
        s3_service=cast(Any, s3_service),
        config=cast(Any, _Config()),
    )
    return service, exchange_file_repository, s3_service


def _jpeg_bytes(size: tuple[int, int] = (900, 600)) -> bytes:
    """Create JPEG bytes for tests."""
    image = Image.new("RGB", size, (20, 80, 140))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_exchange_uri_returns_object_key_only() -> None:
    """Exchange URI contains file-location object key, not entity id."""
    object_key = "exchange/workspace-1/files/random/original"

    assert exchange_object_key_from_uri(f"exchange://{object_key}") == object_key
    assert exchange_object_key_from_uri("artifact://anything") is None
    assert exchange_object_key_from_uri("exchange://") is None


@pytest.mark.asyncio
async def test_create_agent_upload_stores_object_and_metadata() -> None:
    """Upload stores object and metadata together."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Success)
    file = result.value
    assert file.agent_id == "agent-1"
    assert file.object_key == f"exchange/workspace-1/files/{file.id}/original"
    assert file.uri == f"exchange://{file.object_key}"
    assert s3_service.objects[file.object_key] == b"a,b\n1,2\n"
    assert file.preview_summary == "a,b\n1,2\n"
    assert repository.files[file.id].sha256


@pytest.mark.asyncio
async def test_create_upload_does_not_hold_db_session_during_storage_io() -> None:
    """S3 I/O runs between the authorization and metadata DB sessions."""
    service, _repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Success)
    assert tracker.entries == 2
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_upload_cleans_blob_when_metadata_write_fails() -> None:
    """A DB failure after upload deletes the unreferenced object."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker
    repository.fail_create = True

    with pytest.raises(RuntimeError, match="metadata write failed"):
        await service.create_agent_upload(
            agent_id="agent-1",
            user_id="user-1",
            filename="report.csv",
            media_type="text/csv",
            body=b"a,b\n1,2\n",
        )

    assert s3_service.objects == {}
    assert len(s3_service.deleted_keys) == 1
    assert repository.files == {}
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_image_recovers_family_after_commit_response_loss() -> None:
    """A lost response reconciles the exact committed original and thumbnail."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker(
        exit_exception_call=2,
        exit_exception=RuntimeError("commit response lost"),
    )
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="photo.jpg",
        media_type="image/jpeg",
        body=_jpeg_bytes(),
    )

    assert isinstance(result, Success)
    thumbnail_id = result.value.preview_thumbnail_file_id
    assert thumbnail_id is not None
    assert set(repository.files) == {result.value.id, thumbnail_id}
    assert set(s3_service.objects) == {
        result.value.object_key,
        repository.files[thumbnail_id].object_key,
    }
    assert s3_service.deleted_keys == []
    assert tracker.entries == 3
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_preserves_committed_file_then_propagates_cancellation() -> None:
    """Commit-time cancellation keeps the exact durable file and blob."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker(
        exit_exception_call=2,
        exit_exception=asyncio.CancelledError("stop during commit"),
    )
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker

    with pytest.raises(asyncio.CancelledError, match="stop during commit"):
        await service.create_agent_upload(
            agent_id="agent-1",
            user_id="user-1",
            filename="report.csv",
            media_type="text/csv",
            body=b"a,b\n1,2\n",
        )

    assert len(repository.files) == 1
    file = next(iter(repository.files.values()))
    assert s3_service.objects[file.object_key] == b"a,b\n1,2\n"
    assert s3_service.deleted_keys == []
    assert tracker.entries == 3
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_upload_cleans_blob_when_upload_writes_then_raises() -> None:
    """A partial original upload failure deletes its pre-generated object key."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker
    s3_service.fail_upload_after_write_at = 1

    with pytest.raises(RuntimeError, match="upload failed after write"):
        await service.create_agent_upload(
            agent_id="agent-1",
            user_id="user-1",
            filename="report.csv",
            media_type="text/csv",
            body=b"a,b\n1,2\n",
        )

    assert s3_service.objects == {}
    assert len(s3_service.deleted_keys) == 1
    assert repository.files == {}
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_upload_cleanup_failure_does_not_replace_upload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal cleanup cancellation keeps the upload failure primary."""
    service, _repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    s3_service.fail_upload_after_write_at = 1

    async def failed_compensation(_object_keys: list[str]) -> None:
        raise asyncio.CancelledError("cleanup cancelled")

    monkeypatch.setattr(service, "_compensate_uploaded_objects", failed_compensation)

    with pytest.raises(RuntimeError, match="upload failed after write") as raised:
        await service.create_agent_upload(
            agent_id="agent-1",
            user_id="user-1",
            filename="report.csv",
            media_type="text/csv",
            body=b"a,b\n1,2\n",
        )
    assert isinstance(raised.value.__cause__, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_create_image_cleans_both_blobs_when_thumbnail_upload_fails() -> None:
    """A partial thumbnail failure deletes both attempted object keys."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker
    s3_service.fail_upload_after_write_at = 2

    with pytest.raises(RuntimeError, match="upload failed after write"):
        await service.create_agent_upload(
            agent_id="agent-1",
            user_id="user-1",
            filename="photo.jpg",
            media_type="image/jpeg",
            body=_jpeg_bytes(),
        )

    assert s3_service.objects == {}
    assert len(s3_service.deleted_keys) == 2
    assert repository.files == {}
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_session_upload_revalidates_session_ownership() -> None:
    """Do not commit metadata if Session ownership changes during upload."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    agent_session_repository = cast(Any, service.agent_session_repository)
    changed_session = _make_agent_session().model_copy(update={"agent_id": "agent-2"})
    s3_service.after_upload = lambda: setattr(
        agent_session_repository.lock_by_id,
        "return_value",
        changed_session,
    )

    result = await service.create_session_upload(
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, SessionNotFound)
    assert repository.files == {}
    assert s3_service.objects == {}


@pytest.mark.asyncio
async def test_create_agent_upload_revalidates_workspace_access() -> None:
    """Do not commit metadata when workspace access is revoked during upload."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    workspace_user_repository = cast(Any, service.workspace_user_repository)
    s3_service.after_upload = lambda: setattr(
        workspace_user_repository.lock_by_workspace_and_user,
        "return_value",
        None,
    )

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, FileAccessDenied)
    assert repository.files == {}
    assert s3_service.objects == {}


@pytest.mark.asyncio
async def test_create_text_upload_truncates_preview() -> None:
    """Text upload stores a bounded preview alongside the original."""
    service, _repository, _s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="long.txt",
        media_type="text/plain",
        body=("a" * 2100).encode(),
    )

    assert isinstance(result, Success)
    assert result.value.preview_summary == "a" * 2000 + "\n... (truncated)"


@pytest.mark.asyncio
async def test_create_image_upload_stores_preview_thumbnail() -> None:
    """Image upload also stores preview thumbnail Exchange file."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="photo.jpg",
        media_type="image/jpeg",
        body=_jpeg_bytes(),
    )

    assert isinstance(result, Success)
    file = result.value
    assert file.preview_thumbnail_file_id is not None
    thumbnail = repository.files[file.preview_thumbnail_file_id]
    assert file.preview_thumbnail_uri == f"exchange://{thumbnail.object_key}"
    assert file.preview_thumbnail_media_type == "image/jpeg"
    assert file.preview_thumbnail_width is not None
    assert file.preview_thumbnail_height is not None
    assert file.preview_generated_at is not None
    assert thumbnail.media_type == "image/jpeg"
    assert thumbnail.filename == "photo.jpg.preview.jpg"
    assert thumbnail.object_key in s3_service.objects
    assert len(s3_service.objects[thumbnail.object_key]) < len(_jpeg_bytes())


@pytest.mark.asyncio
async def test_create_artifact_stores_artifact_origin() -> None:
    """Artifact creation also uses files namespace URI and object key."""
    service, _repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )

    result = await service.create_artifact(
        session_id="session-1",
        user_id="user-1",
        filename="result.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    file = result.value
    assert file.origin_type == ExchangeFileOrigin.ARTIFACT
    assert file.object_key == f"exchange/workspace-1/files/{file.id}/original"
    assert file.uri == f"exchange://{file.object_key}"
    assert s3_service.objects[file.object_key] == b"hello"


@pytest.mark.asyncio
async def test_create_session_upload_uses_session_scope() -> None:
    """Chat upload uses AgentSession workspace permission, not Agent permission."""
    agent = _make_agent().model_copy(update={"workspace_id": "workspace-agent"})
    agent_session = _make_agent_session().model_copy(
        update={"workspace_id": "workspace-1"}
    )
    service, _repository, s3_service = _make_service(
        workspace_user=_make_workspace_user(),
        agent=agent,
        agent_session=agent_session,
    )

    result = await service.create_session_upload(
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Success)
    file = result.value
    assert file.agent_id == "agent-1"
    assert file.workspace_id == "workspace-1"
    assert file.origin_type == ExchangeFileOrigin.UPLOAD
    assert s3_service.objects[file.object_key] == b"a,b\n1,2\n"


@pytest.mark.asyncio
async def test_create_session_upload_denies_mismatched_agent() -> None:
    """Reject upload when path agent differs from session agent."""
    service, _repository, _s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )

    result = await service.create_session_upload(
        agent_id="other-agent",
        session_id="session-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, SessionNotFound)


@pytest.mark.asyncio
async def test_create_agent_upload_denies_non_workspace_member() -> None:
    """Reject upload when not a workspace member."""
    service, _repository, _s3_service = _make_service(workspace_user=None)

    result = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, FileAccessDenied)


@pytest.mark.asyncio
async def test_download_returns_unavailable_when_object_missing() -> None:
    """Return unavailable when only metadata remains and object is absent."""
    service, _repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)
    s3_service.objects.clear()

    result = await service.download(file_id=created.value.id, user_id="user-1")

    assert isinstance(result, Failure)
    assert isinstance(result.error, FileUnavailable)


@pytest.mark.asyncio
async def test_download_returns_expired_when_file_is_past_ttl() -> None:
    """Return expired for file past expiration time even if storage object exists."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)
    expired_file = created.value.model_copy(
        update={"expires_at": _NOW - datetime.timedelta(seconds=1)}
    )
    repository.files[created.value.id] = expired_file

    result = await service.download(file_id=created.value.id, user_id="user-1")

    assert isinstance(result, Failure)
    assert isinstance(result.error, FileExpired)
    assert created.value.object_key in s3_service.objects
    assert repository.files[created.value.id].status == ExchangeFileStatus.EXPIRED


@pytest.mark.asyncio
async def test_resolve_attachment_metadata_keeps_expired_attachment_visible() -> None:
    """Metadata-only resolve returns expired attachment metadata."""
    service, repository, _s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)
    repository.files[created.value.id] = created.value.model_copy(
        update={"expires_at": _NOW - datetime.timedelta(seconds=1)}
    )

    result = await service.resolve_attachment_metadata(
        uri=created.value.uri,
        user_id="user-1",
    )

    assert isinstance(result, Success)
    assert result.value.status == ExchangeFileStatus.EXPIRED


@pytest.mark.asyncio
async def test_download_returns_not_found_after_delete() -> None:
    """After hard delete, metadata is absent and not found is returned."""
    service, _repository, _s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)
    deleted = await service.delete(file_id=created.value.id, user_id="user-1")
    assert isinstance(deleted, Success)

    result = await service.download(file_id=created.value.id, user_id="user-1")

    assert isinstance(result, Failure)
    assert isinstance(result.error, FileNotFound)


@pytest.mark.asyncio
async def test_download_allows_empty_object() -> None:
    """0-byte file is also downloaded as normal file."""
    service, _repository, _s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="empty.txt",
        media_type="text/plain",
        body=b"",
    )
    assert isinstance(created, Success)

    result = await service.download(file_id=created.value.id, user_id="user-1")

    assert isinstance(result, Success)
    assert result.value.body == b""


@pytest.mark.asyncio
async def test_resolve_attachment_rejects_entity_id_uri() -> None:
    """entity id convention URI is not file-location URI, so it is not fetched."""
    service, _repository, _s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)

    result = await service.resolve_attachment(
        uri=f"exchange://uploads/{created.value.id}",
        user_id="user-1",
    )

    assert isinstance(result, Failure)


@pytest.mark.asyncio
async def test_delete_removes_object_and_metadata() -> None:
    """Deletion removes both object and metadata."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)

    result = await service.delete(file_id=created.value.id, user_id="user-1")

    assert isinstance(result, Success)
    assert created.value.object_key not in s3_service.objects
    assert created.value.id not in repository.files


@pytest.mark.asyncio
async def test_delete_removes_preview_thumbnail_object_and_metadata() -> None:
    """Original deletion also deletes linked preview thumbnail."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="photo.jpg",
        media_type="image/jpeg",
        body=_jpeg_bytes(),
    )
    assert isinstance(created, Success)
    thumbnail_file_id = created.value.preview_thumbnail_file_id
    assert thumbnail_file_id is not None
    thumbnail = repository.files[thumbnail_file_id]

    result = await service.delete(file_id=created.value.id, user_id="user-1")

    assert isinstance(result, Success)
    assert created.value.object_key not in s3_service.objects
    assert thumbnail.object_key not in s3_service.objects
    assert created.value.id not in repository.files
    assert thumbnail.id not in repository.files


@pytest.mark.asyncio
async def test_delete_tombstones_metadata_when_object_delete_fails() -> None:
    """An object-store failure leaves retryable expired metadata, never AVAILABLE."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="report.csv",
        media_type="text/csv",
        body=b"a,b\n1,2\n",
    )
    assert isinstance(created, Success)

    s3_service.fail_delete = True
    with pytest.raises(RuntimeError):
        await service.delete(file_id=created.value.id, user_id="user-1")

    assert created.value.object_key in s3_service.objects
    assert created.value.id in repository.files
    assert repository.files[created.value.id].status == ExchangeFileStatus.EXPIRED


@pytest.mark.asyncio
async def test_delete_retries_after_partial_preview_family_blob_deletion() -> None:
    """A retry completes a family after one blob was deleted before another failed."""
    service, repository, s3_service = _make_service(
        workspace_user=_make_workspace_user()
    )
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3_service.session_tracker = tracker
    created = await service.create_agent_upload(
        agent_id="agent-1",
        user_id="user-1",
        filename="photo.jpg",
        media_type="image/jpeg",
        body=_jpeg_bytes(),
    )
    assert isinstance(created, Success)
    thumbnail_file_id = created.value.preview_thumbnail_file_id
    assert thumbnail_file_id is not None
    thumbnail = repository.files[thumbnail_file_id]

    s3_service.fail_delete_at = 2
    with pytest.raises(RuntimeError, match="delete failed"):
        await service.delete(file_id=created.value.id, user_id="user-1")

    assert thumbnail.object_key not in s3_service.objects
    assert created.value.object_key in s3_service.objects
    assert repository.files[thumbnail.id].status == ExchangeFileStatus.EXPIRED
    assert repository.files[thumbnail.id].blob_deleted_at is not None
    assert repository.files[created.value.id].status == ExchangeFileStatus.EXPIRED
    assert repository.files[created.value.id].blob_deleted_at is None
    assert tracker.active_sessions == 0

    s3_service.fail_delete_at = None
    retried = await service.delete(file_id=created.value.id, user_id="user-1")

    assert isinstance(retried, Success)
    assert s3_service.objects == {}
    assert created.value.id not in repository.files
    assert thumbnail.id not in repository.files
    assert tracker.active_sessions == 0
