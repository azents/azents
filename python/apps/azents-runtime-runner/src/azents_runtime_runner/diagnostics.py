"""Bounded Runner error provenance that never serializes exception content."""

from __future__ import annotations

import dataclasses
import enum
import logging
from collections.abc import Mapping
from pathlib import PurePath
from types import TracebackType
from typing import NamedTuple


class RunnerDiagnosticReason(enum.StrEnum):
    """Implementation-owned labels safe for authentication and protocol logs."""

    AUTHORITY_REJECTED = "runner_authority_rejected"
    CREDENTIAL_REJECTED = "runner_credential_rejected"
    CONTROL_STREAM_FAILED = "runner_control_stream_failed"
    CONTROL_CLOSE_TIMED_OUT = "runner_control_close_timed_out"
    WEB_PROTOCOL_FAILED = "runner_web_protocol_failed"
    WEB_RESOURCE_EXHAUSTED = "runner_web_resource_exhausted"
    TRANSFER_RESPONSE_INVALID = "direct_claim_renewal_response_invalid"
    TRANSFER_RENEWAL_FAILED = "direct_claim_renewal_failed"
    OPERATION_FAILED = "runner_operation_failed"


class SafeExceptionInfo(NamedTuple):
    """Logging's exception tuple without the original value or source text."""

    exception_type: type[BaseException]
    exception: BaseException
    traceback: TracebackType | None


@dataclasses.dataclass(frozen=True)
class SafeErrorFrame:
    """One original raising-frame location without locals or source contents."""

    file: str
    function: str
    line: int


@dataclasses.dataclass(frozen=True)
class RunnerExceptionDiagnostic:
    """Safe exception label and separately structured original-frame evidence."""

    reason: RunnerDiagnosticReason
    error_type: str
    frames: tuple[SafeErrorFrame, ...]

    @property
    def exc_info(self) -> SafeExceptionInfo:
        """Render only a new bounded value, with no original exception chain."""
        safe = RuntimeError(self.reason.value)
        return SafeExceptionInfo(RuntimeError, safe, None)

    def log_fields(self) -> dict[str, object]:
        """Serialize bounded diagnostic fields at the logging boundary."""
        return {
            "error_type": self.error_type,
            "error_frames": [
                {
                    "file": frame.file,
                    "function": frame.function,
                    "line": frame.line,
                }
                for frame in self.frames
            ],
        }


def runner_exception_diagnostic(
    error: BaseException, reason: RunnerDiagnosticReason
) -> RunnerExceptionDiagnostic:
    """Retain origin locations without formatting values, locals, or code lines."""
    frames: list[SafeErrorFrame] = []
    traceback = error.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        frames.append(
            SafeErrorFrame(
                file=PurePath(code.co_filename).name,
                function=code.co_name,
                line=traceback.tb_lineno,
            )
        )
        traceback = traceback.tb_next
    return RunnerExceptionDiagnostic(
        reason=reason,
        error_type=type(error).__name__,
        frames=tuple(frames[-16:]),
    )


def bind_extra(
    logger: logging.Logger, fields: Mapping[str, object]
) -> logging.LoggerAdapter[logging.Logger]:
    """Bind shared Runner context using the standard-library merge contract."""
    return logging.LoggerAdapter(logger, dict(fields), merge_extra=True)
