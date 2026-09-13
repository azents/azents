"""Runtime Web endpoint URL resolution contract."""

from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeWebEndpointUrlResolver(Protocol):
    """Resolve a stable hostname key to its configured public URL."""

    def resolve(self, hostname_key: str) -> str | None:
        """Return a configured public URL or None when unavailable."""
        ...


class RuntimeWebEndpointUrlSettings(BaseSettings):
    """Public API settings used to expose stable Runtime Web endpoint URLs."""

    model_config = SettingsConfigDict(
        env_prefix="AZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    runtime_web_gateway_enabled: bool = False
    runtime_web_gateway_service_suffix: str | None = Field(
        default=None,
        min_length=1,
    )


@dataclass(frozen=True)
class SettingsRuntimeWebEndpointUrlResolver:
    """Resolve endpoint URLs from the deployment's Gateway configuration."""

    enabled: bool
    service_suffix: str | None

    def resolve(self, hostname_key: str) -> str | None:
        """Return the stable HTTPS root URL when the Gateway is configured."""
        if not self.enabled or self.service_suffix is None:
            return None
        return f"https://{hostname_key}.{self.service_suffix}/"


def get_runtime_web_endpoint_url_settings() -> RuntimeWebEndpointUrlSettings:
    """Load Runtime Web endpoint URL settings from the process environment."""
    return RuntimeWebEndpointUrlSettings()


def get_runtime_web_endpoint_url_resolver(
    settings: Annotated[
        RuntimeWebEndpointUrlSettings,
        Depends(get_runtime_web_endpoint_url_settings),
    ],
) -> RuntimeWebEndpointUrlResolver:
    """Return the configured Runtime Web URL resolver contract."""
    return SettingsRuntimeWebEndpointUrlResolver(
        enabled=settings.runtime_web_gateway_enabled,
        service_suffix=settings.runtime_web_gateway_service_suffix,
    )
