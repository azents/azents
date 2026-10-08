"""Pure dependency factories for System Settings projections."""

import os
from typing import Annotated

from fastapi import Depends

from azents.core.config import CredentialEncryptionConfig
from azents.core.deps import get_credential_encryption_config
from azents.core.system_setting import (
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
)


def get_system_setting_environment() -> SystemSettingEnvironment:
    """Return the process environment overlay view."""
    return SystemSettingEnvironment(values=os.environ)


def get_system_setting_generation_hasher(
    config: Annotated[
        CredentialEncryptionConfig,
        Depends(get_credential_encryption_config),
    ],
) -> SystemSettingGenerationHasher:
    """Return the effective-generation hasher rooted in deployment material."""
    return SystemSettingGenerationHasher(config.key)
