"""Typed Runtime Web Gateway authentication and admission data."""

import datetime

from pydantic import BaseModel, Field

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.runtime_web.data import RuntimeWebServiceRecord


class RuntimeWebDesiredConfiguration(BaseModel):
    """Deployment configuration proposed to the shared DB authority."""

    enabled: bool
    mode: RuntimeWebAuthMode
    fingerprint: str = Field(min_length=64, max_length=64)


class RuntimeWebGatewayIdentity(BaseModel):
    """Validated server-side Gateway identity."""

    id: str
    user_id: str
    auth_session_id: str
    mode: RuntimeWebAuthMode
    issued_at: datetime.datetime
    expires_at: datetime.datetime


class RuntimeWebIssuedSecret(BaseModel):
    """Opaque secret returned only to a trusted cookie-setting surface."""

    secret: str
    expires_at: datetime.datetime


class RuntimeWebRedeemedIdentity(RuntimeWebIssuedSecret):
    """Identity plus the ticket-bound service destination."""

    service_id: str


class RuntimeWebAuthBinding(BaseModel):
    """One separate-domain browser binding."""

    id: str
    initiation_id: str
    user_id: str
    auth_session_id: str
    service_id: str
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
    service_id: str
    expires_at: datetime.datetime


class RuntimeWebGatewayAuthority(BaseModel):
    """Current service, Runtime, and caller authority."""

    identity: RuntimeWebGatewayIdentity
    service: RuntimeWebServiceRecord
    runtime_id: str
    desired_generation: int
    runner_generation: int
    exposure_deadline_at: datetime.datetime
