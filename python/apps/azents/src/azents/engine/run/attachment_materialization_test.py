"""Metadata-first model-input admission for retained Exchange attachments."""

from datetime import UTC, datetime, timedelta

import pytest
from azcommon.result import Failure, Result, Success

from azents.core.enums import ExchangeFileOrigin, ExchangeFileStatus
from azents.core.exchange_file_errors import (
    FileAccessDenied,
    FileNotFound,
    SessionNotFound,
)
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.engine.run.resolve import (
    _materialize_admitted_input_exchange_file_attachment,
    _materialize_user_input_exchange_file_attachment,
)
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile
from azents.services.exchange_file import (
    ExchangeFileDownload,
    ExchangeFileError,
    ExchangeFileService,
)
from azents.services.model_file import (
    ModelFileCreateError,
    ModelFileInvalidImage,
    ModelFileService,
)


class _Exchange(ExchangeFileService):
    """Expose trusted metadata and count attempts to open the original body."""

    def __init__(self, file: ExchangeFile) -> None:
        self.file = file
        self.body_reads = 0

    async def resolve_admitted_input_attachment_metadata(
        self, *, uri: str, agent_id: str, session_id: str
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        assert uri == self.file.uri
        return Success(self.file)

    async def resolve_attachment_metadata_for_agent(
        self, *, uri: str, agent_id: str, session_id: str, user_id: str
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        assert uri == self.file.uri
        return Success(self.file)

    async def resolve_admitted_input_attachment(
        self, *, uri: str, agent_id: str, session_id: str
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        self.body_reads += 1
        return Success(ExchangeFileDownload(file=self.file, body=b"x"))

    async def resolve_attachment_for_agent(
        self, *, uri: str, agent_id: str, session_id: str, user_id: str
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        self.body_reads += 1
        return Success(ExchangeFileDownload(file=self.file, body=b"x"))


class _ModelFiles(ModelFileService):
    """Record eligible materialization without allocating a large test body."""

    def __init__(self) -> None:
        self.created = 0

    async def create(
        self,
        *,
        authority: SessionResourceAuthority,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Result[ModelFile, ModelFileCreateError]:
        self.created += 1
        return Failure(ModelFileInvalidImage())


def _file(media_type: str, size: int) -> ExchangeFile:
    now = datetime.now(UTC)
    return ExchangeFile(
        id="file-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="workspace-1/file-1",
        filename="attachment.bin",
        media_type=media_type,
        size_bytes=size,
        sha256="a" * 64,
        retention_root_session_id="session-1",
        retention_bound_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
    )


def _authority() -> SessionResourceAuthority:
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("admitted", (True, False))
@pytest.mark.parametrize(
    ("media_type", "size"),
    (
        ("application/pdf", 1_000_001),
        ("image/png", 20 * 1024 * 1024 + 1),
        ("image/png", 128 * 1024 * 1024),
    ),
)
async def test_large_attachment_remains_available_without_original_body_read(
    admitted: bool, media_type: str, size: int
) -> None:
    file = _file(media_type, size)
    exchange = _Exchange(file)
    model_files = _ModelFiles()
    if admitted:
        materialized = await _materialize_admitted_input_exchange_file_attachment(
            uri=file.uri,
            authority=_authority(),
            exchange_file_service=exchange,
            model_file_service=model_files,
        )
    else:
        materialized = await _materialize_user_input_exchange_file_attachment(
            uri=file.uri,
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            exchange_file_service=exchange,
            model_file_service=model_files,
        )

    assert materialized is not None
    assert materialized.file_part is None
    assert materialized.attachment.availability == "available"
    assert materialized.attachment.uri == file.uri
    assert materialized.attachment.size == size
    assert materialized.attachment.text_preview is not None
    assert "This file was not stored as model input." in (
        materialized.attachment.text_preview
    )
    assert exchange.body_reads == 0
    assert model_files.created == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "size"),
    (("application/pdf", 1_000_000), ("image/png", 20 * 1024 * 1024)),
)
async def test_eligible_metadata_retains_the_existing_materialization_path(
    media_type: str, size: int
) -> None:
    file = _file(media_type, size)
    exchange = _Exchange(file)
    model_files = _ModelFiles()

    materialized = await _materialize_admitted_input_exchange_file_attachment(
        uri=file.uri,
        authority=_authority(),
        exchange_file_service=exchange,
        model_file_service=model_files,
    )

    assert materialized is not None
    assert materialized.attachment.availability == "available"
    assert exchange.body_reads == 1
    assert model_files.created == 1
