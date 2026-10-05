"""kubernetes.client.rest — ApiException type definitions."""

class ApiException(Exception):
    status: int
    reason: str
    body: str | None
    headers: dict[str, str] | None
    def __init__(
        self,
        status: int = 0,
        reason: str | None = None,
        http_resp: object = None,
    ) -> None: ...
