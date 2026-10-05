"""Public Secret data surface used by Provider credential bootstrap."""

class V1Secret:
    data: dict[str, str] | None

    def __init__(self, *, data: dict[str, str] | None = ...) -> None: ...
