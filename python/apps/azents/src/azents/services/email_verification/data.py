"""EmailVerification service data models."""

from pydantic import BaseModel, Field

from azents.repos.email_verification.data import (
    EmailVerification,
)


class EmailVerificationOutput(EmailVerification):
    """EmailVerification output model."""

    pass


class EmailVerificationListOutput(BaseModel):
    """EmailVerification list output model."""

    items: list[EmailVerificationOutput] = Field(description="Verification record list")
    total: int = Field(description="Total record count")


__all__: list[str] = []
