"""Logging helpers for content-safe exception observation."""

from types import TracebackType

type SanitizedExceptionInfo = tuple[
    type[BaseException],
    BaseException,
    TracebackType | None,
]


def sanitized_exception_info(
    error: BaseException,
    *,
    message: str,
) -> SanitizedExceptionInfo:
    """Preserve origin frames while replacing untrusted exception text."""
    sanitized = RuntimeError(message)
    return type(sanitized), sanitized, error.__traceback__
