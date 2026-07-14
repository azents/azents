"""ModelFileService tests."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from PIL import Image

from azents.core.enums import ModelFileStatus
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.services.model_file import (
    ModelFileInvalidImage,
    ModelFileOversized,
    ModelFileService,
    ModelFileSessionNotFound,
    model_file_size_limit_message,
    normalize_model_file_body,
)


class _TrackedSessionManager:
    """Track open DB scopes and optionally fail one commit boundary."""

    def __init__(
        self,
        *,
        fail_exit_call: int | None = None,
        exit_exception: BaseException | None = None,
        persist_failed_commit: bool = False,
    ) -> None:
        self.active = 0
        self.calls = 0
        self.fail_exit_call = fail_exit_call
        self.exit_exception = exit_exception
        self.persist_failed_commit = persist_failed_commit

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[object]:
        """Yield one tracked placeholder session."""
        self.calls += 1
        call = self.calls
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1
        if call == self.fail_exit_call:
            if self.exit_exception is not None:
                raise self.exit_exception
            raise RuntimeError("metadata commit failed")


class _TrackedS3Service:
    """Assert object storage I/O never overlaps a DB session."""

    def __init__(
        self,
        session_manager: _TrackedSessionManager,
        *,
        fail_upload: bool = False,
    ) -> None:
        self.session_manager = session_manager
        self.fail_upload = fail_upload
        self.uploaded: list[str] = []
        self.deleted: list[str] = []
        self.delete_completed = asyncio.Event()
        self.after_upload: Callable[[], None] | None = None

    async def upload(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str,
    ) -> None:
        """Record an upload after verifying the DB boundary."""
        del bucket, body, content_type
        assert self.session_manager.active == 0
        self.uploaded.append(key)
        if self.after_upload is not None:
            self.after_upload()
        if self.fail_upload:
            raise RuntimeError("upload failed after object write")

    async def delete(self, *, bucket: str, key: str) -> None:
        """Record a compensating delete outside any DB boundary."""
        del bucket
        assert self.session_manager.active == 0
        self.deleted.append(key)
        self.delete_completed.set()


def _model_file_service(
    session_manager: _TrackedSessionManager,
    *,
    s3_service: _TrackedS3Service | None = None,
) -> tuple[ModelFileService, AsyncMock, AsyncMock]:
    """Build a ModelFileService with deterministic repository fakes."""
    agent_session_repository = AsyncMock()
    agent_session = SimpleNamespace(
        id="session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
    )
    agent_session_repository.get_by_id.return_value = agent_session
    agent_session_repository.lock_by_id.return_value = agent_session
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        id="agent-1",
        workspace_id="workspace-1",
    )
    workspace_user_repository = AsyncMock()
    workspace_user_repository.get_by_workspace_and_user.return_value = object()
    workspace_user_repository.lock_by_workspace_and_user.return_value = object()
    agent_run_repository = AsyncMock()
    agent_run_repository.next_run_index.return_value = 4
    model_file_repository = AsyncMock()
    last_created: ModelFile | None = None

    async def create_model_file(
        session: object,
        create: ModelFileCreate,
    ) -> ModelFile:
        nonlocal last_created
        del session
        assert session_manager.active == 1
        assert create.id is not None
        now = datetime.datetime.now(datetime.UTC)
        last_created = ModelFile(
            id=create.id,
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            name=create.name,
            media_type=create.media_type,
            kind=create.kind,
            size_bytes=create.size_bytes,
            created_run_index=create.created_run_index,
            storage_key=(
                f"model-files/{create.workspace_id}/{create.session_id}/{create.id}"
            ),
            status=ModelFileStatus.AVAILABLE,
            normalized_format=create.normalized_format,
            sha256=create.sha256,
            metadata=create.metadata,
            created_at=now,
        )
        return last_created

    async def get_model_file(
        session: object,
        model_file_id: str,
    ) -> ModelFile | None:
        """Expose a row only when the failed commit is configured as durable."""
        del session
        if (
            session_manager.persist_failed_commit
            and last_created is not None
            and last_created.id == model_file_id
        ):
            return last_created
        return None

    model_file_repository.create.side_effect = create_model_file
    model_file_repository.get_by_id.side_effect = get_model_file
    service = ModelFileService(
        model_file_repository=cast(Any, model_file_repository),
        agent_repository=cast(Any, agent_repository),
        agent_session_repository=cast(Any, agent_session_repository),
        agent_run_repository=cast(Any, agent_run_repository),
        workspace_user_repository=cast(Any, workspace_user_repository),
        session_manager=cast(Any, session_manager),
        s3_service=cast(Any, s3_service or _TrackedS3Service(session_manager)),
        config=cast(
            Any,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="workspace-files")),
        ),
    )
    return service, agent_session_repository, workspace_user_repository


def _png_bytes() -> bytes:
    """Create PNG bytes for tests."""
    image = Image.new("RGBA", (2, 2), (255, 0, 0, 128))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_model_file_normalizes_to_jpeg() -> None:
    """Image ModelFile is converted to JPEG normalized blob."""
    result = normalize_model_file_body(media_type="image/png", body=_png_bytes())

    assert isinstance(result, Success)
    assert result.value.media_type == "image/jpeg"
    assert result.value.kind == "image"
    assert result.value.normalized_format == "jpeg"
    assert result.value.body.startswith(b"\xff\xd8")


def test_invalid_image_fails_without_storing_random_bytes_as_image() -> None:
    """Does not create image ModelFile when declared image payload is broken."""
    result = normalize_model_file_body(media_type="image/png", body=b"not an image")

    assert isinstance(result, Failure)
    assert isinstance(result.error, ModelFileInvalidImage)


def test_non_image_model_file_keeps_original_bytes_under_cap() -> None:
    """Non-image ModelFile is not normalized and only applies size cap."""
    body = b"\x00\x01\x02"
    result = normalize_model_file_body(
        media_type="application/octet-stream",
        body=body,
    )

    assert isinstance(result, Success)
    assert result.value.body == body
    assert result.value.kind == "binary"
    assert result.value.normalized_format == "original"


def test_non_image_model_file_rejects_oversized_input() -> None:
    """Non-image input exceeding size cap is not made into ModelFile."""
    body = b"x" * 1_000_001
    result = normalize_model_file_body(media_type="application/pdf", body=body)

    assert isinstance(result, Failure)
    assert isinstance(result.error, ModelFileOversized)
    assert "File size exceeds the allowed limit" in model_file_size_limit_message(
        result.error
    )


async def test_create_uploads_only_after_authorization_session_closes() -> None:
    """S3 upload and cleanup never run while a DB session is open."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert result.value.created_run_index == 3
    assert result.value.storage_key == s3.uploaded[0]
    assert s3.deleted == []
    assert session_manager.active == 0
    assert session_manager.calls == 2


