"""Runtime-native edit tool tests."""

import json
from datetime import UTC, datetime

import pytest

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.edit import RuntimeEditTarget, make_edit_tool
from azents.engine.tools.runtime_io import (
    RuntimeFileEditResult,
    RuntimeRunnerOperationFailedError,
)


class _FakeRunnerOperations:
    """Capture native edit requests and return a configured result."""

    def __init__(
        self,
        *,
        replacements: int = 1,
        error: RuntimeRunnerOperationFailedError | None = None,
    ) -> None:
        self.replacements = replacements
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def edit_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        deadline_at: datetime,
    ) -> RuntimeFileEditResult:
        self.calls.append(
            {
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "owner_session_id": owner_session_id,
                "path": path,
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
                "deadline_at": deadline_at,
            }
        )
        if self.error is not None:
            raise self.error
        return RuntimeFileEditResult(
            replacements=self.replacements,
            final_cursor="cursor-1",
        )


def _make_tool(
    *,
    replacements: int = 1,
    error: RuntimeRunnerOperationFailedError | None = None,
) -> tuple[FunctionTool, _FakeRunnerOperations]:
    """Create edit tool with one Runner-native operation fake."""
    runner_operations = _FakeRunnerOperations(
        replacements=replacements,
        error=error,
    )

    async def resolve_runtime_target() -> RuntimeEditTarget:
        return RuntimeEditTarget(runtime_id="runtime-1", runner_generation=7)

    tool = make_edit_tool(
        runner_operations=runner_operations,
        resolve_runtime_target=resolve_runtime_target,
        owner_session_id="session-1",
        agent_id="agent-1",
    )
    return tool, runner_operations


class TestEditFile:
    """Native file edit tests."""

    async def test_replace_single_occurrence(self) -> None:
        """Replace one occurrence through one Runner operation."""
        tool, runner_operations = _make_tool()

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/note.txt",
                    "old_string": "world",
                    "new_string": "Python",
                }
            )
        )

        assert result == (
            "Edited /workspace/agent/note.txt: replaced 1 occurrence(s) "
            "of old_string with new_string."
        )
        assert len(runner_operations.calls) == 1
        assert runner_operations.calls[0] == {
            "runtime_id": "runtime-1",
            "runner_generation": 7,
            "owner_session_id": "session-1",
            "path": "/workspace/agent/note.txt",
            "old_string": "world",
            "new_string": "Python",
            "replace_all": False,
            "deadline_at": runner_operations.calls[0]["deadline_at"],
        }
        deadline_at = runner_operations.calls[0]["deadline_at"]
        assert isinstance(deadline_at, datetime)
        assert deadline_at.tzinfo is UTC

    async def test_replace_all_occurrences(self) -> None:
        """Return the Runner-reported all-occurrence replacement count."""
        tool, runner_operations = _make_tool(replacements=3)

        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/data.txt",
                    "old_string": "foo",
                    "new_string": "qux",
                    "replace_all": True,
                }
            )
        )

        assert isinstance(result, str)
        assert "replaced 3 occurrence(s)" in result
        assert runner_operations.calls[0]["replace_all"] is True


class TestEditErrors:
    """Model-visible native edit failure mappings."""

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (
                RuntimeRunnerOperationFailedError(
                    "FILE_EDIT_NOT_FOUND: File does not exist"
                ),
                "File not found",
            ),
            (
                RuntimeRunnerOperationFailedError(
                    "FILE_EDIT_OLD_STRING_NOT_FOUND: old_string was not found"
                ),
                "old_string not found",
            ),
            (
                RuntimeRunnerOperationFailedError("FILE_EDIT_MULTIPLE_MATCHES: 3"),
                "found 3 times",
            ),
            (
                RuntimeRunnerOperationFailedError(
                    "FILE_EDIT_INVALID_UTF8: File is not valid UTF-8 text"
                ),
                "not valid UTF-8",
            ),
            (
                RuntimeRunnerOperationFailedError(
                    "FILE_EDIT_PERMISSION_DENIED: Permission denied while saving file"
                ),
                "read-only scope",
            ),
        ],
    )
    async def test_preserves_existing_error_messages(
        self,
        error: RuntimeRunnerOperationFailedError,
        message: str,
    ) -> None:
        """Map safe native operation codes to existing edit guidance."""
        tool, _runner_operations = _make_tool(error=error)

        with pytest.raises(FunctionToolError, match=message):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/note.txt",
                        "old_string": "old",
                        "new_string": "new",
                    }
                )
            )
