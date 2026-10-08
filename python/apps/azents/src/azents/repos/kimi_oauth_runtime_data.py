"""Typed Kimi runtime persistence inputs and outcomes."""

import datetime
from dataclasses import dataclass
from typing import NamedTuple

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets


class KimiOAuthCredentials(NamedTuple):
    """Typed credentials decoded from one detached integration."""

    secrets: KimiOAuthSecrets
    config: KimiOAuthConfig


@dataclass(frozen=True)
class KimiOAuthRefreshTokens:
    """Provider refresh values needed by the database operation."""

    access_token: str
    refresh_token: str
    expires_at: datetime.datetime


@dataclass(frozen=True)
class KimiRuntimeInvalidCredentials:
    """The original integration did not contain typed Kimi credentials."""


@dataclass(frozen=True)
class KimiRuntimeIntegrationMissing:
    """Persistence could not find or update the original integration."""


def kimi_oauth_credentials(
    integration: LLMProviderIntegrationWithSecrets,
) -> KimiOAuthCredentials | None:
    """Read the exact existing typed-secret and typed-config predicate."""
    if not isinstance(integration.secrets, KimiOAuthSecrets) or not isinstance(
        integration.config, KimiOAuthConfig
    ):
        return None
    return KimiOAuthCredentials(integration.secrets, integration.config)
