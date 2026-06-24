"""aiodocker.exceptions stub."""

class DockerError(Exception):
    status: int
    message: str

    def __init__(
        self,
        status: int,
        message: str = ...,
        data: dict[str, object] | None = ...,
    ) -> None: ...
