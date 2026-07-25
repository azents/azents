"""ModelFile materializer tests."""

import datetime

import pytest
from azcommon.result import Failure, Result, Success

from azents.core.enums import EventKind, ModelFileStatus
from azents.engine.events.file_parts import RequestLocalModelFileResolver
from azents.engine.events.model_file_materializer import ModelFileMaterializer
from azents.engine.events.types import (
    ClientToolResultPayload,
    Event,
    FileOutputPart,
)
from azents.repos.model_file.data import ModelFile
from azents.services.model_file import (
    ModelFileDownload,
    ModelFileNotFound,
    ModelFileResolveError,
)
from azents.services.session_resource_authority import SessionResourceAuthority

_NOW = datetime.datetime.now(datetime.UTC)


class _Downloader:
    """ModelFile downloader for tests."""

    def __init__(
        self,
        result: Result[ModelFileDownload, ModelFileResolveError],
    ) -> None:
        self.result = result
        self.calls: list[tuple[str, SessionResourceAuthority]] = []

    async def download_for_authority(
        self,
        *,
        model_file_id: str,
        authority: SessionResourceAuthority,
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        """Record Session/Run-authorized download call."""
        self.calls.append((model_file_id, authority))
        return self.result


@pytest.mark.asyncio
async def test_materializer_downloads_by_model_file_id_without_uri() -> None:
    """FilePart entity reference is model_file_id, not URI."""
    resolver = RequestLocalModelFileResolver()
    downloader = _Downloader(
        Success(
            ModelFileDownload(
                model_file=_model_file(),
                body=b"image-bytes",
            )
        )
    )
    materializer = ModelFileMaterializer(
        model_file_service=downloader,
        resolver=resolver,
        authority=_authority(),
    )
    part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/jpeg",
        name="image.jpg",
        size=11,
        kind="image",
    )

    await materializer.materialize(transcript=[_tool_result_event(part)])

    assert downloader.calls == [("m" * 32, _authority())]
    content = resolver.resolve(part)
    assert content is not None
    assert content.data_url == "data:image/jpeg;base64,aW1hZ2UtYnl0ZXM="


@pytest.mark.asyncio
async def test_materializer_leaves_resolver_empty_when_download_fails() -> None:
    """Leave unavailable ModelFile empty so lowerer can create placeholder."""
    resolver = RequestLocalModelFileResolver()
    downloader = _Downloader(Failure(ModelFileNotFound()))
    materializer = ModelFileMaterializer(
        model_file_service=downloader,
        resolver=resolver,
        authority=_authority(),
    )
    part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="application/pdf",
        name="doc.pdf",
        size=11,
        kind="document",
    )

    await materializer.materialize(transcript=[_tool_result_event(part)])

    assert downloader.calls == [("m" * 32, _authority())]
    assert resolver.resolve(part) is None


@pytest.mark.asyncio
async def test_materializer_skips_download_without_resource_authority() -> None:
    """Do not materialize transcript FileParts without canonical authority."""
    resolver = RequestLocalModelFileResolver()
    downloader = _Downloader(
        Success(ModelFileDownload(model_file=_model_file(), body=b"x"))
    )
    materializer = ModelFileMaterializer(
        model_file_service=downloader,
        resolver=resolver,
        authority=None,
    )
    part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/jpeg",
        name="image.jpg",
        size=1,
        kind="image",
    )

    await materializer.materialize(transcript=[_tool_result_event(part)])

    assert downloader.calls == []
    assert resolver.resolve(part) is None


def _tool_result_event(part: FileOutputPart) -> Event:
    """Create tool result event with FilePart."""
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-1",
            name="read_image",
            status="completed",
            output=[part],
            wire_dialect="json_function",
        ),
        created_at=_NOW,
    )


def _model_file() -> ModelFile:
    """Create ModelFile for tests."""
    return ModelFile(
        id="m" * 32,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        name="image.jpg",
        media_type="image/jpeg",
        kind="image",
        size_bytes=11,
        created_run_id="run-1",
        created_run_index=1,
        storage_key="model-files/workspace-1/session-1/m",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="jpeg",
        sha256="2" * 64,
        metadata={},
        created_at=_NOW,
        deleted_at=None,
    )


def _authority() -> SessionResourceAuthority:
    """Create canonical Session/Run authority for tests."""
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-2",
        run_index=2,
        owner_generation=1,
    )
