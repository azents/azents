"""Pure prepared Signup redemption values and canonical domain failures."""

import dataclasses
import datetime


@dataclasses.dataclass(frozen=True)
class SignupTokenRedeemCommand:
    """Application preparation ready for the original atomic redemption group."""

    token_hash: str
    now: datetime.datetime
    email: str
    password_hash: str
    refresh_token: str
    expires_at: datetime.datetime
    max_expires_at: datetime.datetime | None
    user_agent: str | None
    ip_address: str | None


@dataclasses.dataclass(frozen=True)
class SignupTokenRedeemFacts:
    """Committed identity facts for post-closure JWT creation."""

    user_id: str
    session_id: str


@dataclasses.dataclass(frozen=True)
class InvalidSignupToken:
    """Invalid signup token."""

    pass


@dataclasses.dataclass(frozen=True)
class SignupTokenEmailMismatch:
    """Signup token email mismatch."""

    pass


@dataclasses.dataclass(frozen=True)
class SignupTokenEmailAlreadyRegistered:
    """Email already signed up."""

    email: str
