"""Runtime Provider enrollment v1 Public API schemas."""

import datetime

from pydantic import BaseModel, Field


class RuntimeProviderCredentialExchangeRequest(BaseModel):
    """One-time enrollment grant exchange input."""

    grant_id: str = Field(min_length=1)
    secret: str = Field(min_length=1)


class RuntimeProviderCredentialExchangeResponse(BaseModel):
    """One-time Provider credential result returned to a controller operator."""

    credential_id: str
    provider_id: str
    credential: str
    expires_at: datetime.datetime | None
