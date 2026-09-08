"""Runtime connection registration service errors."""

import dataclasses


@dataclasses.dataclass
class RuntimeConnectionRegistrationUnavailable(Exception):
    """A cross-store Runtime connection registration cannot be accepted."""

    code: str

    def __post_init__(self) -> None:
        Exception.__init__(
            self,
            f"Runtime connection registration unavailable: {self.code}",
        )
