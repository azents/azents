"""Runtime Provider enrollment v1 Admin API schemas."""

import datetime

from pydantic import BaseModel, Field


class RuntimeProviderEnrollmentGrantIssueRequest(BaseModel):
    """System Admin enrollment grant issuance input."""

    expires_at: datetime.datetime = Field()


class RuntimeProviderEnrollmentGrantIssueResponse(BaseModel):
    """One-time enrollment grant returned only to a System Admin."""

    grant_id: str
    provider_id: str
    secret: str
    expires_at: datetime.datetime


class RuntimeProviderCredentialRevokeResponse(BaseModel):
    """Result of revoking one Provider credential."""

    revoked: bool
