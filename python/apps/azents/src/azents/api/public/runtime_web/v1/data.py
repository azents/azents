"""Public Runtime Web service control schemas."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from azents.services.runtime_web.data import (
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


RuntimeWebConfigurationState = Literal["configured", "unconfigured"]
RuntimeWebDurationSeconds = Literal[3600, 21600, 86400]


class RuntimeWebServiceResponse(_ClosedModel):
    """Current user-relevant Runtime Web service projection."""

    id: str = Field(min_length=32, max_length=32)
    port: int = Field(ge=1, le=65_535)
    label: str | None
    url: str | None
    configuration_state: RuntimeWebConfigurationState
    on: bool
    selected_duration_seconds: RuntimeWebDurationSeconds
    expires_at: datetime | None
    revision: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    observed_at: datetime

    @classmethod
    def convert_from(cls, projection: RuntimeWebServiceProjection) -> Self:
        """Convert the internal service projection."""
        return cls.model_validate(projection, from_attributes=True)


class RuntimeWebServiceListResponse(_ClosedModel):
    """Bounded service projection page."""

    items: list[RuntimeWebServiceResponse]
    total_count: int = Field(ge=0)

    @classmethod
    def convert_from(cls, page: RuntimeWebServicePage) -> Self:
        """Convert the internal service page."""
        return cls(
            items=[RuntimeWebServiceResponse.convert_from(item) for item in page.items],
            total_count=page.total_count,
        )


class RuntimeWebCreateRequest(_ClosedModel):
    """Create one Agent-port service."""

    port: int = Field(ge=1, le=65_535)
    label: str | None = Field(max_length=120)
    selected_duration_seconds: RuntimeWebDurationSeconds
    turn_on: bool
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebUpdateRequest(_ClosedModel):
    """Update service metadata using omission for unchanged fields."""

    expected_revision: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=120)
    selected_duration_seconds: RuntimeWebDurationSeconds | None = None
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebExpectedRevisionRequest(_ClosedModel):
    """Revision-fenced service control mutation."""

    expected_revision: int = Field(ge=0)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebTurnOnRequest(RuntimeWebExpectedRevisionRequest):
    """Turn an Off service On, optionally selecting duration atomically."""

    selected_duration_seconds: RuntimeWebDurationSeconds | None = None


class RuntimeWebDeleteResponse(_ClosedModel):
    """Idempotent authorized service deletion outcome."""

    deleted: bool


class RuntimeWebActionErrorDetail(_ClosedModel):
    """Bounded Public API control error detail."""

    code: Literal[
        "not_found",
        "access_denied",
        "conflict",
        "quota_exceeded",
        "configuration_unavailable",
        "runtime_capability_unavailable",
    ]
    scope: str | None


class RuntimeWebActionErrorResponse(_ClosedModel):
    """FastAPI envelope for a bounded Runtime Web control error."""

    detail: RuntimeWebActionErrorDetail


class RuntimeWebIdentitySecretResponse(_ClosedModel):
    """Opaque identity secret for a trusted cookie-setting response."""

    secret: str = Field(min_length=32, max_length=128)
    expires_at: datetime


class RuntimeWebIdentityRevokeRequest(_ClosedModel):
    """Exact identity secret revoked during trusted logout."""

    secret: str = Field(min_length=32, max_length=128)


class RuntimeWebIdentityRevokeResponse(_ClosedModel):
    """Identity revocation outcome."""

    revoked: bool


class RuntimeWebSeparateInitiateRequest(_ClosedModel):
    """Start one browser-bound separate-domain exchange."""

    service_id: str = Field(min_length=32, max_length=32)


class RuntimeWebSeparateInitiateResponse(_ClosedModel):
    """Main-origin binding state returned without URL credentials."""

    initiation_id: str = Field(min_length=32, max_length=32)
    main_binding_secret: str = Field(min_length=32, max_length=128)
    expires_at: datetime


class RuntimeWebSeparateBoundRequest(_ClosedModel):
    """Prove the exact Main binding after the broker callback."""

    initiation_id: str = Field(min_length=32, max_length=32)
    main_binding_secret: str = Field(min_length=32, max_length=128)


class RuntimeWebSeparateTicketResponse(_ClosedModel):
    """One-use POST-body ticket for the exact service."""

    ticket_secret: str = Field(min_length=32, max_length=128)
    service_id: str = Field(min_length=32, max_length=32)
    expires_at: datetime
