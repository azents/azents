"""Resolve the system-owned Historical Memory execution policy."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.system_setting import SystemSettingSection
from azents.services.system_setting.service import SystemSettingsService


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryExecutionPolicyService:
    system_settings: Annotated[SystemSettingsService, Depends(SystemSettingsService)]

    async def resolve(self) -> HistoricalMemoryExecutionConfig:
        setting = await self.system_settings.resolve(
            SystemSettingSection.HISTORICAL_MEMORY_EXECUTION
        )
        if not isinstance(setting.config, HistoricalMemoryExecutionConfig):
            raise TypeError("Unexpected Historical Memory execution settings model.")
        return setting.config
