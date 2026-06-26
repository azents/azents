"""ExchangeFileService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRole,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentType,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    WorkspaceUserRole,
)
from azents.repos.agent.data import Agent
from azents.repos.agent_session.data import AgentSession
from azents.repos.agent_subagent.data import SubagentToolkitInheritMode
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.workspace_user.data import WorkspaceUser
from azents.testing.model_selection import make_test_model_selection

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

    async def create(
        self,
        session: AsyncSession,
        create: ExchangeFileCreate,
    ) -> ExchangeFile:
        """Store create input as domain model as-is."""
        del session
        file_id = f"{self.next_id:032x}"
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


class _FakeS3Service:
    """S3 service for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_delete = False

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
        self.objects[key] = body

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """Fetch object bytes."""
        del bucket
        return self.objects.get(key)

    async def delete(self, bucket: str, key: str) -> None:
        """Delete object."""
        del bucket
        if self.fail_delete:
            msg = "delete failed"
            raise RuntimeError(msg)
        self.objects.pop(key, None)


class _WorkspaceS3Config:
    """workspace S3 config for tests."""

    bucket = "test-bucket"


class _Config:
    """Config for tests."""

    workspace_s3 = _WorkspaceS3Config()


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Session manager for tests."""
    yield cast(AsyncSession, object())


def _make_agent_session() -> AgentSession:
    """Create AgentSession for tests."""
    return AgentSession(
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
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
    return Agent(
        id="agent-1",
        workspace_id="workspace-1",
        name="Test Agent",
        description=None,
        model_selection=make_test_model_selection(),
        lightweight_model_selection=make_test_model_selection(),
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        type=AgentType.PUBLIC,
        role=AgentRole.AGENT,
        runtime_provider_id=None,
        shell_enabled=True,
        memory_enabled=True,
        max_turns=None,
        toolkit_inherit_mode=SubagentToolkitInheritMode.ALL,
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

    workspace_user_repository = AsyncMock()
    workspace_user_repository.get_by_workspace_and_user.return_value = workspace_user

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
    assert repository.files[file.id].sha256


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
async def test_expire_due_files_marks_expired_and_deletes_blob() -> None:
    """Expiration cleanup hook marks due file expired and tries object delete."""
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
    repository.files[created.value.id] = created.value.model_copy(
        update={"expires_at": _NOW - datetime.timedelta(seconds=1)}
    )

    expired = await service.expire_due_files()

    assert [file.id for file in expired] == [created.value.id]
    assert repository.files[created.value.id].status == ExchangeFileStatus.EXPIRED
    assert created.value.object_key not in s3_service.objects


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
async def test_delete_keeps_metadata_when_object_delete_fails() -> None:
    """Leave metadata on object deletion failure to allow retry."""
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
