"""Defining detached Runtime management contracts."""

import dataclasses


@dataclasses.dataclass
class RuntimeProviderContractUnavailable(Exception):
    """A Provider contract operation cannot be completed safely."""

    code: str
    message: str
    current_admin_version: int | None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
