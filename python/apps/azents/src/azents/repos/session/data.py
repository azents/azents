"""Session repository data models."""

import dataclasses
import datetime
import enum
from typing import Self

from azcommon.datetime import tznow
from pydantic import BaseModel, Field

from azents.rdb.models.session import RDBSession


class TokenMatch(enum.Enum):
    """Token match result."""

    CURRENT = "current"  # Matches current refresh_token
    PREVIOUS = "previous"  # Matches prev_refresh_token


class Session(BaseModel):
    """Session domain model."""

    id: str = Field(description="Session ID")
    user_id: str = Field(description="User ID")
    refresh_token: str = Field(description="Refresh token")
    prev_refresh_token: str | None = Field(
        None, description="Previous refresh token (for grace period)"
    )
    refresh_token_created_at: datetime.datetime = Field(
        description="Current refresh token creation time"
    )
    revoked_at: datetime.datetime | None = Field(None, description="Revocation time")
    user_agent: str | None = Field(None, description="User agent")
    ip_address: str | None = Field(None, description="IP address")
    last_used_at: datetime.datetime = Field(description="Last used time")
    expires_at: datetime.datetime = Field(description="Expiration time")
    max_expires_at: datetime.datetime | None = Field(
        None, description="Maximum expiration time"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def from_rdb(cls, rdb_session: "RDBSession") -> Self:
        """Convert RDBSession to domain Session."""
        return cls(
            id=rdb_session.id,
            user_id=rdb_session.user_id,
            refresh_token=rdb_session.refresh_token,
            prev_refresh_token=rdb_session.prev_refresh_token,
            refresh_token_created_at=rdb_session.refresh_token_created_at,
            revoked_at=rdb_session.revoked_at,
            user_agent=rdb_session.user_agent,
            ip_address=rdb_session.ip_address,
            last_used_at=rdb_session.last_used_at,
            expires_at=rdb_session.expires_at,
            max_expires_at=rdb_session.max_expires_at,
            created_at=rdb_session.created_at,
            updated_at=rdb_session.updated_at,
        )

    @property
    def is_active(self) -> bool:
        """Check whether session is active (not revoked and not expired)."""
        return self.revoked_at is None and self.expires_at > tznow()

    @property
    def is_revoked(self) -> bool:
        """Check whether session is revoked."""
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        """Check whether session is expired."""
        return self.revoked_at is None and self.expires_at <= tznow()


class SessionCreate(BaseModel):
    """Session create schema."""

    user_id: str = Field(description="User ID")
    refresh_token: str = Field(description="Refresh token")
    expires_at: datetime.datetime = Field(description="Expiration time")
    max_expires_at: datetime.datetime | None = Field(
        default=None, description="Maximum expiration time"
    )
    user_agent: str | None = Field(default=None, description="User agent")
    ip_address: str | None = Field(default=None, description="IP address")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Session not found."""

    id: str
