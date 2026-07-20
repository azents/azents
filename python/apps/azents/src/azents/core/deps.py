"""Common dependency injection."""

from typing import Annotated

from fastapi import Depends

from azents.core.crypto import CredentialCipher
from azents.utils.appctx import AppContext

from .config import (
    AuthConfig,
    Config,
    CredentialEncryptionConfig,
    EmailConfig,
    SystemBootstrapConfig,
)


def get_appctx() -> AppContext[Config]:
    """Placeholder dependency that returns AppContext.

    The actual AppContext is injected by dependency_overrides in app.py.
    """
    raise NotImplementedError("get_appctx was not provided")


def get_config(appctx: Annotated[AppContext[Config], Depends(get_appctx)]) -> Config:
    """Dependency that returns Config."""
    return appctx.config


def get_auth_config(config: Annotated[Config, Depends(get_config)]) -> AuthConfig:
    """AuthDependency that returns Config."""
    return config.auth


def get_system_bootstrap_config(
    config: Annotated[Config, Depends(get_config)],
) -> SystemBootstrapConfig:
    """Return initial system bootstrap configuration."""
    return config.system_bootstrap


def get_email_config(
    config: Annotated[Config, Depends(get_config)],
) -> EmailConfig | None:
    """EmailDependency that returns Config.

    Returns None when email_sender is not configured.
    """
    return config.email


def get_credential_encryption_config(
    config: Annotated[Config, Depends(get_config)],
) -> CredentialEncryptionConfig:
    """Return deployment-controlled credential encryption configuration."""
    return config.credential_encryption


def get_credential_cipher(
    config: Annotated[Config, Depends(get_config)],
) -> CredentialCipher:
    """Dependency that returns CredentialCipher."""
    return CredentialCipher(key=config.credential_encryption.key)