async def test_create_cleans_object_when_upload_reports_failure() -> None:
    """A possibly written object is deleted even when upload raises."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager, fail_upload=True)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    with pytest.raises(RuntimeError, match="upload failed after object write"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert s3.deleted == s3.uploaded
    assert session_manager.active == 0


async def test_create_cleans_object_when_metadata_commit_fails() -> None:
    """Metadata commit failure compensates the already completed upload."""
    session_manager = _TrackedSessionManager(fail_exit_call=2)
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    with pytest.raises(RuntimeError, match="metadata commit failed"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert s3.deleted == s3.uploaded
    assert session_manager.active == 0


async def test_fresh_reconciliation_cancel_still_cleans_rolled_back_object() -> None:
    """Detached commit reconciliation deletes a proven orphaned object."""
    session_manager = _TrackedSessionManager(fail_exit_call=2)
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )
    reconciliation_started = asyncio.Event()
    release_reconciliation = asyncio.Event()
    repository = cast(Any, service.model_file_repository)
    get_by_id = repository.get_by_id.side_effect

    async def delayed_lookup(session: object, model_file_id: str) -> object:
        reconciliation_started.set()
        await release_reconciliation.wait()
        return await get_by_id(session, model_file_id)

    repository.get_by_id.side_effect = delayed_lookup
    create_task = asyncio.create_task(
        service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )
    )
    await asyncio.wait_for(reconciliation_started.wait(), timeout=1)
    create_task.cancel("fresh reconciliation cancellation")

    with pytest.raises(
        asyncio.CancelledError,
        match="fresh reconciliation cancellation",
    ):
        await asyncio.wait_for(create_task, timeout=0.1)
    assert s3.deleted == []

    release_reconciliation.set()
    await asyncio.wait_for(s3.delete_completed.wait(), timeout=1)
    assert s3.deleted == s3.uploaded
    assert session_manager.active == 0


async def test_create_recovers_model_file_after_commit_response_loss() -> None:
    """A lost response reconciles exact durable metadata without blob deletion."""
    session_manager = _TrackedSessionManager(
        fail_exit_call=2,
        exit_exception=RuntimeError("commit response lost"),
        persist_failed_commit=True,
    )
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert result.value.storage_key == s3.uploaded[0]
    assert s3.deleted == []
    assert session_manager.calls == 3
    assert session_manager.active == 0


async def test_create_preserves_model_file_then_propagates_cancellation() -> None:
    """Commit-time cancellation preserves the durable metadata/blob pair."""
    session_manager = _TrackedSessionManager(
        fail_exit_call=2,
        exit_exception=asyncio.CancelledError("stop during commit"),
        persist_failed_commit=True,
    )
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    with pytest.raises(asyncio.CancelledError, match="stop during commit"):
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )

    assert len(s3.uploaded) == 1
    assert s3.deleted == []
    assert session_manager.calls == 3
    assert session_manager.active == 0


async def test_commit_cleanup_failure_does_not_replace_database_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An internal cleanup cancellation cannot hide the commit failure."""
    session_manager = _TrackedSessionManager(fail_exit_call=2)
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    async def failed_compensation(_object_key: str) -> None:
        raise asyncio.CancelledError("cleanup cancelled")

    monkeypatch.setattr(service, "_compensate_uploaded_object", failed_compensation)

    with pytest.raises(RuntimeError, match="metadata commit failed") as raised:
        await service.create(
            session_id="session-1",
            user_id="user-1",
            created_run_index=3,
            filename="report.txt",
            media_type="text/plain",
            body=b"hello",
        )
    assert isinstance(raised.value.__cause__, asyncio.CancelledError)


