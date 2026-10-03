"""Tests for registered bounded VFS read routing and Skills backend."""

import asyncio
import logging
import os
import re
import signal
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

import azents.services.vfs_read as vfs_read_module
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.vfs import (
    VfsLocation,
    VfsProjection,
    make_vfs_projection,
    make_vfs_source_revision,
    parse_vfs_exact_uri,
    parse_vfs_glob_pattern,
    parse_vfs_search_uri,
)
from azents.services.file_storage import GrepResult, TextReadResult
from azents.services.vfs_read import (
    SkillsVfsReadBackend,
    VfsGlobResult,
    VfsReadBackendCapabilities,
    VfsReadBackendRegistry,
    VfsReadContext,
    VfsReadError,
    VfsReadRouter,
)


@dataclass
class _ProjectionService:
    """Projection reader test double retaining bound-owner evidence."""

    projection: VfsProjection
    owner: SessionExecutionOwner | None = None

    def for_execution(self, owner: SessionExecutionOwner) -> "_ProjectionService":
        self.owner = owner
        return self

    async def load_run_projection(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> VfsProjection:
        assert run_id == "run-1"
        assert agent_id == "agent-1"
        assert session_id == "session-1"
        assert workspace_id == "workspace-1"
        return self.projection


class _AuthorityValidator:
    """Record router admission before backend dispatch."""

    def __init__(self) -> None:
        self.contexts: list[VfsReadContext] = []

    async def validate(self, context: VfsReadContext) -> None:
        self.contexts.append(context)


@dataclass(frozen=True)
class _NoReadBackend:
    """Backend fixture declaring no text-read capability."""

    mount: str = "disabled"
    capabilities: VfsReadBackendCapabilities = VfsReadBackendCapabilities(
        read_text=False,
        grep=False,
        glob=False,
        transfer_read=False,
    )

    async def read_text(
        self,
        context: VfsReadContext,
        location: VfsLocation,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        del context, location, offset, limit, encoding
        raise AssertionError("unsupported operation must not dispatch")

    async def grep(
        self,
        context: VfsReadContext,
        location: VfsLocation,
        *,
        pattern: re.Pattern[str],
        recursive: bool,
        exclude_patterns: Sequence[str],
        max_matching_files: int,
        max_lines_per_file: int,
        max_searched_files: int,
        max_scanned_bytes: int,
    ) -> GrepResult:
        del (
            context,
            location,
            pattern,
            recursive,
            exclude_patterns,
            max_matching_files,
            max_lines_per_file,
            max_searched_files,
            max_scanned_bytes,
        )
        raise AssertionError("unsupported operation must not dispatch")

    async def glob(
        self,
        context: VfsReadContext,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        del context, location, exclude_patterns
        raise AssertionError("unsupported operation must not dispatch")


def _projection() -> VfsProjection:
    revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/azents/alpha/SKILL.md",
                b"first line\nneedle one\nneedle two\n",
                "text/markdown",
            ),
            (
                "azents://skills/azents/alpha/references/guide.txt",
                b"guide needle\n",
                "text/plain",
            ),
            (
                "azents://skills/azents/beta/SKILL.md",
                b"beta\n",
                "text/markdown",
            ),
        ],
    )
    return make_vfs_projection([revision])


def _context() -> VfsReadContext:
    return VfsReadContext(
        run_id="run-1",
        session_id="session-1",
        root_session_id="session-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        associated_user_id=None,
        owner_generation=7,
        memory_enabled=True,
    )


def test_registry_rejects_duplicate_mounts() -> None:
    """Composition fails instead of selecting precedence for duplicate mounts."""
    backend = SkillsVfsReadBackend(_ProjectionService(_projection()))

    with pytest.raises(ValueError, match="Duplicate VFS read backend mount"):
        VfsReadBackendRegistry([backend, backend])


async def test_router_validates_authority_and_rejects_unsupported_operation() -> None:
    """Router checks execution ownership before supported backend I/O only."""
    validator = _AuthorityValidator()
    router = VfsReadRouter(
        registry=VfsReadBackendRegistry([_NoReadBackend()]),
        authority_validator=validator,
    )

    with pytest.raises(VfsReadError, match="does not support"):
        await router.read_text(
            _context(),
            "azents://disabled/file.txt",
            offset=0,
            limit=100,
            encoding="utf-8",
        )

    assert validator.contexts == []


