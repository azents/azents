"""xAI OAuth v1 Public API data models."""

import datetime

from pydantic import BaseModel, Field

from azents.api.public.llm_provider_integration.v1.data import (
    LLMProviderIntegrationResponse,
)
from azents.core.xai_oauth import XaiOAuthSessionStatus
from azents.services.xai_oauth.data import (
    XaiOAuthDeviceStartOutput,
    XaiOAuthDeviceStatusOutput,
)


class XaiOAuthDeviceStartResponse(BaseModel):
    """Device OAuth start response."""

    session_id: str = Field(description="OAuth session ID")
    user_code: str = Field(description="Device user code")
    verification_uri: str = Field(description="Device verification URI")
    interval_seconds: int = Field(description="Provider polling interval")
    expires_at: datetime.datetime = Field(description="Session expiry")

    @classmethod
    def convert_from(
        cls, data: XaiOAuthDeviceStartOutput
    ) -> "XaiOAuthDeviceStartResponse":
        """Convert service output to API response."""
        return cls.model_validate(data, from_attributes=True)


class XaiOAuthDeviceStatusResponse(BaseModel):
    """Device OAuth status response."""

    session_id: str = Field(description="OAuth session ID")
    status: XaiOAuthSessionStatus = Field(description="Session status")
    interval_seconds: int = Field(description="Current provider polling interval")
    integration: LLMProviderIntegrationResponse | None = Field(
        default=None, description="Stored provider integration when connected"
    )

    @classmethod
    def convert_from(
        cls, data: XaiOAuthDeviceStatusOutput
    ) -> "XaiOAuthDeviceStatusResponse":
        """Convert service output to API response."""
        return cls(
            session_id=data.session_id,
            status=data.status,
            interval_seconds=data.interval_seconds,
            integration=(
                LLMProviderIntegrationResponse.convert_from(data.integration)
                if data.integration is not None
                else None
            ),
        )
