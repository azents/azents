"""Tests for the GPT V4A Runtime apply_patch function tool."""

import asyncio
import json
import logging
from datetime import datetime

import pytest

from azents.engine.run.client_tool_compatibility import ClientToolModelProfile
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    PlaintextCustomToolHandler,
)
from azents.engine.tools.apply_patch import (
    RuntimeApplyPatchOperationClient,
    RuntimePatchTarget,
    make_apply_patch_tool,
)
from azents.engine.tools.runtime_io import (
    RuntimeFileApplyPatchFailedError,
    RuntimeFileApplyPatchFailure,
    RuntimeFileApplyPatchResult,
    RuntimeFilePatchChange,
    RuntimeFilePatchOperation,
)

_PATCH = """*** Begin Patch
*** Add File: new.txt
+secret replacement text
*** End Patch"""


class _RunnerOperations:
    """Record one apply_patch call and return a configured terminal outcome."""

    def __init__(
        self,
        outcome: RuntimeFileApplyPatchResult | RuntimeFileApplyPatchFailedError,
        *,
        wait_for_cancellation: bool = False,
    ) -> None:
        self.outcome = outcome
        self.wait_for_cancellation = wait_for_cancellation
        self.started = asyncio.Event()
        self.calls: list[dict[str, object]] = []

    async def apply_patch(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        base_path: str,
        patch: bytes,
        schema_version: int,
        deadline_at: datetime,
    ) -> RuntimeFileApplyPatchResult:
        """Return or raise the configured terminal outcome."""
        self.calls.append(
            {
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "owner_session_id": owner_session_id,
                "base_path": base_path,
                "patch": patch,
                "schema_version": schema_version,
                "deadline_at": deadline_at,
            }
        )
        self.started.set()
        if self.wait_for_cancellation:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
        if isinstance(self.outcome, RuntimeFileApplyPatchFailedError):
            raise self.outcome
        return self.outcome


async def _resolve_runtime_target() -> RuntimePatchTarget:
    return RuntimePatchTarget(runtime_id="runtime-1", runner_generation=7)


def _tool(runner_operations: RuntimeApplyPatchOperationClient) -> FunctionTool:
    return make_apply_patch_tool(
        runner_operations=runner_operations,
        resolve_runtime_target=_resolve_runtime_target,
        owner_session_id="session-1",
        agent_id="agent-1",
    )


async def test_apply_patch_schema_profile_and_success_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = _RunnerOperations(
        RuntimeFileApplyPatchResult(
            changes=(
                RuntimeFilePatchChange(
                    path="new.txt",
                    action="add",
                    added_lines=1,
                    removed_lines=0,
                    content_sha256="a" * 64,
                ),
            ),
            final_cursor="1-0",
        )
    )
    tool = _tool(runner)

    with caplog.at_level(logging.INFO):
        result = await tool.handler(
            json.dumps({"base_path": "/workspace/project", "patch": _PATCH})
        )

    assert tool.spec.name == "apply_patch"
    assert tool.spec.input_schema["additionalProperties"] is False
    assert tool.required_client_tool_model_profile is ClientToolModelProfile.V4A_PATCH
    assert [variant.wire_dialect for variant in tool.wire_variants] == [
        "json_function",
        "plaintext_custom",
    ]
    assert isinstance(result, FunctionToolResult)
    assert result.output == (
        "Applied patch under /workspace/project: 1 file changed (+1 -0):\nA new.txt"
    )
    assert result.metadata == {
        "kind": "apply_patch_result",
        "base_path": "/workspace/project",
        "changes": [
            {
                "path": "new.txt",
                "action": "add",
                "added_lines": 1,
                "removed_lines": 0,
                "content_sha256": "a" * 64,
            }
        ],
        "exact": True,
    }
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["runtime_id"] == "runtime-1"
    assert call["runner_generation"] == 7
    assert call["owner_session_id"] == "session-1"
    assert call["base_path"] == "/workspace/project"
    assert call["patch"] == _PATCH.encode()
    assert call["schema_version"] == 1
    assert _PATCH not in caplog.text
    assert "secret replacement text" not in caplog.text


