"""Runtime exception types."""


class UserVisibleRuntimeError(RuntimeError):
    """Runtime error that can be exposed directly to user."""

    @property
    def user_message(self) -> str:
        """Error message to display in UI."""
        return str(self)


class ModelCallError(UserVisibleRuntimeError):
    """LLM provider/model call failure."""


class CompactionFailedError(RuntimeError):
    """Context compaction failure."""


class CompactionContextWindowExceededError(CompactionFailedError):
    """Compaction summary model input exceeded context window."""
