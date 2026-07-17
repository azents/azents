"""Tests for the testenv runtime hook QA toolkit."""

import asyncio
from pathlib import Path

import pytest

from azents.engine.run.types import FunctionTool
from azents.testing.runtime_hooks import (
    TestenvRuntimeHookQAConfig as RuntimeHookQAConfig,
)
from azents.testing.runtime_hooks import (
    TestenvRuntimeHookQAToolkit as RuntimeHookQAToolkit,
)


class _RuntimeHookQAToolkitForTest(RuntimeHookQAToolkit):
    """Expose the probe tool for focused behavior tests."""

    def make_probe_tool(self) -> FunctionTool:
        """Return the probe tool under test."""
        return self._make_probe_tool()


@pytest.mark.asyncio
async def test_probe_waits_for_release_file(tmp_path: Path) -> None:
    """Keep the probe blocked until the configured release file exists."""
    release_file = tmp_path / "release"
    toolkit = _RuntimeHookQAToolkitForTest(
        RuntimeHookQAConfig(release_file_path=str(release_file))
    )
    tool = toolkit.make_probe_tool()

    task = asyncio.ensure_future(tool.handler('{"marker":"blocked"}'))
    await asyncio.sleep(0.2)
    assert not task.done()

    release_file.touch()

    assert await asyncio.wait_for(task, timeout=1) == (
        "runtime hook qa raw output: blocked"
    )
