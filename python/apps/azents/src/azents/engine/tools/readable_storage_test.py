"""Tests for Runtime-independent generic readable storage routing."""

from unittest.mock import AsyncMock, Mock

import pytest

from azents.core.enums import AgentRuntimeCapability
from azents.core.runtime_capabilities import RuntimeCapabilityResolver
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.readable_storage import RoutedReadableStorage
from azents.services.file_storage import FileStorage, GrepResult, TextReadResult
from azents.services.vfs_read import VfsGlobResult, VfsReadContext, VfsReadRouter


def _context() -> VfsReadContext:
    return VfsReadContext(
        run_id="run-1",
        session_id="session-1",
        root_session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        associated_user_id=None,
        owner_generation=1,
        memory_enabled=True,
    )


def _resolver(*, managed: bool) -> RuntimeCapabilityResolver:
    return RuntimeCapabilityResolver.from_agent(
        state=(
            AgentRuntimeCapability.MANAGED if managed else AgentRuntimeCapability.NONE
        ),
        version=1,
    )


async def test_vfs_read_does_not_require_runtime_capability() -> None:
    """Canonical VFS reads remain available when Runtime is unavailable."""
    router = AsyncMock(spec=VfsReadRouter)
    router.read_text.return_value = TextReadResult(
        text="skill body",
        start_character=0,
        end_character=10,
        truncated=False,
    )
    runtime_factory = Mock()
    storage = RoutedReadableStorage(
        agent_id="agent-1",
        vfs_router=router,
        vfs_context=_context(),
        runtime_storage_factory=runtime_factory,
        runtime_capability_resolver=_resolver(managed=False),
    )

    result = await storage.get_text(
        "azents://skills/azents/demo/SKILL.md",
        agent_id="agent-1",
        offset=0,
        limit=100,
        encoding="utf-8",
    )

    assert result.text == "skill body"
    runtime_factory.assert_not_called()


async def test_absolute_read_requires_runtime_capability_before_storage() -> None:
    """Absolute paths fail with the stable capability error before Runtime I/O."""
    runtime_factory = Mock()
    storage = RoutedReadableStorage(
        agent_id="agent-1",
        vfs_router=AsyncMock(spec=VfsReadRouter),
        vfs_context=_context(),
        runtime_storage_factory=runtime_factory,
        runtime_capability_resolver=_resolver(managed=False),
    )

    with pytest.raises(FunctionToolError) as raised:
        await storage.get_text(
            "/workspace/agent/file.txt",
            agent_id="agent-1",
            offset=0,
            limit=100,
            encoding="utf-8",
        )

    assert raised.value.metadata == {
        "kind": "runtime_capability_denied",
        "capability": "runtime_filesystem",
        "reason_code": "runtime_capability_unavailable",
    }
    runtime_factory.assert_not_called()


async def test_absolute_read_preserves_runtime_storage_behavior() -> None:
    """Authorized absolute paths delegate unchanged to Runtime FileStorage."""
    runtime_storage = AsyncMock(spec=FileStorage)
    runtime_storage.get_text.return_value = TextReadResult(
        text="runtime body",
        start_character=0,
        end_character=12,
        truncated=False,
    )
    storage = RoutedReadableStorage(
        agent_id="agent-1",
        vfs_router=AsyncMock(spec=VfsReadRouter),
        vfs_context=_context(),
        runtime_storage_factory=Mock(return_value=runtime_storage),
        runtime_capability_resolver=_resolver(managed=True),
    )

    result = await storage.get_text(
        "/workspace/agent/file.txt",
        agent_id="agent-1",
        offset=0,
        limit=100,
        encoding="utf-8",
    )

    assert result.text == "runtime body"
    runtime_storage.get_text.assert_awaited_once_with(
        "/workspace/agent/file.txt",
        agent_id="agent-1",
        offset=0,
        limit=100,
        encoding="utf-8",
    )


async def test_vfs_glob_and_grep_preserve_normalized_results() -> None:
    """Generic storage adapts normalized VFS glob and grep contracts."""
    router = AsyncMock(spec=VfsReadRouter)
    router.glob.return_value = VfsGlobResult(
        uris=("azents://skills/azents/demo/SKILL.md",),
        truncated=False,
    )
    router.grep.return_value = GrepResult(
        files=(),
        searched_file_count=1,
        matched_file_count=0,
        truncated=False,
    )
    storage = RoutedReadableStorage(
        agent_id="agent-1",
        vfs_router=router,
        vfs_context=_context(),
        runtime_storage_factory=None,
        runtime_capability_resolver=_resolver(managed=False),
    )

    globbed = await storage.glob(
        "azents://skills/**/*.md",
        agent_id="agent-1",
        exclude_patterns=None,
    )
    grep_result = await storage.grep(
        "azents://skills",
        agent_id="agent-1",
        pattern="needle",
    )

    assert [entry.uri for entry in globbed.files] == [
        "azents://skills/azents/demo/SKILL.md"
    ]
    assert grep_result.searched_file_count == 1
    compiled = router.grep.await_args.kwargs["pattern"]
    assert compiled.pattern == "needle"


async def test_relative_location_is_rejected_without_fallback() -> None:
    """Non-absolute non-VFS locations never fall through to Runtime guessing."""
    storage = RoutedReadableStorage(
        agent_id="agent-1",
        vfs_router=AsyncMock(spec=VfsReadRouter),
        vfs_context=_context(),
        runtime_storage_factory=None,
        runtime_capability_resolver=_resolver(managed=True),
    )

    with pytest.raises(ValueError, match="absolute Runtime path"):
        await storage.get_text(
            "relative/file.txt",
            agent_id="agent-1",
            offset=0,
            limit=100,
            encoding="utf-8",
        )
