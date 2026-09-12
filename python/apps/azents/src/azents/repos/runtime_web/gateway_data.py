"""Typed Runtime Web Gateway authentication and admission data."""

import datetime

from pydantic import BaseModel, Field

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.runtime_web.data import (
    RuntimeWebCycle,
    RuntimeWebEndpoint,
    RuntimeWebRequest,
)


class RuntimeWebDesiredConfiguration(BaseModel):
    """Deployment configuration proposed to the monotonic DB authority."""

    enabled: bool
    mode: RuntimeWebAuthMode
    configuration_version: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)
    active_duration_seconds: int = Field(ge=300, le=28_800)


class RuntimeWebGatewayIdentity(BaseModel):
    """Validated server-side Gateway identity."""

    id: str
    user_id: str
    auth_session_id: str
    mode: RuntimeWebAuthMode
    epoch: int
    browser_profile: str
    issued_at: datetime.datetime
    expires_at: datetime.datetime


class RuntimeWebIssuedSecret(BaseModel):
    """Opaque secret returned only to a trusted cookie-setting surface."""

    secret: str
    expires_at: datetime.datetime


class RuntimeWebRedeemedIdentity(RuntimeWebIssuedSecret):
    """Identity plus the ticket-bound endpoint destination."""

    endpoint_id: str


class RuntimeWebAuthBinding(BaseModel):
    """One separate-domain browser binding."""

    id: str
    initiation_id: str
    user_id: str
    auth_session_id: str
    endpoint_id: str
    epoch: int
    expires_at: datetime.datetime
    broker_bound: bool
    settled: bool


class RuntimeWebIssuedBinding(BaseModel):
    """Main-origin binding secret and public initiation identifier."""

    binding: RuntimeWebAuthBinding
    main_binding_secret: str


class RuntimeWebBrokerBinding(BaseModel):
    """Broker-origin binding secret created for an initiation."""

    binding: RuntimeWebAuthBinding
    broker_binding_secret: str


class RuntimeWebIssuedTicket(BaseModel):
    """Thirty-second one-use broker redemption ticket."""

    ticket_secret: str
    endpoint_id: str
    expires_at: datetime.datetime


class RuntimeWebGatewayAuthority(BaseModel):
    """Current endpoint, approval, Runtime, and caller authority."""

    identity: RuntimeWebGatewayIdentity
    endpoint: RuntimeWebEndpoint
    request: RuntimeWebRequest | None
    cycle: RuntimeWebCycle | None
    runtime_id: str | None
    desired_generation: int | None
    runner_generation: int | None
    active: bool
    runtime_ready: bool


class RuntimeWebAdmissionLimits(BaseModel):
    """Shared connection limits for one transport kind."""

    endpoint: int = Field(ge=1)
    user: int = Field(ge=1)
    agent: int = Field(ge=1)