async def test_create_revalidates_access_after_upload() -> None:
    """Revoked access prevents metadata commit and cleans the uploaded object."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager)
    service, _, workspace_user_repository = _model_file_service(
        session_manager,
        s3_service=s3,
    )
    workspace_user_repository.lock_by_workspace_and_user.return_value = None

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Failure)
    assert s3.deleted == s3.uploaded


async def test_pending_input_resolves_run_index_after_upload() -> None:
    """A concurrent Run advance cannot leave stale pending-file metadata."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )
    run_repository = cast(Any, service.agent_run_repository)
    run_repository.next_run_index.return_value = 4
    session_repository = cast(Any, service.agent_session_repository)
    model_file_repository = cast(Any, service.model_file_repository)
    final_transaction_order: list[str] = []

    async def lock_session(*args: object, **kwargs: object) -> object:
        del args, kwargs
        final_transaction_order.append("lock_session")
        return SimpleNamespace(
            id="session-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
        )

    async def next_run_index(*args: object, **kwargs: object) -> int:
        del args, kwargs
        final_transaction_order.append("next_run_index")
        return 5

    original_create = model_file_repository.create.side_effect

    async def create_metadata(*args: object, **kwargs: object) -> ModelFile:
        final_transaction_order.append("create_metadata")
        return await original_create(*args, **kwargs)

    session_repository.lock_by_id.side_effect = lock_session
    run_repository.next_run_index.side_effect = next_run_index
    model_file_repository.create.side_effect = create_metadata

    def advance_run_index() -> None:
        final_transaction_order.append("upload_completed")

    s3.after_upload = advance_run_index

    result = await service.create_for_pending_input(
        session_id="session-1",
        user_id="user-1",
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert result.value.created_run_index == 5
    run_repository.next_run_index.assert_awaited_once()
    assert final_transaction_order == [
        "upload_completed",
        "lock_session",
        "next_run_index",
        "create_metadata",
    ]
    assert session_manager.calls == 2


async def test_agent_pending_input_rejects_foreign_session_before_upload() -> None:
    """Agent-scoped creation cannot write into another Agent's session."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )

    result = await service.create_for_agent_pending_input(
        agent_id="agent-2",
        session_id="session-1",
        user_id="user-1",
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, ModelFileSessionNotFound)
    assert s3.uploaded == []
    assert s3.deleted == []


async def test_discard_unreferenced_commits_tombstone_before_blob_delete() -> None:
    """Compensation uses short DB sessions around the external blob delete."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )
    created_result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )
    assert isinstance(created_result, Success)
    model_file = created_result.value
    repository = cast(Any, service.model_file_repository)
    repository.get_by_id_for_agent.return_value = model_file
    repository.mark_deleted_if_unpinned.return_value = [model_file]

    await service.discard_unreferenced(
        agent_id="agent-1",
        session_id="session-1",
        model_file_ids=[model_file.id],
    )

    assert s3.deleted == [model_file.storage_key]
    repository.mark_deleted_if_unpinned.assert_awaited_once()
    repository.mark_blob_deleted.assert_awaited_once()
    assert session_manager.active == 0


async def test_discard_unreferenced_preserves_pinned_model_file() -> None:
    """Compensation cannot delete a file that another durable Run has pinned."""
    session_manager = _TrackedSessionManager()
    s3 = _TrackedS3Service(session_manager)
    service, _, _ = _model_file_service(
        session_manager,
        s3_service=s3,
    )
    created_result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_index=3,
        filename="report.txt",
        media_type="text/plain",
        body=b"hello",
    )
    assert isinstance(created_result, Success)
    model_file = created_result.value
    repository = cast(Any, service.model_file_repository)
    repository.get_by_id_for_agent.return_value = model_file
    repository.mark_deleted_if_unpinned.return_value = []

    await service.discard_unreferenced(
        agent_id="agent-1",
        session_id="session-1",
        model_file_ids=[model_file.id],
    )

    assert s3.deleted == []
    repository.mark_blob_deleted.assert_not_awaited()
