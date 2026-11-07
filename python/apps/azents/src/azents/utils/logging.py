"""Logging helpers for content-safe exception observation."""

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

type SanitizedExceptionInfo = tuple[
    type[BaseException],
    BaseException,
    TracebackType | None,
]


@dataclass(frozen=True)
class ExceptionOriginFrame:
    """Source location only, without source lines or local values."""

    file: str
    function: str
    line: int


@dataclass(frozen=True)
class ContentSafeExceptionDiagnostic:
    """Sanitized exception plus separately structured source locations."""

    exc_info: SanitizedExceptionInfo
    error_type: str
    frames: tuple[ExceptionOriginFrame, ...]

    def log_fields(self) -> dict[str, object]:
        """Return structured origin evidence without rendering the traceback."""
        return {
            "error_type": self.error_type,
            "error_frames": [
                {"file": frame.file, "function": frame.function, "line": frame.line}
                for frame in self.frames
            ],
        }


def content_safe_exception_diagnostic(
    error: BaseException, *, message: str
) -> ContentSafeExceptionDiagnostic:
    """Exclude values, causes, source lines and locals from a handled failure."""
    frames: list[ExceptionOriginFrame] = []
    traceback = error.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        frames.append(
            ExceptionOriginFrame(
                file=Path(code.co_filename).name,
                function=code.co_name,
                line=traceback.tb_lineno,
            )
        )
        traceback = traceback.tb_next
    sanitized = RuntimeError(message)
    return ContentSafeExceptionDiagnostic(
        exc_info=(RuntimeError, sanitized, None),
        error_type=type(error).__name__,
        frames=tuple(frames),
    )


def sanitized_exception_info(
    error: BaseException,
    *,
    message: str,
) -> SanitizedExceptionInfo:
    """Preserve origin frames while replacing untrusted exception text."""
    sanitized = RuntimeError(message)
    return type(sanitized), sanitized, error.__traceback__
