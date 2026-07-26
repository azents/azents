"""ArtifactService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity, S3ProductPublicationMetadata
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    ArtifactStatus,
    WorkspaceUserRole,
)
from azents.repos.agent_session.data import AgentSession
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.workspace_user.data import WorkspaceUser
from azents.services.session_resource_authority import SessionResourceAuthority

from .artifact import (
    ArtifactAccessDenied,
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

    async def create(
        self,
        session: AsyncSession,
        create: ArtifactCreate,
    ) -> Artifact:
        """Store create input as domain model as-is."""
        del session
        artifact_id = create.id
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

    async def get_root_session_agent_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object | None:
        """Return the root SessionAgent identity."""
        del session
        if session_id != self.agent_session.id:
            return None
        return SimpleNamespace(agent_session_id=self.agent_session.id)


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

    def __init__(self, session_boundary: "_SessionBoundary") -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.product_copy_calls: list[
            tuple[S3ObjectIdentity, S3ObjectIdentity, int, S3ProductPublicationMetadata]
        ] = []
        self.product_cleanup_calls: list[
            tuple[S3ObjectIdentity, int, S3ProductPublicationMetadata]
        ] = []
        self.session_boundary = session_boundary

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
        assert self.session_boundary.active == 0
        self.objects[key] = body

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """Fetch object bytes."""
        del bucket
        assert self.session_boundary.active == 0
        return self.objects.get(key)

    async def delete(self, bucket: str, key: str) -> None:
        """Delete object."""
        del bucket
        assert self.session_boundary.active == 0
        self.deleted_keys.append(key)
        self.objects.pop(key, None)

    async def copy_verified_transfer_object_to_product(
        self,
        *,
        source: S3ObjectIdentity,
        destination: S3ObjectIdentity,
        expected_size: int,
        publication_metadata: S3ProductPublicationMetadata,
    ) -> object:
        """Copy one trusted source into the final product key."""
        assert self.session_boundary.active == 0
        self.product_copy_calls.append(
            (source, destination, expected_size, publication_metadata)
        )
        self.objects[destination.key] = b"x" * expected_size
        return SimpleNamespace(created=True)

    async def delete_uncommitted_product_object(
        self,
        *,
        identity: S3ObjectIdentity,
        expected_size: int,
        publication_metadata: S3ProductPublicationMetadata,
    ) -> None:
        """Record conditional product cleanup."""
        assert self.session_boundary.active == 0
        self.product_cleanup_calls.append(
            (identity, expected_size, publication_metadata)
        )
        self.objects.pop(identity.key, None)


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


class _SessionBoundary:
    """Track open DB scopes for external-I/O boundary assertions."""

    def __init__(self) -> None:
        self.active = 0

    @asynccontextmanager
    async def session_manager(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a test DB session while tracking its lifetime."""
        self.active += 1
        try:
            yield cast(AsyncSession, object())
        finally:
            self.active -= 1


class _AuthorityArtifactService(ArtifactService):
    """Artifact service with explicit authority outcomes for publication tests."""

    authority_results: list[bool]

    async def _has_valid_resource_authority(
        self,
        session: AsyncSession,
        authority: SessionResourceAuthority,
        *,
        lock: bool = False,
    ) -> bool:
        """Return the next explicitly injected authority result."""
        del session, authority, lock
        return self.authority_results.pop(0)


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
        last_activity_at=_NOW,
        pinned=False,
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
        role=WorkspaceUserRole.MEMBER,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service() -> tuple[ArtifactService, _FakeArtifactRepository, _FakeS3Service]:
    """Create ArtifactService for tests."""
    artifact_repo = _FakeArtifactRepository()
    session_boundary = _SessionBoundary()
    s3 = _FakeS3Service(session_boundary)
    service = ArtifactService(
        artifact_repository=cast(Any, artifact_repo),
        agent_session_repository=cast(
            Any, _FakeAgentSessionRepository(_make_agent_session())
        ),
        agent_run_repository=cast(Any, object()),
        workspace_user_repository=cast(
            Any,
            _FakeWorkspaceUserRepository(_make_workspace_user()),
        ),
        session_manager=session_boundary.session_manager,
        s3_service=cast(Any, s3),
        config=cast(Any, _Config()),
    )
    return service, artifact_repo, s3


def _make_authority_service(
    *,
    authority_results: list[bool],
) -> tuple[_AuthorityArtifactService, _FakeArtifactRepository, _FakeS3Service]:
    """Create ArtifactService with authority checks injected for publication tests."""
    artifact_repo = _FakeArtifactRepository()
    session_boundary = _SessionBoundary()
    s3 = _FakeS3Service(session_boundary)
    service = _AuthorityArtifactService(
        artifact_repository=cast(Any, artifact_repo),
        agent_session_repository=cast(
            Any, _FakeAgentSessionRepository(_make_agent_session())
        ),
        agent_run_repository=cast(Any, object()),
        workspace_user_repository=cast(
            Any,
            _FakeWorkspaceUserRepository(_make_workspace_user()),
        ),
        session_manager=session_boundary.session_manager,
        s3_service=cast(Any, s3),
        config=cast(Any, _Config()),
    )
    service.authority_results = authority_results
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
    assert len(artifact.id) == 32
    assert artifact.expires_at - datetime.timedelta(days=7) >= _NOW
    assert artifact.storage_key == f"artifacts/workspace-1/session-1/3/{artifact.id}"
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


