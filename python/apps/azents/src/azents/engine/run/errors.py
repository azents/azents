"""Runtime exception types."""

from typing import Literal

ModelStreamTimeoutKind = Literal["connect", "parsed_event_idle", "absolute_attempt"]
ModelStreamTimeoutFailureCode = Literal[
    "model_connect_timeout",
    "model_stream_idle_timeout",
    "model_attempt_timeout",
]
ModelStreamCallKind = Literal["sampling", "compaction", "session_title"]


class UserVisibleRuntimeError(RuntimeError):
    """Runtime error that can be exposed directly to user."""

    @property
    def user_message(self) -> str:
        """Error message to display in UI."""
        return str(self)


class ModelCallError(UserVisibleRuntimeError):
    """LLM provider/model call failure."""


class TransientModelCallError(ModelCallError):
    """Retryable model call failure with a stable operational code."""

    failure_code: str


class ModelStreamTimeoutError(TransientModelCallError):
    """Azents-owned timeout for one streaming model provider attempt."""

    _FAILURE_CODES: dict[ModelStreamTimeoutKind, ModelStreamTimeoutFailureCode] = {
        "connect": "model_connect_timeout",
        "parsed_event_idle": "model_stream_idle_timeout",
        "absolute_attempt": "model_attempt_timeout",
    }
    _MESSAGES: dict[ModelStreamTimeoutKind, str] = {
        "connect": "The model connection timed out.",
        "parsed_event_idle": "The model response stream became inactive.",
        "absolute_attempt": "The model response exceeded the attempt time limit.",
    }

    def __init__(
        self,
        *,
        timeout_kind: ModelStreamTimeoutKind,
        deadline_seconds: float,
        elapsed_seconds: float,
        call_kind: ModelStreamCallKind,
        provider: str,
        model: str,
    ) -> None:
        """Store safe timeout classification and operational context."""
        super().__init__(self._MESSAGES[timeout_kind])
        self.timeout_kind = timeout_kind
        self.failure_code = self._FAILURE_CODES[timeout_kind]
        self.deadline_seconds = deadline_seconds
        self.elapsed_seconds = elapsed_seconds
        self.call_kind = call_kind
        self.provider = provider
        self.model = model


class CompactionFailedError(RuntimeError):
    """Context compaction failure."""


class CompactionContextWindowExceededError(CompactionFailedError):
    """Compaction summary model input exceeded context window."""


class CompactionModelStreamTimeoutError(CompactionFailedError):
    """Compaction failed because its streaming model attempt timed out."""

    def __init__(self, timeout: ModelStreamTimeoutError) -> None:
        """Preserve typed timeout metadata through compaction conversion."""
        super().__init__(timeout.user_message)
        self.timeout_kind = timeout.timeout_kind
        self.failure_code = timeout.failure_code
        self.deadline_seconds = timeout.deadline_seconds
        self.elapsed_seconds = timeout.elapsed_seconds
        self.provider = timeout.provider
        self.model = timeout.model
