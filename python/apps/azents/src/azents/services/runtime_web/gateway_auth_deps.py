"""Dependency composition for Runtime Web Gateway authentication."""

import datetime
from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_web.gateway_data import RuntimeWebDesiredConfiguration
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime_web_gateway.settings import runtime_web_security_fingerprint
from azents.services.runtime_web.gateway_auth import (
    RuntimeWebGatewayAuthService,
)


class RuntimeWebGatewayAuthSettings(BaseSettings):
    """Public API settings shared with the Gateway deployment."""

    model_config = SettingsConfigDict(
        env_prefix="AZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    runtime_web_gateway_identity_lifetime_seconds: int = Field(
        default=1_800,
        ge=60,
        le=3_600,
    )
    runtime_web_gateway_enabled: bool = False
    runtime_web_gateway_auth_mode: RuntimeWebAuthMode = RuntimeWebAuthMode.SHARED_COOKIE
    runtime_web_gateway_auth_configuration_version: int = Field(default=1, ge=1)
    runtime_web_gateway_main_web_origin: str | None = None
    runtime_web_gateway_broker_origin: str | None = None
    runtime_web_gateway_service_suffix: str | None = None
    runtime_web_gateway_cookie_domain: str | None = None
    runtime_web_gateway_identity_cookie_name: str = "__Http-Azents-Runtime-Web"
    runtime_web_gateway_active_duration_seconds: int = Field(
        default=3_600,
        ge=300,
        le=28_800,
    )
    runtime_web_gateway_chromium_min_version: int = Field(default=152, ge=1)
    runtime_web_gateway_chromium_max_version: int = Field(default=152, ge=1)


def get_runtime_web_gateway_auth_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    repository: Annotated[
        RuntimeWebGatewayRepository,
        Depends(RuntimeWebGatewayRepository),
    ],
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ],
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ],
) -> RuntimeWebGatewayAuthService:
    """Compose the trusted Public API authentication service."""
    settings = RuntimeWebGatewayAuthSettings()
    desired = RuntimeWebDesiredConfiguration(
        enabled=settings.runtime_web_gateway_enabled,
        mode=settings.runtime_web_gateway_auth_mode,
        configuration_version=(settings.runtime_web_gateway_auth_configuration_version),
        fingerprint=runtime_web_security_fingerprint(
            enabled=settings.runtime_web_gateway_enabled,
            mode=settings.runtime_web_gateway_auth_mode,
            main_web_origin=settings.runtime_web_gateway_main_web_origin,
            broker_origin=settings.runtime_web_gateway_broker_origin,
            service_suffix=settings.runtime_web_gateway_service_suffix,
            cookie_domain=settings.runtime_web_gateway_cookie_domain,
            identity_cookie_name=settings.runtime_web_gateway_identity_cookie_name,
            chromium_min_version=(settings.runtime_web_gateway_chromium_min_version),
            chromium_max_version=(settings.runtime_web_gateway_chromium_max_version),
        ),
        active_duration_seconds=(settings.runtime_web_gateway_active_duration_seconds),
    )
    return RuntimeWebGatewayAuthService(
        session_manager=session_manager,
        repository=repository,
        agent_session_repository=agent_session_repository,
        workspace_user_repository=workspace_user_repository,
        identity_lifetime=datetime.timedelta(
            seconds=settings.runtime_web_gateway_identity_lifetime_seconds
        ),
        desired_configuration=desired,
        chromium_min_version=settings.runtime_web_gateway_chromium_min_version,
        chromium_max_version=settings.runtime_web_gateway_chromium_max_version,
    )
