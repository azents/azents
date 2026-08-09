"""Runner-side lifecycle for one contained operation helper process."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from azents_runtime_runner.contained_async_protocol import read_async_frame
from azents_runtime_runner.contained_protocol import (
    JsonValue,
    ProtocolFrame,
    encode_binary_frame,
    encode_control_frame,
)
from azents_runtime_runner.containment import (
    ExecutionBackend,
    ExecutionProcess,
    ExecutionSpec,
    ProcessTerminationResult,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_COMMON_HELPER_MODULE = "azents_runtime_runner.contained_helper"
_GIT_HELPER_MODULE = "azents_runtime_runner.contained_git_helper"
_APPLY_PATCH_HELPER_MODULE = "azents_runtime_runner.contained_apply_patch_helper"
_TRANSFER_HELPER_MODULE = "azents_runtime_runner.contained_transfer_helper"
_GIT_OPERATIONS = frozenset(
    {
        "list_git_refs",
        "create_git_worktree",
        "inspect_git_worktree",
        "discover_managed_git_worktrees",
        "remove_discovered_git_worktree",
        "remove_git_worktree",
        "delete_git_branch",
    }
)
_TERMINATE_TIMEOUT_SECONDS = 2.0
_KILL_TIMEOUT_SECONDS = 2.0
_MAX_DIAGNOSTIC_BYTES = 4096


@dataclass(frozen=True)
class ContainedHelperDiagnostic:
    """Bounded private helper diagnostic captured for failure classification."""

    text: str
    truncated: bool


@dataclass(frozen=True)
class ContainedOperationEvent:
    """One helper-produced operation event."""

    event_type: str
    payload: Mapping[str, JsonValue]
    binary: bytes | None
    final: bool


type ContainedOperationEventHandler = Callable[
    [ContainedOperationEvent],
    Awaitable[None],
]
type ContainedCompletionFactory = Callable[[], Mapping[str, JsonValue]]


class ContainedOperationClient:
    """Execute one-shot native operations through the selected backend."""

    def __init__(
        self,
        *,
        backend: ExecutionBackend,
        workspace_path: Path,
    ) -> None:
        self._backend = backend
        self._workspace_path = workspace_path

    async def run(
        self,
        *,
        operation: str,
        payload: Mapping[str, JsonValue],
        body_chunks: Sequence[bytes],
        deadline_at: datetime | None,
        event_handler: ContainedOperationEventHandler,
    ) -> None:
        """Run one operation and relay its ordered events."""
        session = await ContainedHelperSession.start(
            backend=self._backend,
            workspace_path=self._workspace_path,
            operation=operation,
            metadata={
                "payload": dict(payload),
                "body_count": len(body_chunks),
                "deadline_at": (
                    None
                    if deadline_at is None
                    else deadline_at.astimezone(UTC).isoformat()
                ),
            },
        )
        try:
            for chunk in body_chunks:
                await session.send_binary(chunk)
            await self._relay_until_terminal(session, event_handler)
        except asyncio.CancelledError:
            await session.send_control({"kind": "cancel"})
            if operation != "file.apply_patch":
                await session.terminate()
                raise
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.uncancel()
            await self._relay_until_terminal(session, event_handler)
        except BaseException:
            await session.terminate()
            raise

    async def run_streaming_input(
        self,
        *,
        operation: str,
        payload: Mapping[str, JsonValue],
        input_chunks: AsyncIterator[bytes],
        completion_factory: ContainedCompletionFactory,
        deadline_at: datetime,
        event_handler: ContainedOperationEventHandler,
    ) -> None:
        """Stream request bytes before relaying the helper terminal result."""
        session = await ContainedHelperSession.start(
            backend=self._backend,
            workspace_path=self._workspace_path,
            operation=operation,
            metadata={
                "payload": dict(payload),
                "body_count": 0,
                "deadline_at": deadline_at.astimezone(UTC).isoformat(),
            },
        )
        completion_sent = False
        try:
            ready = await session.receive()
            if ready.control == {
                "kind": "event",
                "event_type": "transfer_ready",
                "payload": {},
                "binary_follows": False,
                "final": False,
            }:
                pass
            elif ready.control is not None and ready.control.get("final") is True:
                control = ready.control
                event_type = control.get("event_type")
                event_payload = control.get("payload")
                if not isinstance(event_type, str) or not isinstance(
                    event_payload, dict
                ):
                    raise RuntimeError(
                        "contained streaming helper readiness is invalid"
                    )
                await event_handler(
                    ContainedOperationEvent(
                        event_type=event_type,
                        payload=event_payload,
                        binary=None,
                        final=True,
                    )
                )
                await session.finish()
                return
            else:
                raise RuntimeError("contained streaming helper readiness is invalid")
            async for chunk in input_chunks:
                await session.send_binary(chunk)
            await session.send_control(
                {"kind": "transfer_complete", **dict(completion_factory())}
            )
            completion_sent = True
            await self._relay_until_terminal(session, event_handler)
        except asyncio.CancelledError:
            if not completion_sent:
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
                await session.send_control({"kind": "cancel"})

                async def ignore_terminal(event: ContainedOperationEvent) -> None:
                    del event

                await self._relay_until_terminal(session, ignore_terminal)
                raise
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.uncancel()
            await self._relay_until_terminal(session, event_handler)
        except BaseException:
            await session.terminate()
            raise

    async def _relay_until_terminal(
        self,
        session: "ContainedHelperSession",
        event_handler: ContainedOperationEventHandler,
    ) -> None:
        """Relay validated helper events through the single terminal frame."""
        while True:
            frame = await session.receive()
            control = frame.control
            if control is None:
                raise RuntimeError("contained helper sent an unexpected binary frame")
            event_type = control.get("event_type")
            event_payload = control.get("payload")
            final = control.get("final")
            binary_follows = control.get("binary_follows", False)
            if (
                control.get("kind") != "event"
                or not isinstance(event_type, str)
                or not isinstance(event_payload, dict)
                or not isinstance(final, bool)
                or not isinstance(binary_follows, bool)
            ):
                raise RuntimeError("contained helper event shape is invalid")
            binary = None
            if binary_follows:
                binary_frame = await session.receive()
                if binary_frame.binary is None:
                    raise RuntimeError(
                        "contained helper binary event payload is missing"
                    )
                binary = binary_frame.binary
            await event_handler(
                ContainedOperationEvent(
                    event_type=event_type,
                    payload=event_payload,
                    binary=binary,
                    final=final,
                )
            )
            if final:
                await session.finish()
                return


class ContainedHelperSession:
    """One framed helper session executed through the selected backend."""

    def __init__(
        self,
        *,
        process: ExecutionProcess,
        diagnostic_task: asyncio.Task[ContainedHelperDiagnostic],
    ) -> None:
        self._process = process
        self._diagnostic_task = diagnostic_task
        self._write_lock = asyncio.Lock()
        self._terminal = False

    @classmethod
    async def start(
        cls,
        *,
        backend: ExecutionBackend,
        workspace_path: Path,
        operation: str,
        metadata: Mapping[str, JsonValue],
    ) -> "ContainedHelperSession":
        """Start one helper and send its exact opening request."""
        environment = dict(
            backend.agent_environment(
                workspace_path=str(workspace_path),
                operation_environment={"PYTHONPATH": str(_PACKAGE_ROOT)},
            )
        )
        process = await backend.start(
            ExecutionSpec(
                argv=(
                    backend.helper_python_path,
                    "-m",
                    _helper_module(operation),
                ),
                cwd=workspace_path,
                environment=environment,
                stdin=True,
                managed=False,
            )
        )
        session = cls(
            process=process,
            diagnostic_task=asyncio.create_task(
                _read_diagnostic(process),
            ),
        )
        await session.send_control(
            {
                "protocol_version": 1,
                "operation": operation,
                "workspace_path": str(workspace_path),
                "metadata": dict(metadata),
            }
        )
        return session

    async def send_control(self, payload: Mapping[str, JsonValue]) -> None:
        """Send one ordered control frame."""
        async with self._write_lock:
            await self._process.write_stdin(encode_control_frame(payload))

    async def send_binary(self, data: bytes) -> None:
        """Send one ordered raw binary frame."""
        async with self._write_lock:
            await self._process.write_stdin(encode_binary_frame(data))

    async def receive(self) -> ProtocolFrame:
        """Receive one ordered helper frame."""
        return await read_async_frame(self._process.stdout)

    async def finish(self) -> ContainedHelperDiagnostic:
        """Wait for one successful helper exit after a terminal frame."""
        if self._terminal:
            raise RuntimeError("contained helper session already finished")
        self._terminal = True
        returncode = await self._process.wait()
        diagnostic = await self._diagnostic_task
        if returncode != 0:
            raise RuntimeError("contained helper exited unsuccessfully")
        return diagnostic

    async def terminate(self) -> ProcessTerminationResult:
        """Terminate the complete helper descendant group."""
        if not self._diagnostic_task.done():
            self._diagnostic_task.cancel()
            await asyncio.gather(self._diagnostic_task, return_exceptions=True)
        return await self._process.terminate_descendants(
            terminate_timeout_seconds=_TERMINATE_TIMEOUT_SECONDS,
            kill_timeout_seconds=_KILL_TIMEOUT_SECONDS,
        )


def _helper_module(operation: str) -> str:
    if operation in _GIT_OPERATIONS:
        return _GIT_HELPER_MODULE
    if operation == "file.apply_patch":
        return _APPLY_PATCH_HELPER_MODULE
    if operation.startswith("transfer."):
        return _TRANSFER_HELPER_MODULE
    return _COMMON_HELPER_MODULE


async def _read_diagnostic(process: ExecutionProcess) -> ContainedHelperDiagnostic:
    data = await process.stderr.read(_MAX_DIAGNOSTIC_BYTES + 1)
    return ContainedHelperDiagnostic(
        text=data[:_MAX_DIAGNOSTIC_BYTES].decode(errors="replace"),
        truncated=len(data) > _MAX_DIAGNOSTIC_BYTES,
    )