async def test_plaintext_custom_apply_patch_preserves_v4a_body() -> None:
    runner = _RunnerOperations(
        RuntimeFileApplyPatchResult(
            changes=(),
            final_cursor="1-0",
        )
    )
    tool = _tool(runner)
    patch = "*** Begin Patch\n*** End Patch"

    assert isinstance(tool.handler, PlaintextCustomToolHandler)
    await tool.handler.execute_plaintext_custom(
        "*** Base Path: /workspace/project\n" + patch
    )

    assert len(runner.calls) == 1
    assert runner.calls[0]["base_path"] == "/workspace/project"
    assert runner.calls[0]["patch"] == patch.encode()


async def test_plaintext_custom_rejects_invalid_envelope_before_runner() -> None:
    runner = _RunnerOperations(
        RuntimeFileApplyPatchResult(
            changes=(),
            final_cursor="1-0",
        )
    )
    tool = _tool(runner)

    assert isinstance(tool.handler, PlaintextCustomToolHandler)
    with pytest.raises(FunctionToolError) as error:
        await tool.handler.execute_plaintext_custom(
            "*** Base Path: relative\n*** Begin Patch\n*** End Patch"
        )

    assert error.value.metadata["kind"] == "apply_patch_input_failure"
    assert error.value.metadata["reason"] == "base_path_not_absolute"
    assert runner.calls == []


async def test_apply_patch_preserves_typed_partial_failure_metadata() -> None:
    failure = RuntimeFileApplyPatchFailure(
        phase="commit",
        reason="source_changed",
        applied=(
            RuntimeFilePatchChange(
                path="first.txt",
                action="update",
                added_lines=2,
                removed_lines=1,
                content_sha256="b" * 64,
            ),
        ),
        failed=RuntimeFilePatchOperation(path="second.txt", action="delete"),
        not_attempted=(RuntimeFilePatchOperation(path="third.txt", action="add"),),
        exact=True,
    )
    runner = _RunnerOperations(
        RuntimeFileApplyPatchFailedError(
            "source changed before deletion",
            failure=failure,
        )
    )

    with pytest.raises(FunctionToolError) as error:
        await _tool(runner).handler(
            json.dumps({"base_path": "/workspace/project", "patch": _PATCH})
        )

    assert "Patch failed after applying 1 change(s)." in str(error.value)
    assert "Re-read the affected files before continuing." in str(error.value)
    assert error.value.metadata == {
        "kind": "apply_patch_failure",
        "phase": "commit",
        "reason": "source_changed",
        "applied": [
            {
                "path": "first.txt",
                "action": "update",
                "added_lines": 2,
                "removed_lines": 1,
                "content_sha256": "b" * 64,
            }
        ],
        "failed": {"path": "second.txt", "action": "delete"},
        "not_attempted": [{"path": "third.txt", "action": "add"}],
        "exact": True,
    }


async def test_apply_patch_cancellation_waits_for_typed_runner_result() -> None:
    failure = RuntimeFileApplyPatchFailure(
        phase="preflight",
        reason="cancelled",
        applied=(),
        failed=None,
        not_attempted=(),
        exact=True,
    )
    runner = _RunnerOperations(
        RuntimeFileApplyPatchFailedError(
            "Runtime operation cancelled",
            failure=failure,
        ),
        wait_for_cancellation=True,
    )
    task = asyncio.ensure_future(
        _tool(runner).handler(
            json.dumps({"base_path": "/workspace/project", "patch": _PATCH})
        )
    )
    await runner.started.wait()

    task.cancel()

    with pytest.raises(FunctionToolError) as error:
        await task
    assert error.value.metadata["reason"] == "cancelled"
    assert error.value.metadata["applied"] == []
    assert str(error.value).endswith("No files were changed.")
