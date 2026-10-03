"""Pure ordered facts for completed Credential database reads."""

import dataclasses
from enum import StrEnum


class CredentialReadKind(StrEnum):
    """Database query behavior, independent of provider projection attributes."""

    PASSWORD = "password"
    EMAIL = "email"


@dataclasses.dataclass(frozen=True)
class CredentialReadFact:
    """Detached configuration fact for one requested query kind."""

    kind: CredentialReadKind
    configured: bool


@dataclasses.dataclass(frozen=True)
class CredentialReadSnapshot:
    """Completed read facts retaining request order and multiplicity."""

    facts: tuple[CredentialReadFact, ...]
