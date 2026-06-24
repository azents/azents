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

_NOW = datetime.datetime.now(datetime.UTC)


class _Downloader:
    """ModelFile downloader for tests."""

    def __init__(
        self,
        result: Result[ModelFileDownload, ModelFileResolveError],
    ) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    async def download_for_agent(
        self,
        *,
        model_file_id: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        """Record agent-scoped download call."""
        self.calls.append((model_file_id, agent_id, user_id))
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
        user_id="user-1",
        agent_id="agent-1",
    )
    part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="image/jpeg",
        name="image.jpg",
        size=11,
        kind="image",
    )

    await materializer.materialize(transcript=[_tool_result_event(part)])

    assert downloader.calls == [("m" * 32, "agent-1", "user-1")]
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
        user_id="user-1",
        agent_id="agent-1",
    )
    part = FileOutputPart(
        model_file_id="m" * 32,
        media_type="application/pdf",
        name="doc.pdf",
        size=11,
        kind="document",
    )

    await materializer.materialize(transcript=[_tool_result_event(part)])

    assert downloader.calls == [("m" * 32, "agent-1", "user-1")]
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
        created_run_index=1,
        expires_after_run_index=3,
        storage_key="model-files/workspace-1/session-1/m",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="jpeg",
        sha256="2" * 64,
        metadata={},
        created_at=_NOW,
        degraded_at=None,
        deleted_at=None,
    )
