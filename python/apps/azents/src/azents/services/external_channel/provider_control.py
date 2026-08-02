"""Immediate post-commit External Channel provider controls."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ExternalChannelProviderControlService:
    """Execute one process-local provider control after canonical commit."""

    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ]

    async def attempt(
        self,
        plan: ProviderEffectPlan,
    ) -> ProviderMutationOutcome | None:
        """Attempt one current provider control once without persistence or replay."""
        outcome = await self.action_service.execute_direct_control(plan)
        if outcome is not None and outcome.status in {"failed", "unknown"}:
            logger.warning(
                "External Channel provider control did not complete",
                extra={
                    "provider": plan.target.provider.value,
                    "operation": plan.target.operation.value,
                    "status": outcome.status,
                    "error_kind": outcome.error_kind,
                },
            )
        return outcome


def get_external_channel_provider_control_service(
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ],
) -> ExternalChannelProviderControlService:
    """Compose immediate provider-control execution."""
    return ExternalChannelProviderControlService(action_service=action_service)