async def test_router_dispatches_supported_read_after_authority_validation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Supported dispatch validates execution ownership before backend I/O."""
    service = _ProjectionService(_projection())
    validator = _AuthorityValidator()
    router = VfsReadRouter(
        registry=VfsReadBackendRegistry([SkillsVfsReadBackend(service)]),
        authority_validator=validator,
    )

    with caplog.at_level(logging.INFO):
        result = await router.read_text(
            _context(),
            "azents://skills/azents/alpha/SKILL.md",
            offset=0,
            limit=10,
            encoding="utf-8",
        )

    assert result.text == "first line"
    assert validator.contexts == [_context()]
    record = next(
        item
        for item in caplog.records
        if item.getMessage() == "VFS read operation completed"
    )
    fields = vars(record)
    assert fields["vfs_mount"] == "skills"
    assert fields["vfs_operation"] == "read_text"
    assert fields["visited_bytes"] == 10
    assert "text" not in fields


async def test_skills_backend_reads_bounded_verified_text() -> None:
    """Exact reads preserve immutable projection integrity and character paging."""
    service = _ProjectionService(_projection())
    backend = SkillsVfsReadBackend(service)

    result = await backend.read_text(
        _context(),
        location=_location("azents://skills/azents/alpha/SKILL.md"),
        offset=11,
        limit=6,
        encoding="utf-8",
    )

    assert result.text == "needle"
    assert result.start_character == 11
    assert result.end_character == 17
    assert result.truncated is True
    assert service.owner == SessionExecutionOwner(
        session_id="session-1",
        owner_generation=7,
    )


async def test_skills_backend_grep_is_bounded_and_canonical() -> None:
    """Regex search returns canonical paths with per-file line truncation."""
    backend = SkillsVfsReadBackend(_ProjectionService(_projection()))

    result = await backend.grep(
        _context(),
        location=_search_location("azents://skills/azents/alpha"),
        pattern=re.compile("needle"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=10,
        max_lines_per_file=1,
        max_searched_files=10,
        max_scanned_bytes=10_000,
    )

    assert result.matched_file_count == 2
    assert result.files[0].path == "azents://skills/azents/alpha/SKILL.md"
    assert result.files[0].lines[0].line_number == 2
    assert result.files[0].truncated is True
    assert result.files[1].path.endswith("references/guide.txt")


async def test_skills_backend_kills_regex_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Kill and reap non-cooperative sandbox work without a costly regex fixture."""
    started_marker = tmp_path / "regex-worker-started"
    processes: list[asyncio.subprocess.Process] = []
    create_process = asyncio.create_subprocess_exec

    async def observe_process(
        program: str,
        *args: str,
        stdin: int,
        stdout: int,
        stderr: int,
    ) -> asyncio.subprocess.Process:
        """Delegate actual creation and retain the child for cleanup evidence."""
        process = await create_process(
            program,
            *args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        processes.append(process)
        return process

    # The isolated exec cannot inherit a monkeypatched parent callback. This
    # benign child consumes the real request, signals readiness, then blocks
    # independently of the parent's deadline. Production timeout/kill/wait stays
    # unchanged; no costly expression, synthetic TimeoutError, or kill mock is used.
    monkeypatch.setattr(
        vfs_read_module,
        "_REGEX_GREP_WORKER",
        f"""
import json
import os
import threading
from pathlib import Path
import sys

json.load(sys.stdin)
Path({str(started_marker)!r}).write_text(str(os.getpid()), encoding="utf-8")
threading.Event().wait()
""",
    )
    monkeypatch.setattr(
        vfs_read_module.asyncio,
        "create_subprocess_exec",
        observe_process,
    )
    # Allow interpreter startup while keeping the original one-second outer bound.
    monkeypatch.setattr(
        vfs_read_module,
        "_SKILLS_OPERATION_MAX_SECONDS",
        0.4,
    )
    revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/azents/slow/SKILL.md",
                b"needle\n",
                "text/markdown",
            )
        ],
    )
    backend = SkillsVfsReadBackend(_ProjectionService(make_vfs_projection([revision])))
    started_at = time.monotonic()

    result = await backend.grep(
        _context(),
        location=_search_location("azents://skills/azents/slow"),
        pattern=re.compile("needle"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=10,
        max_lines_per_file=10,
        max_searched_files=10,
        max_scanned_bytes=200_000,
    )

    assert result.truncated is True
    assert result.stopped_reason == "deadline"
    assert len(processes) == 1
    process = processes[0]
    assert started_marker.read_text(encoding="utf-8") == str(process.pid)
    return_code = process.returncode
    assert return_code is not None and return_code != 0
    if os.name == "posix":
        assert return_code == -signal.SIGKILL
    assert await asyncio.wait_for(process.wait(), timeout=0.1) == return_code
    assert time.monotonic() - started_at < 1


async def test_skills_backend_glob_restores_sorted_canonical_uris() -> None:
    """Recursive brace glob uses canonical URI identity and sorted output."""
    backend = SkillsVfsReadBackend(_ProjectionService(_projection()))

    result = await backend.glob(
        _context(),
        location=_glob_location("azents://skills/azents/{alpha,beta}/**/*.md"),
        exclude_patterns=(),
    )

    assert result == VfsGlobResult(
        uris=(
            "azents://skills/azents/alpha/SKILL.md",
            "azents://skills/azents/beta/SKILL.md",
        ),
        truncated=False,
    )


def _location(uri: str) -> VfsLocation:
    return parse_vfs_exact_uri(uri)


def _search_location(uri: str) -> VfsLocation:
    return parse_vfs_search_uri(uri)


def _glob_location(pattern: str) -> VfsLocation:
    return parse_vfs_glob_pattern(pattern)
