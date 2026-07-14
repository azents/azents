"""Runtime exception types."""


class UserVisibleRuntimeError(RuntimeError):
    """Runtime error that can be exposed directly to user."""

    @property
    def user_message(self) -> str:
        """Error message to display in UI."""
        return str(self)


class ModelCallError(UserVisibleRuntimeError):
    """LLM provider/model call failure."""


class ModelStreamTimeoutError(ModelCallError):
    """LLM provider stream did not make progress before its deadline."""

    def __init__(self, *, stage: str, timeout_seconds: float) -> None:
        super().__init__("The model did not respond in time. Retrying.")
        self.stage = stage
        self.timeout_seconds = timeout_seconds


class CompactionFailedError(RuntimeError):
    """Context compaction failure."""


class CompactionContextWindowExceededError(CompactionFailedError):
    """Compaction summary model input exceeded context window."""
