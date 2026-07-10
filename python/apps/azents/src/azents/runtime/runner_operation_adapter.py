"""Convert Runtime control client to engine runtime I/O protocol."""

from collections.abc import Awaitable
from datetime import datetime
from typing import TypeVar

from azents.engine.tools import runtime_io as engine_runtime_io
from azents.engine.tools.runtime_io import (
    RuntimeBashResult,
    RuntimeFileListEntry,
    RuntimeFileListResult,
    RuntimeFileReadResult,
    RuntimeFileStatResult,
    RuntimeFileWriteResult,
    RuntimeGrepFileMatch,
    RuntimeGrepLineMatch,
    RuntimeGrepResult,
    RuntimeOperationCancelCheck,
    RuntimeProcessOutputCallback,
    RuntimeProcessOutputDelta,
    RuntimeProcessResult,
)
from azents.runtime.control_protocol import (
    runner_operations as control_runner_operations,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient as ControlRuntimeRunnerOperationClient,
)

_T = TypeVar("_T")


class RuntimeRunnerOperationAdapter:
    """Adapter wrapping Runtime control client as engine runtime I/O protocol."""

    def __init__(self, client: ControlRuntimeRunnerOperationClient) -> None:
        """Initialize Adapter."""
        self._client = client

    async def run_bash(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        command: str,
        timeout_seconds: int,
        env: dict[str, str] | None,
        deadline_at: datetime,
        cancel_check: RuntimeOperationCancelCheck | None = None,
    ) -> RuntimeBashResult:
        """Run bash operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.run_bash(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                command=command,
                timeout_seconds=timeout_seconds,
                env=env,
                deadline_at=deadline_at,
                cancel_check=cancel_check,
            )
        )
        return RuntimeBashResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            final_cursor=result.final_cursor,
        )

    async def start_process(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        command: str,
        workdir: str | None,
        yield_time_ms: int,
        max_output_bytes: int,
        env: dict[str, str] | None,
        owner_session_id: str,
        deadline_at: datetime,
        process_output_callback: RuntimeProcessOutputCallback | None = None,
    ) -> RuntimeProcessResult:
        """Start process operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.start_process(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                command=command,
                workdir=workdir,
                yield_time_ms=yield_time_ms,
                max_output_bytes=max_output_bytes,
                env=env,
                owner_session_id=owner_session_id,
                deadline_at=deadline_at,
                process_output_callback=_control_process_output_callback(
                    process_output_callback
                ),
            )
        )
        return _process_result(result)

    async def write_process_stdin(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        process_id: str,
        stdin: str,
        yield_time_ms: int,
        max_output_bytes: int,
        owner_session_id: str,
        deadline_at: datetime,
        process_output_callback: RuntimeProcessOutputCallback | None = None,
    ) -> RuntimeProcessResult:
        """Write process stdin or poll, and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.write_process_stdin(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                process_id=process_id,
                stdin=stdin,
                yield_time_ms=yield_time_ms,
                max_output_bytes=max_output_bytes,
                owner_session_id=owner_session_id,
                deadline_at=deadline_at,
                process_output_callback=_control_process_output_callback(
                    process_output_callback
                ),
            )
        )
        return _process_result(result)

    async def terminate_session_processes(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        deadline_at: datetime,
    ) -> None:
        """Terminate all Runner-owned processes for one AgentSession."""
        await _translate_runtime_errors(
            self._client.terminate_session_processes(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                deadline_at=deadline_at,
            )
        )

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        offset: int,
        max_bytes: int | None,
        deadline_at: datetime,
    ) -> RuntimeFileReadResult:
        """Run file read operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.read_file(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=path,
                offset=offset,
                max_bytes=max_bytes,
                deadline_at=deadline_at,
            )
        )
        return RuntimeFileReadResult(data=result.data, final_cursor=result.final_cursor)

    async def write_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        data: bytes,
        deadline_at: datetime,
    ) -> RuntimeFileWriteResult:
        """Run file write operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.write_file(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=path,
                data=data,
                deadline_at=deadline_at,
            )
        )
        return RuntimeFileWriteResult(
            bytes_written=result.bytes_written,
            final_cursor=result.final_cursor,
        )

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        """Run file list operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.list_files(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=path,
                recursive=recursive,
                exclude_patterns=exclude_patterns,
                deadline_at=deadline_at,
            )
        )
        return RuntimeFileListResult(
            entries=tuple(
                RuntimeFileListEntry(
                    path=entry.path,
                    type=entry.type,
                    size_bytes=entry.size_bytes,
                )
                for entry in result.entries
            ),
            final_cursor=result.final_cursor,
        )

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        """Run file stat operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.stat_file(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=path,
                deadline_at=deadline_at,
            )
        )
        return RuntimeFileStatResult(
            path=result.path,
            kind=result.kind,
            size_bytes=result.size_bytes,
            symlink=result.symlink,
            real_path=result.real_path,
            resolved_kind=result.resolved_kind,
            final_cursor=result.final_cursor,
        )

    async def grep_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeGrepResult:
        """Run file grep operation and convert to engine result."""
        result = await _translate_runtime_errors(
            self._client.grep_files(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=path,
                pattern=pattern,
                recursive=recursive,
                exclude_patterns=exclude_patterns,
                max_matching_files=max_matching_files,
                max_lines_per_file=max_lines_per_file,
                max_searched_files=max_searched_files,
                max_scanned_bytes=max_scanned_bytes,
                deadline_at=deadline_at,
            )
        )
        return RuntimeGrepResult(
            files=tuple(
                RuntimeGrepFileMatch(
                    path=file_match.path,
                    lines=tuple(
                        RuntimeGrepLineMatch(
                            line_number=line_match.line_number,
                            text=line_match.text,
                        )
                        for line_match in file_match.lines
                    ),
                    truncated=file_match.truncated,
                )
                for file_match in result.files
            ),
            searched_file_count=result.searched_file_count,
            matched_file_count=result.matched_file_count,
            truncated=result.truncated,
            stopped_reason=result.stopped_reason,
            final_cursor=result.final_cursor,
        )


async def _translate_runtime_errors(awaitable: Awaitable[_T]) -> _T:
    """Convert Runtime control error to engine protocol error."""
    try:
        return await awaitable
    except control_runner_operations.RuntimeRunnerOperationUnavailable as exc:
        raise engine_runtime_io.RuntimeRunnerOperationUnavailable(str(exc)) from exc
    except control_runner_operations.RuntimeRunnerOperationGenerationError as exc:
        raise engine_runtime_io.RuntimeRunnerOperationGenerationError(str(exc)) from exc
    except control_runner_operations.RuntimeRunnerOperationFailedError as exc:
        raise engine_runtime_io.RuntimeRunnerOperationFailedError(str(exc)) from exc


def _control_process_output_callback(
    callback: RuntimeProcessOutputCallback | None,
) -> control_runner_operations.RuntimeProcessOutputCallback | None:
    """Convert control process output callback to engine callback."""
    if callback is None:
        return None

    async def converted(
        delta: control_runner_operations.RuntimeProcessOutputDelta,
    ) -> None:
        await callback(
            RuntimeProcessOutputDelta(
                process_id=delta.process_id,
                stream=delta.stream,
                chunk_id=delta.chunk_id,
                text=delta.text,
                truncated=delta.truncated,
                omitted_bytes=delta.omitted_bytes,
            )
        )

    return converted


def _process_result(
    result: control_runner_operations.RuntimeProcessResult,
) -> RuntimeProcessResult:
    """Convert control process result to engine process result."""
    return RuntimeProcessResult(
        process_id=result.process_id,
        status=result.status,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
        stdout_omitted_bytes=result.stdout_omitted_bytes,
        stderr_omitted_bytes=result.stderr_omitted_bytes,
        missing_reason=result.missing_reason,
        final_cursor=result.final_cursor,
    )


def adapt_runtime_runner_operations(
    client: ControlRuntimeRunnerOperationClient,
) -> engine_runtime_io.RuntimeRunnerOperationClient:
    """Convert Runtime control client to engine protocol client."""
    return RuntimeRunnerOperationAdapter(client)
