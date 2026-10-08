"""Pure UserEmail input and conflict contracts shared with API callers."""

import dataclasses

from pydantic import BaseModel, Field


class UserEmailCreate(BaseModel):
    """UserEmail create schema."""

    user_id: str = Field(description="Owning User ID")
    email: str = Field(description="Email address")


@dataclasses.dataclass(frozen=True)
class DuplicateEmail:
    """Duplicate email."""

    email: str
