"""Completed Email Verification operation data models."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class EmailVerificationVerify:
    """Verification values validated and conditionally marked together."""

    email: str
    csrf_token: str
    code: str


@dataclasses.dataclass(frozen=True)
class InvalidCode:
    """Verification code did not match the active verification record."""

    pass
