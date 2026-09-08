"""Completed Auth operation data models."""

import dataclasses
import datetime


@dataclasses.dataclass(frozen=True)
class VerifiedEmailUserResolve:
    """Verified email identity resolution input."""

    email: str
    registration_open: bool


@dataclasses.dataclass(frozen=True)
class ResolvedAuthUser:
    """User identity resolved for authentication."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class PasswordCredentialLookup:
    """Password credential lookup input."""

    email: str


@dataclasses.dataclass(frozen=True)
class PasswordCredentialSnapshot:
    """Detached active-user password credential snapshot."""

    user_id: str
    password_hash: str


@dataclasses.dataclass(frozen=True)
class RefreshAuthenticationSession:
    """Refresh Session operation input."""

    refresh_token: str
    candidate_refresh_token: str
    rotation_period: datetime.timedelta
    grace_period: datetime.timedelta
    expire_timedelta: datetime.timedelta


@dataclasses.dataclass(frozen=True)
class RegistrationRequired:
    """Verified email is not registered and registration is unavailable."""

    pass


@dataclasses.dataclass(frozen=True)
class AuthenticationUnavailable:
    """User or credential cannot authorize authentication."""

    pass


@dataclasses.dataclass(frozen=True)
class RefreshTokenRejected:
    """Refresh token cannot authorize a Session refresh."""

    pass