@pytest.mark.asyncio
async def test_authority_resolves_artifact_created_by_previous_session_run() -> None:
    """A later Run can import an Artifact owned by the same exact Session."""
    service, _, _ = _make_service()
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
    run_repository = AsyncMock()

    async def get_run(
        session: AsyncSession,
        run_id: str,
    ) -> object | None:
        del session
        if run_id == "run-1":
            return SimpleNamespace(
                session_id="session-1",
                run_index=1,
                status=AgentRunStatus.COMPLETED,
            )
        if run_id == "run-2":
            return SimpleNamespace(
                session_id="session-1",
                run_index=2,
                status=AgentRunStatus.RUNNING,
            )
        return None

    run_repository.get_by_id.side_effect = get_run
    service.agent_run_repository = run_repository

    resolved = await service.resolve_for_authority(
        uri=created.value.uri,
        authority=SessionResourceAuthority(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            root_session_id="session-1",
            run_id="run-2",
            run_index=2,
            owner_generation=0,
        ),
    )

    assert isinstance(resolved, Success)
    assert resolved.value.body == b"hello"
    assert resolved.value.artifact.created_run_id == "run-1"


@pytest.mark.asyncio
async def test_authority_publishes_verified_object_without_body_relay() -> None:
    """Authority publication copies the verified object and persists its manifest."""
    service, artifact_repo, s3 = _make_authority_service(authority_results=[True, True])
    authority = SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=3,
        owner_generation=0,
    )
    source = S3ObjectIdentity(bucket="transfer-bucket", key="verified-object")
    sha256 = "a" * 64

    result = await service.create_from_verified_object_for_authority(
        authority=authority,
        source=source,
        size_bytes=5 * 1024 * 1024,
        sha256=sha256,
        publication_id="artifact-publication",
        filename="report.txt",
        media_type="text/plain",
    )

    assert isinstance(result, Success)
    artifact = result.value
    assert artifact.size_bytes == 5 * 1024 * 1024
    assert artifact.sha256 == sha256
    assert artifact_repo.artifacts[artifact.id] == artifact
    assert s3.product_copy_calls == [
        (
            source,
            S3ObjectIdentity(bucket="test-bucket", key=artifact.storage_key),
            5 * 1024 * 1024,
            S3ProductPublicationMetadata(
                sha256=sha256,
                content_type="text/plain",
                publication_id=artifact.id,
            ),
        )
    ]
    assert s3.product_cleanup_calls == []


@pytest.mark.asyncio
async def test_authority_recovers_committed_verified_publication_without_copy() -> None:
    """A stable retry returns the committed Artifact without touching its object."""
    service, _artifact_repo, s3 = _make_authority_service(
        authority_results=[True, True, True]
    )
    authority = SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=3,
        owner_generation=0,
    )

    async def publish() -> Result[Artifact, ArtifactAccessDenied]:
        return await service.create_from_verified_object_for_authority(
            authority=authority,
            source=S3ObjectIdentity(
                bucket="transfer-bucket",
                key="verified-object",
            ),
            size_bytes=5 * 1024 * 1024,
            sha256="a" * 64,
            publication_id="artifact-publication",
            filename="report.txt",
            media_type="text/plain",
        )

    created = await publish()
    recovered = await publish()

    assert isinstance(created, Success)
    assert isinstance(recovered, Success)
    assert recovered.value == created.value
    assert len(s3.product_copy_calls) == 1
    assert s3.product_cleanup_calls == []


@pytest.mark.asyncio
async def test_authority_publication_compensates_uncommitted_verified_object() -> None:
    """Authority revalidation failure conditionally compensates the final object."""
    service, artifact_repo, s3 = _make_authority_service(
        authority_results=[True, False]
    )
    authority = SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=3,
        owner_generation=0,
    )
    source = S3ObjectIdentity(bucket="transfer-bucket", key="verified-object")

    result = await service.create_from_verified_object_for_authority(
        authority=authority,
        source=source,
        size_bytes=7,
        sha256="b" * 64,
        publication_id="artifact-publication",
        filename="report.txt",
        media_type="text/plain",
    )

    assert isinstance(result, Failure)
    assert artifact_repo.artifacts == {}
    assert len(s3.product_copy_calls) == 1
    assert len(s3.product_cleanup_calls) == 1
    cleanup_identity, cleanup_size, cleanup_metadata = s3.product_cleanup_calls[0]
    assert cleanup_identity.key == s3.product_copy_calls[0][1].key
    assert cleanup_size == 7
    assert cleanup_metadata.publication_id not in artifact_repo.artifacts


def test_artifact_uri_returns_storage_key_only() -> None:
    """Artifact URI contains file-location storage key, not entity id."""
    storage_key = "artifacts/workspace-1/session-1/3/random"

    assert artifact_storage_key_from_uri(f"artifact://{storage_key}") == storage_key
    assert artifact_storage_key_from_uri("exchange://anything") is None
    assert artifact_storage_key_from_uri("artifact://") is None
