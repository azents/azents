"""ArtifactService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    ArtifactStatus,
    WorkspaceUserRole,
)
from azents.repos.agent_session.data import AgentSession
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.workspace_user.data import WorkspaceUser

from .artifact import (
    ArtifactDownload,
    ArtifactExpired,
    ArtifactService,
    artifact_storage_key_from_uri,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


class _FakeArtifactRepository:
    """Artifact repository for tests."""

    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.next_id = "a" * 32

    async def create(
        self,
        session: AsyncSession,
        create: ArtifactCreate,
    ) -> Artifact:
        """Store create input as domain model as-is."""
        del session
        artifact_id = self.next_id
        artifact = Artifact(
            id=artifact_id,
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            created_run_id=create.created_run_id,
            created_run_index=create.created_run_index,
            expires_at=create.expires_at,
            name=create.name,
            media_type=create.media_type,
            size_bytes=create.size_bytes,
            storage_key=(
                f"artifacts/{create.workspace_id}/{create.session_id}/"
                f"{create.created_run_index}/{artifact_id}"
            ),
            status=ArtifactStatus.AVAILABLE,
            sha256=create.sha256,
            source_tool_name=create.source_tool_name,
            source_call_id=create.source_call_id,
            source_part_index=create.source_part_index,
            description=create.description,
            metadata=create.metadata,
            created_at=_NOW,
            expired_at=None,
            blob_deleted_at=None,
        )
        self.artifacts[artifact.id] = artifact
        return artifact

    async def get_by_id(
        self,
        session: AsyncSession,
        artifact_id: str,
    ) -> Artifact | None:
        """Fetch Artifact by ID."""
        del session
        return self.artifacts.get(artifact_id)

    async def get_by_storage_key(
        self,
        session: AsyncSession,
        storage_key: str,
    ) -> Artifact | None:
        """Fetch Artifact by storage key."""
        del session
        for artifact in self.artifacts.values():
            if artifact.storage_key == storage_key:
                return artifact
        return None

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[Artifact]:
        """Expire due Artifact rows."""
        del session, limit
        expired: list[Artifact] = []
        for artifact in list(self.artifacts.values()):
            if (
                artifact.status == ArtifactStatus.AVAILABLE
                and artifact.expires_at <= now
            ):
                updated = artifact.model_copy(
                    update={"status": ArtifactStatus.EXPIRED, "expired_at": now}
                )
                self.artifacts[artifact.id] = updated
                expired.append(updated)
        return expired

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        artifact_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record blob deletion."""
        del session
        self.artifacts[artifact_id] = self.artifacts[artifact_id].model_copy(
            update={"blob_deleted_at": blob_deleted_at}
        )


class _FakeAgentSessionRepository:
    """AgentSession repository for tests."""

    def __init__(self, agent_session: AgentSession) -> None:
        self.agent_session = agent_session

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession by ID."""
        del session
        if session_id == self.agent_session.id:
            return self.agent_session
        return None


class _FakeWorkspaceUserRepository:
    """WorkspaceUser repository for tests."""

    def __init__(self, workspace_user: WorkspaceUser | None = None) -> None:
        self.workspace_user = workspace_user

    async def get_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        """Fetch workspace/user membership."""
        del session
        if self.workspace_user is None:
            return None
        if (
            workspace_id == self.workspace_user.workspace_id
            and user_id == self.workspace_user.user_id
        ):
            return self.workspace_user
        return None


class _FakeS3Service:
    """S3 service for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

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
        self.deleted_keys.append(key)
        self.objects.pop(key, None)


class _WorkspaceS3Config:
    """workspace S3 config for tests."""

    bucket = "test-bucket"


class _FileLifecycleConfig:
    """File lifecycle config for tests."""

    artifact_ttl = datetime.timedelta(days=7)


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


def _make_workspace_user() -> WorkspaceUser:
    """Create WorkspaceUser for tests."""
    return WorkspaceUser(
        id="workspace-user-1",
        workspace_id="workspace-1",
        user_id="user-1",
        name="Test User",
        locale="en-US",
        role=WorkspaceUserRole.MEMBER,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service() -> tuple[ArtifactService, _FakeArtifactRepository, _FakeS3Service]:
    """Create ArtifactService for tests."""
    artifact_repo = _FakeArtifactRepository()
    s3 = _FakeS3Service()
    service = ArtifactService(
        artifact_repository=cast(Any, artifact_repo),
        agent_session_repository=cast(
            Any, _FakeAgentSessionRepository(_make_agent_session())
        ),
        workspace_user_repository=cast(
            Any,
            _FakeWorkspaceUserRepository(_make_workspace_user()),
        ),
        session_manager=_session_manager,
        s3_service=cast(Any, s3),
        config=cast(Any, _Config()),
    )
    return service, artifact_repo, s3


@pytest.mark.asyncio
async def test_create_and_resolve_artifact() -> None:
    """Create Artifact metadata and object, then fetch by artifact:// URI."""
    service, artifact_repo, s3 = _make_service()

    created = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
        source_tool_name="write",
        source_call_id="call-1",
        source_part_index=0,
        description="report",
        metadata={"nested": {"count": 1}},
    )

    assert isinstance(created, Success)
    artifact = created.value
    assert artifact.id == "a" * 32
    assert artifact.expires_at - datetime.timedelta(days=7) >= _NOW
    assert artifact.storage_key == "artifacts/workspace-1/session-1/3/" + "a" * 32
    assert artifact.uri == f"artifact://{artifact.storage_key}"
    assert s3.objects[artifact.storage_key] == b"hello"
    assert artifact_repo.artifacts[artifact.id].metadata == {"nested": {"count": 1}}

    resolved = await service.resolve(uri=artifact.uri, user_id="user-1")

    assert isinstance(resolved, Success)
    assert resolved.value == ArtifactDownload(artifact=artifact, body=b"hello")


@pytest.mark.asyncio
async def test_expired_artifact_is_denied_even_if_blob_exists() -> None:
    """Expired Artifact rejects resolution even when blob remains."""
    service, artifact_repo, s3 = _make_service()
    artifact_repo.next_id = "b" * 32
    created = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=1,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )
    assert isinstance(created, Success)
    artifact = created.value
    artifact_repo.artifacts[artifact.id] = artifact.model_copy(
        update={"status": ArtifactStatus.EXPIRED}
    )
    s3.objects[artifact.storage_key] = b"still here"

    resolved = await service.resolve(uri=artifact.uri, user_id="user-1")

    assert isinstance(resolved, Failure)
    assert isinstance(resolved.error, ArtifactExpired)


def test_artifact_uri_returns_storage_key_only() -> None:
    """Artifact URI contains file-location storage key, not entity id."""
    storage_key = "artifacts/workspace-1/session-1/3/random"

    assert artifact_storage_key_from_uri(f"artifact://{storage_key}") == storage_key
    assert artifact_storage_key_from_uri("exchange://anything") is None
    assert artifact_storage_key_from_uri("artifact://") is None
