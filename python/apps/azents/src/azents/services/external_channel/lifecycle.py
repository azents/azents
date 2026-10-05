"""Post-commit External Channel lifecycle provider cleanup."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.services.external_channel.channel_action import ExternalChannelActionService


@dataclasses.dataclass
class ExternalChannelLifecycleService:
    """Attempt detached provider cleanup only after lifecycle persistence completes."""

    action_service: Annotated[
        ExternalChannelActionService, Depends(ExternalChannelActionService.create)
    ]

    async def consume_archive_cleanup(
        self,
        plans: Sequence[ProviderEffectPlan],
    ) -> int:
        """Attempt every captured archive cleanup once."""
        for plan in plans:
            await self.action_service.execute_terminal_control(plan)
        return len(plans)
