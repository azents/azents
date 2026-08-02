"""Tests for one-shot post-commit provider controls."""

from typing import cast
from unittest.mock import AsyncMock

import pytest

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
    ProviderOperationKey,
    ProviderTarget,
)


def _plan() -> ProviderEffectPlan:
    return ProviderEffectPlan(
        target=ProviderTarget(
            operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            binding_id=None,
            resource_id="resource-1",
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            app_mode=ExternalChannelAppMode.SINGLE,
            encrypted_credentials="encrypted",
            provider_tenant_id="tenant-1",
            capabilities=None,
            workspace_handle=None,
            agent_id=None,
            agent_session_id=None,
            agent_name=None,
            agent_avatar=None,
            request_payload={"control_kind": "setup_required"},
        ),
        operation_key=ProviderOperationKey.from_seed("control-1"),
    )


@pytest.mark.asyncio
async def test_attempt_delegates_exactly_once_without_drain() -> None:
    action_service = AsyncMock(spec=ExternalChannelActionService)
    action_service.execute_direct_control.return_value = ProviderMutationOutcome(
        status="delivered",
        provider_message_key=None,
        error_kind=None,
        error_summary=None,
    )
    service = ExternalChannelProviderControlService(
        action_service=cast(ExternalChannelActionService, action_service)
    )
    plan = _plan()

    result = await service.attempt(plan)

    assert result is not None
    assert result.status == "delivered"
    action_service.execute_direct_control.assert_awaited_once_with(plan)
