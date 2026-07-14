"""ArtifactService tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, Callable
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
    ArtifactAccessDenied,
    ArtifactDownload,
    ArtifactExpired,
    ArtifactService,
    ArtifactSessionNotFound,
    artifact_storage_key_from_uri,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


class _FakeArtifactRepository:
    """Artifact repository for tests."""

    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.next_id = "a" * 32
        self.fail_create = False
        self.lookup_error: Exception | None = None
        self.return_mismatched_lookup = False

    async def create(
        self,
        session: AsyncSession,
        create: ArtifactCreate,
    ) -> Artifact:
        """Store create input as domain model as-is."""
        del session
        if self.fail_create:
            msg = "metadata write failed"
            raise RuntimeError(msg)
        artifact_id = create.id or self.next_id
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
        if self.lookup_error is not None:
            raise self.lookup_error
        artifact = self.artifacts.get(artifact_id)
        if artifact is not None and self.return_mismatched_lookup:
            return artifact.model_copy(update={"sha256": "unexpected"})
        return artifact

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

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> AgentSession | None:
        """Fetch AgentSession under the final metadata authority lock."""
        return await self.get_by_id(session, session_id)


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

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        """Fetch membership under the final metadata authority lock."""
        return await self.get_by_workspace_and_user(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )


class _FakeS3Service:
    """S3 service for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.session_tracker: _SessionTracker | None = None
        self.after_upload: Callable[[], None] | None = None
        self.fail_upload_after_write = False

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
        self.objects[key] = body
        if self.after_upload is not None:
            self.after_upload()
        if self.fail_upload_after_write:
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
async def test_create_does_not_hold_db_session_during_object_storage_io() -> None:
    """S3 upload runs between the authorization and metadata DB sessions."""
    service, _artifact_repo, s3 = _make_service()
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert tracker.entries == 2
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_cleans_uploaded_blob_when_metadata_write_fails() -> None:
    """A DB failure after upload deletes the unreferenced object."""
    service, artifact_repo, s3 = _make_service()
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker
    artifact_repo.fail_create = True

    with pytest.raises(RuntimeError, match="metadata write failed"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_id="run-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert s3.objects == {}
    assert len(s3.deleted_keys) == 1
    assert artifact_repo.artifacts == {}
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_recovers_committed_artifact_after_commit_response_loss() -> None:
    """A lost commit response is reconciled by exact preallocated identity."""
    service, artifact_repo, s3 = _make_service()
    tracker = _SessionTracker(
        exit_exception_call=2,
        exit_exception=RuntimeError("commit response lost"),
    )
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert artifact_repo.artifacts[result.value.id] == result.value
    assert s3.objects[result.value.storage_key] == b"hello"
    assert s3.deleted_keys == []
    assert tracker.entries == 3
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_preserves_committed_artifact_then_propagates_cancellation() -> (
    None
):
    """Commit-time cancellation keeps the committed blob and original reason."""
    service, artifact_repo, s3 = _make_service()
    tracker = _SessionTracker(
        exit_exception_call=2,
        exit_exception=asyncio.CancelledError("stop during commit"),
    )
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker

    with pytest.raises(asyncio.CancelledError, match="stop during commit"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_id="run-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert len(artifact_repo.artifacts) == 1
    artifact = next(iter(artifact_repo.artifacts.values()))
    assert s3.objects[artifact.storage_key] == b"hello"
    assert s3.deleted_keys == []
    assert tracker.entries == 3
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reconciliation_failure", ["mismatch", "lookup_error"])
async def test_create_preserves_blob_when_commit_reconciliation_is_uncertain(
    reconciliation_failure: str,
) -> None:
    """Destructive compensation requires confirmed row absence, not uncertainty."""
    service, artifact_repo, s3 = _make_service()
    tracker = _SessionTracker(
        exit_exception_call=2,
        exit_exception=RuntimeError("commit response lost"),
    )
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker
    if reconciliation_failure == "mismatch":
        artifact_repo.return_mismatched_lookup = True
    else:
        artifact_repo.lookup_error = RuntimeError("lookup unavailable")

    with pytest.raises(RuntimeError, match="commit response lost"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_id="run-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert len(artifact_repo.artifacts) == 1
    artifact = next(iter(artifact_repo.artifacts.values()))
    assert s3.objects[artifact.storage_key] == b"hello"
    assert s3.deleted_keys == []
    assert tracker.entries == 3
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_fresh_cancellation_during_commit_reconciliation_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new stop during reconciliation is not replaced by the older DB error."""
    service, artifact_repo, s3 = _make_service()
    tracker = _SessionTracker(
        exit_exception_call=2,
        exit_exception=RuntimeError("commit response lost"),
    )
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker
    lookup_started = asyncio.Event()
    release_lookup = asyncio.Event()
    get_by_id = artifact_repo.get_by_id

    async def blocked_lookup(
        session: AsyncSession,
        artifact_id: str,
    ) -> Artifact | None:
        lookup_started.set()
        await release_lookup.wait()
        return await get_by_id(session, artifact_id)

    monkeypatch.setattr(artifact_repo, "get_by_id", blocked_lookup)
    create_task = asyncio.create_task(
        service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_id="run-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )
    )
    await lookup_started.wait()

    create_task.cancel("user stop during reconciliation")
    await asyncio.sleep(0)
    release_lookup.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await create_task
    assert raised.value.args == ("user stop during reconciliation",)
    assert s3.deleted_keys == []


@pytest.mark.asyncio
async def test_upload_cleanup_failure_does_not_replace_upload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal cleanup cancellation keeps the upload failure primary."""
    service, _artifact_repo, s3 = _make_service()
    s3.fail_upload_after_write = True

    async def failed_compensation(_object_key: str) -> None:
        raise asyncio.CancelledError("cleanup cancelled")

    monkeypatch.setattr(service, "_compensate_uploaded_object", failed_compensation)

    with pytest.raises(RuntimeError, match="upload failed after write") as raised:
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_id="run-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )
    assert isinstance(raised.value.__cause__, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_create_cleans_blob_when_upload_writes_then_raises() -> None:
    """A partial upload failure also deletes the pre-generated object key."""
    service, artifact_repo, s3 = _make_service()
    tracker = _SessionTracker()
    service.session_manager = cast(Any, tracker)
    s3.session_tracker = tracker
    s3.fail_upload_after_write = True

    with pytest.raises(RuntimeError, match="upload failed after write"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_id="run-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert s3.objects == {}
    assert len(s3.deleted_keys) == 1
    assert artifact_repo.artifacts == {}
    assert tracker.active_sessions == 0


@pytest.mark.asyncio
async def test_create_revalidates_session_ownership_after_upload() -> None:
    """Do not commit metadata if the Session namespace changed during upload."""
    service, artifact_repo, s3 = _make_service()
    session_repository = cast(
        _FakeAgentSessionRepository,
        service.agent_session_repository,
    )
    s3.after_upload = lambda: setattr(
        session_repository,
        "agent_session",
        session_repository.agent_session.model_copy(update={"agent_id": "agent-2"}),
    )

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, ArtifactSessionNotFound)
    assert artifact_repo.artifacts == {}
    assert s3.objects == {}


@pytest.mark.asyncio
async def test_create_revalidates_workspace_access_after_upload() -> None:
    """Do not commit metadata when workspace access is revoked during upload."""
    service, artifact_repo, s3 = _make_service()
    workspace_user_repository = cast(
        _FakeWorkspaceUserRepository,
        service.workspace_user_repository,
    )
    s3.after_upload = lambda: setattr(
        workspace_user_repository,
        "workspace_user",
        None,
    )

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_id="run-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, ArtifactAccessDenied)
    assert artifact_repo.artifacts == {}
    assert s3.objects == {}


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
