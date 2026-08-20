"""External Channel test data factories."""

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderOperationKey,
    ProviderTarget,
)


def make_provider_effect_plan(
    seed: str = "test-provider-effect",
) -> ProviderEffectPlan:
    """Build one safe process-local provider plan for orchestration tests."""
    return ProviderEffectPlan(
        target=ProviderTarget(
            operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            binding_id="binding-1",
            resource_id="resource-1",
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            app_mode=ExternalChannelAppMode.SINGLE,
            encrypted_credentials="encrypted",
            provider_tenant_id="tenant-1",
            capabilities=None,
            provider_configuration=None,
            workspace_handle="workspace",
            agent_id="agent-1",
            agent_session_id="session-1",
            agent_name="Agent",
            agent_avatar=None,
            request_payload={"control_kind": "test"},
        ),
        operation_key=ProviderOperationKey.from_seed(seed),
    )
