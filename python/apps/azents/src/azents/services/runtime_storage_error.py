"""Common Runtime file storage errors."""


class RuntimeStorageError(RuntimeError):
    """Known error returned by Runtime file storage."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


RUNTIME_CONTROL_CONNECTION_UNAVAILABLE = "Runtime control connection is unavailable"


def is_stale_runtime_storage_error(exc: RuntimeStorageError) -> bool:
    """Whether stale control/storage error can recover by Runtime reconnect."""
    del exc
    return False
