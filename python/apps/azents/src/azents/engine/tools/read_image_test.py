"""read_image tool tests."""

import datetime
import json

import pytest
from azcommon.result import Failure, Result, Success

from azents.core.enums import ModelFileStatus
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tools.read_image import make_read_image_tool
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.model_file.data import ModelFile
from azents.services.model_file import (
    ModelFileCreateError,
    ModelFileOversized,
    ModelFileService,
)

_MODEL_FILE = ModelFile(
    id="m" * 32,
    workspace_id="workspace-1",
    session_id="session-1",
    agent_id="agent-1",
    name="photo.jpg",
    media_type="image/jpeg",
    kind="image",
    size_bytes=10,
    created_run_index=7,
    expires_after_run_index=9,
    storage_key="model-files/workspace-1/session-1/m",
    status=ModelFileStatus.AVAILABLE,
    normalized_format="jpeg",
    sha256="2" * 64,
    metadata={},
    created_at=datetime.datetime.now(datetime.UTC),
    degraded_at=None,
    deleted_at=None,
)


class _FakeModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self, result: Result[ModelFile, ModelFileCreateError]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def create(
        self,
        *,
        session_id: str,
        user_id: str,
        created_run_index: int,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Success[ModelFile] | Failure[ModelFileCreateError]:
        """Record creation input and return specified result."""
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "created_run_index": created_run_index,
                "filename": filename,
                "media_type": media_type,
                "body": body,
                "metadata": metadata,
            }
        )
        return self.result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
) -> tuple[FunctionTool, FakeSharedStorage, _FakeModelFileService]:
    """Create read_image tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    model_file_service = _FakeModelFileService(Success(_MODEL_FILE))
    tool = make_read_image_tool(
        session_storage=storage,
        model_file_service=model_file_service,
        session_id="session-1",
        agent_id="",
        user_id="user-1",
        run_index=7,
    )
    return tool, storage, model_file_service


# ---------------------------------------------------------------------------
# TestReadImageFromSessionData
# ---------------------------------------------------------------------------


class TestReadImageFromSessionData:
    """Image read tests from session data."""

    async def test_read_png(self) -> None:
        """Read PNG image from agent/photo.png URI."""
        # Given: PNG file in session data
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        tool, _, service = _make_tool(files={"/workspace/agent/photo.png": png_data})

        # When: call read_image
        result = await tool.handler(json.dumps({"path": "/workspace/agent/photo.png"}))

        # Then: FunctionToolResult includes FilePart
        assert isinstance(result, FunctionToolResult)
        assert isinstance(result.output, list)
        assert result.output[0]["type"] == "text"
        assert result.output[1]["type"] == "file"
        assert result.output[1]["model_file_id"] == "m" * 32
        assert service.calls[0]["filename"] == "photo.png"
        assert service.calls[0]["created_run_index"] == 7
        assert service.calls[0]["media_type"] == "image/png"
        assert service.calls[0]["body"] == png_data

    async def test_read_jpeg(self) -> None:
        """Read JPEG image from agent/photo.jpg URI."""
        # Given: JPEG file in session data
        jpeg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        tool, _, _ = _make_tool(files={"/workspace/agent/photo.jpg": jpeg_data})

        # When: call read_image
        result = await tool.handler(json.dumps({"path": "/workspace/agent/photo.jpg"}))

        # Then: JPEG MIME type
        assert isinstance(result, FunctionToolResult)
        assert isinstance(result.output, list)
        assert result.output[1]["media_type"] == "image/jpeg"

    async def test_read_webp(self) -> None:
        """Read WebP image from agent/photo.webp URI."""
        # Given: WebP file in session data
        webp_data = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 50
        tool, _, service = _make_tool(files={"/workspace/agent/photo.webp": webp_data})

        # When: call read_image
        result = await tool.handler(json.dumps({"path": "/workspace/agent/photo.webp"}))

        # Then: WebP MIME type
        assert isinstance(result, FunctionToolResult)
        assert service.calls[0]["media_type"] == "image/webp"


# ---------------------------------------------------------------------------
# TestReadImageErrors
# ---------------------------------------------------------------------------


class TestReadImageErrors:
    """Error case tests."""

    async def test_unsupported_path(self) -> None:
        """Disallowed path raises FunctionToolError."""
        tool, _, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(json.dumps({"path": "/tmp/image.png"}))

    async def test_unsupported_extension(self) -> None:
        """Unsupported extension raises FunctionToolError."""
        tool, _, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="Unsupported image format"):
            await tool.handler(json.dumps({"path": "/workspace/agent/document.pdf"}))

    async def test_no_extension(self) -> None:
        """File without extension raises FunctionToolError."""
        tool, _, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="Unsupported image format"):
            await tool.handler(json.dumps({"path": "/workspace/agent/noextension"}))

    async def test_file_not_found(self) -> None:
        """Nonexistent file raises FunctionToolError."""
        tool, _, _ = _make_tool(files={})
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(json.dumps({"path": "/workspace/agent/missing.png"}))

    async def test_image_too_large(self) -> None:
        """Image exceeding 20MB raises FunctionToolError."""
        # Given: 21MB image
        large_data = b"\x00" * (21 * 1024 * 1024)
        tool, _, _ = _make_tool(files={"/workspace/agent/huge.png": large_data})

        # When/Then: FunctionToolError
        with pytest.raises(FunctionToolError, match="Image too large"):
            await tool.handler(json.dumps({"path": "/workspace/agent/huge.png"}))

    async def test_model_file_oversized_returns_text_placeholder(self) -> None:
        """ModelFile size cap exceedance becomes text placeholder without file part."""
        failure: Failure[ModelFileCreateError] = Failure(
            ModelFileOversized(max_bytes=1_000_000, actual_bytes=1_000_001)
        )
        storage = FakeSharedStorage({"/workspace/agent/photo.png": b"small"})
        tool = make_read_image_tool(
            session_storage=storage,
            model_file_service=_FakeModelFileService(failure),
            session_id="session-1",
            agent_id="",
            user_id="user-1",
            run_index=7,
        )

        result = await tool.handler(json.dumps({"path": "/workspace/agent/photo.png"}))

        assert isinstance(result, FunctionToolResult)
        assert isinstance(result.output, list)
        assert result.output == [
            {
                "type": "text",
                "text": (
                    "File size exceeds the allowed limit: "
                    "1000001 bytes > 1000000 bytes. "
                    "This file was not stored as model input."
                ),
            }
        ]


# ---------------------------------------------------------------------------
# TestReadImageRuntimeStorage
# ---------------------------------------------------------------------------


class TestReadImageRuntimeStorage:
    """Image read tests based on runtime storage."""

    async def test_reads_from_session_storage(self) -> None:
        """read_image reads image from runtime session_storage."""
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        session_ss = FakeSharedStorage(files={"/workspace/agent/photo.png": png_data})
        tool = make_read_image_tool(
            session_storage=session_ss,
            model_file_service=_FakeModelFileService(Success(_MODEL_FILE)),
            session_id="session-1",
            agent_id="",
            user_id="user-1",
            run_index=7,
        )

        # When: call read_image
        result = await tool.handler(json.dumps({"path": "/workspace/agent/photo.png"}))

        # Then: read from session_storage
        assert isinstance(result, FunctionToolResult)
        assert isinstance(result.output, list)
        text = result.output[0].get("text")
        assert isinstance(text, str)
        assert "/workspace/agent/photo.png" in text


# ---------------------------------------------------------------------------
# TestFileStorageSystemPrompt
# ---------------------------------------------------------------------------
