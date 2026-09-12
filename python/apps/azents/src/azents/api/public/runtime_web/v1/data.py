"""Public Runtime Web service control schemas."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from azents.rdb.models.runtime_web import (
    RuntimeWebCycleEndReason,
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)
from azents.services.runtime_web.data import (
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


RuntimeWebConfigurationState = Literal["configured", "unconfigured"]


class RuntimeWebEndpointResponse(_ClosedModel):
    """Stable Session-and-port endpoint projection."""

    id: str
    port: int = Field(ge=1, le=65_535)
    label: str | None
    url: str | None
    configuration_state: RuntimeWebConfigurationState
    authority_revision: int = Field(ge=0)
    close_barrier: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeWebServiceProjection,
    ) -> Self:
        endpoint = projection.endpoint
        return cls(
            id=endpoint.id,
            port=endpoint.port,
            label=endpoint.label,
            url=projection.url,
            configuration_state=projection.configuration_state,
            authority_revision=endpoint.authority_revision,
            close_barrier=endpoint.close_barrier,
            created_at=endpoint.created_at,
            updated_at=endpoint.updated_at,
        )


class RuntimeWebRequestResponse(_ClosedModel):
    """Durable exposure request projection."""

    id: str
    requester_kind: RuntimeWebRequesterKind
    state: RuntimeWebRequestState
    revision: int = Field(ge=1)
    label: str | None
    decided_by_user_id: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuntimeWebCycleResponse(_ClosedModel):
    """Finite approved exposure cycle projection."""

    id: str
    request_id: str
    duration_seconds: int = Field(ge=300, le=28_800)
    duration_configuration_revision: int = Field(ge=1)
    approved_at: datetime
    expires_at: datetime
    close_barrier: int = Field(ge=0)
    ended_at: datetime | None
    end_reason: RuntimeWebCycleEndReason | None


class RuntimeWebServiceResponse(_ClosedModel):
    """Orthogonal endpoint, request, cycle, and active-state projection."""

    endpoint: RuntimeWebEndpointResponse
    current_request: RuntimeWebRequestResponse | None
    current_cycle: RuntimeWebCycleResponse | None
    active: bool
    duration_seconds: int = Field(ge=300, le=28_800)
    duration_configuration_revision: int = Field(ge=1)
    observed_at: datetime

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeWebServiceProjection,
    ) -> Self:
        request = projection.current_request
        cycle = projection.current_cycle
        return cls(
            endpoint=RuntimeWebEndpointResponse.convert_from(
                projection,
            ),
            current_request=(
                None
                if request is None
                else RuntimeWebRequestResponse(
                    id=request.id,
                    requester_kind=request.requester_kind,
                    state=request.state,
                    revision=request.revision,
                    label=request.label_snapshot,
                    decided_by_user_id=request.decided_by_user_id,
                    decided_at=request.decided_at,
                    created_at=request.created_at,
                    updated_at=request.updated_at,
                )
            ),
            current_cycle=(
                None
                if cycle is None
                else RuntimeWebCycleResponse(
                    id=cycle.id,
                    request_id=cycle.request_id,
                    duration_seconds=cycle.duration_seconds,
                    duration_configuration_revision=(
                        cycle.duration_configuration_revision
                    ),
                    approved_at=cycle.approved_at,
                    expires_at=cycle.expires_at,
                    close_barrier=cycle.close_barrier,
                    ended_at=cycle.ended_at,
                    end_reason=cycle.end_reason,
                )
            ),
            active=projection.active,
            duration_seconds=projection.duration_seconds,
            duration_configuration_revision=(
                projection.duration_configuration_revision
            ),
            observed_at=projection.observed_at,
        )


class RuntimeWebServiceListResponse(_ClosedModel):
    """Bounded service projection page."""

    items: list[RuntimeWebServiceResponse]
    total_count: int = Field(ge=0)

    @classmethod
    def convert_from(
        cls,
        page: RuntimeWebServicePage,
    ) -> Self:
        return cls(
            items=[RuntimeWebServiceResponse.convert_from(item) for item in page.items],
            total_count=page.total_count,
        )


class RuntimeWebPrepareRequest(_ClosedModel):
    """Idempotent endpoint preparation request."""

    label: str | None = Field(max_length=120)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebExposureRequest(_ClosedModel):
    """Idempotent asynchronous exposure request."""

    label: str | None = Field(max_length=120)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebApprovalRequest(_ClosedModel):
    """Revision- and displayed-duration-bound approval mutation."""

    expected_revision: int = Field(ge=1)
    duration_seconds: int = Field(ge=300, le=28_800)
    duration_configuration_revision: int = Field(ge=1)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebDirectCreateRequest(_ClosedModel):
    """Explicit direct-create confirmation using current displayed duration."""

    label: str | None = Field(max_length=120)
    duration_seconds: int = Field(ge=300, le=28_800)
    duration_configuration_revision: int = Field(ge=1)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebExpectedRevisionRequest(_ClosedModel):
    """Revision-fenced request control mutation."""

    expected_revision: int = Field(ge=1)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebCloseRequest(_ClosedModel):
    """Endpoint-revision-fenced exposure closure."""

    expected_endpoint_revision: int = Field(ge=0)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebActionErrorDetail(_ClosedModel):
    """Bounded Public API control error detail."""

    code: Literal[
        "not_found",
        "access_denied",
        "conflict",
        "quota_exceeded",
        "configuration_unavailable",
    ]
    scope: str | None


class RuntimeWebActionErrorResponse(_ClosedModel):
    """FastAPI envelope for a bounded Runtime Web control error."""

    detail: RuntimeWebActionErrorDetail


class RuntimeWebBrowserProfileRequest(_ClosedModel):
    """Trusted Main Web proof for the admitted browser profile."""

    browser_profile: str = Field(
        pattern=r"^chromium-[0-9]+$",
        min_length=10,
        max_length=32,
    )


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

    endpoint_id: str = Field(min_length=32, max_length=32)


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
    """One-use POST-body ticket for the exact endpoint."""

    ticket_secret: str = Field(min_length=32, max_length=128)
    endpoint_id: str = Field(min_length=32, max_length=32)
    expires_at: datetime
