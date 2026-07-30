"""read_image tool tests."""

import datetime
import json
from dataclasses import dataclass, field
from typing import cast

import pytest

from azents.core.enums import ModelFileStatus
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tools.read_image import make_read_image_tool
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.model_file.data import ModelFile
from azents.runtime.transfer.runtime_image_read import (
    RuntimeImageReadError,
    RuntimeImageReadModelFileOversized,
    RuntimeImageReadRequest,
    RuntimeImageReadService,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.model_file import ModelFileOversized, ModelFileService
from azents.services.session_resource_authority import SessionResourceAuthority

_MODEL_FILE = ModelFile(
    id="m" * 32,
    workspace_id="workspace-1",
    session_id="session-1",
    agent_id="agent-1",
    name="photo.jpg",
    media_type="image/jpeg",
    kind="image",
    size_bytes=10,
    created_run_id="run-1",
    created_run_index=7,
    storage_key="model-files/workspace-1/session-1/m",
    status=ModelFileStatus.AVAILABLE,
    normalized_format="jpeg",
    sha256="2" * 64,
    metadata={},
    created_at=datetime.datetime.now(datetime.UTC),
    deleted_at=None,
)


@dataclass
class _FakeRuntimeImageReadService:
    """Record Runtime-transfer image read requests."""

    result: ModelFile | RuntimeImageReadError = field(
        default_factory=lambda: _MODEL_FILE
    )
    calls: list[RuntimeImageReadRequest] = field(default_factory=list)

    async def read(self, request: RuntimeImageReadRequest) -> ModelFile:
        """Return the configured materialization result."""
        self.calls.append(request)
        if isinstance(self.result, RuntimeImageReadError):
            raise self.result
        return self.result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
) -> tuple[FunctionTool, FakeSharedStorage, _FakeRuntimeImageReadService]:
    """Create read_image tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    runtime_image_read_service = _FakeRuntimeImageReadService()
    tool = make_read_image_tool(
        session_storage=storage,
        model_file_service=cast(ModelFileService, object()),
        authority=_authority(),
        runtime_image_read_service=cast(
            RuntimeImageReadService, runtime_image_read_service
        ),
        resolve_runtime_target=_target,
    )
    return tool, storage, runtime_image_read_service


async def _target() -> ServerToRuntimeTarget:
    """Return the Runtime target expected by the transfer consumer."""
    return ServerToRuntimeTarget(runtime_id="runtime-1", desired_generation=3)


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
        assert service.calls[0].filename == "photo.png"
        assert service.calls[0].authority.run_index == 7
        assert service.calls[0].media_type == "image/png"
        assert service.calls[0].expected_size == len(png_data)
        assert service.calls[0].runtime_path == "/workspace/agent/photo.png"

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
        assert service.calls[0].media_type == "image/webp"


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
        storage = FakeSharedStorage({"/workspace/agent/photo.png": b"small"})
        transfer = _FakeRuntimeImageReadService(
            RuntimeImageReadModelFileOversized(
                ModelFileOversized(max_bytes=1_000_000, actual_bytes=1_000_001)
            )
        )
        tool = make_read_image_tool(
            session_storage=storage,
            model_file_service=cast(ModelFileService, object()),
            authority=_authority(),
            runtime_image_read_service=cast(RuntimeImageReadService, transfer),
            resolve_runtime_target=_target,
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
        tool, _, _ = _make_tool(files={"/workspace/agent/photo.png": png_data})

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


def _authority() -> SessionResourceAuthority:
    """Create canonical Session resource authority for read_image tests."""
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="root-session-1",
        run_id="run-1",
        run_index=7,
        owner_generation=1,
    )
