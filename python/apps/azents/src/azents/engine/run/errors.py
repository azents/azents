"""Runtime exception types."""

from typing import Literal

ModelStreamTimeoutStage = Literal["first_event", "idle"]


class UserVisibleRuntimeError(RuntimeError):
    """Runtime error that can be exposed directly to user."""

    @property
    def user_message(self) -> str:
        """Error message to display in UI."""
        return str(self)


class ModelCallError(UserVisibleRuntimeError):
    """LLM provider/model call failure."""


class ModelProviderTimeoutError(ModelCallError):
    """LLM provider transport timed out independently of stream progress."""


class ModelStreamTimeoutError(ModelCallError):
    """LLM provider stream did not make progress before its deadline."""

    def __init__(
        self,
        *,
        stage: ModelStreamTimeoutStage,
        timeout_seconds: float,
        cancellation_cleanup_timed_out: bool,
        cancellation_cleanup_error_type: str | None,
    ) -> None:
        super().__init__(
            f"Model stream {stage} deadline exceeded after {timeout_seconds} seconds"
        )
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        self.cancellation_cleanup_timed_out = cancellation_cleanup_timed_out
        self.cancellation_cleanup_error_type = cancellation_cleanup_error_type

    @property
    def user_message(self) -> str:
        """Return a stable user-safe timeout message independent of retry state."""
        return "The model did not make progress before the timeout."


class CompactionFailedError(RuntimeError):
    """Context compaction failure."""


class CompactionContextWindowExceededError(CompactionFailedError):
    """Compaction summary model input exceeded context window."""
