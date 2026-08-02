"""Process-local External Channel provider effect contract tests."""

import pytest

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectOutcome,
    ProviderEffectPlan,
    ProviderOperationKey,
    ProviderTarget,
)


def test_operation_key_is_bounded_deterministic_and_opaque() -> None:
    """The live duplicate fence does not retain or expose its source identity."""
    first = ProviderOperationKey.from_seed("delivery-1")
    second = ProviderOperationKey.from_seed("delivery-1")

    assert first == second
    assert len(first.value) == 25
    assert first.value == "0b220df1969115139ffebb337"
    assert "delivery-1" not in repr(first)
    assert first.value not in repr(first)


def test_operation_key_rejects_empty_or_unbounded_values() -> None:
    """Provider operation keys remain valid for bounded provider nonce fields."""
    with pytest.raises(ValueError):
        ProviderOperationKey.from_seed("")
    with pytest.raises(ValueError):
        ProviderOperationKey(value="x" * 26)


def test_provider_plan_and_effect_outcome_exclude_durable_identifiers() -> None:
    """Provider-facing and Tool-facing contracts contain no delivery identity."""
    target = ProviderTarget(
        operation=ExternalChannelDeliveryOperation.REPLY,
        binding_id="binding-1",
        resource_id="resource-1",
        connection_id="connection-1",
        provider=ExternalChannelProvider.DISCORD,
        app_mode=ExternalChannelAppMode.MULTI,
        encrypted_credentials="ciphertext",
        provider_tenant_id="111",
        capabilities=None,
        workspace_handle="workspace",
        agent_id="agent-1",
        agent_session_id="session-1",
        agent_name="Agent",
        agent_avatar=None,
        request_payload={"channel_id": "333"},
    )
    plan = ProviderEffectPlan(
        target=target,
        operation_key=ProviderOperationKey.from_seed("delivery-1"),
    )
    outcome = ProviderEffectOutcome(
        operation=ExternalChannelDeliveryOperation.REPLY,
        part=0,
        status="delivered",
        reason=None,
        detail=None,
    )

    assert plan.target == target
    assert outcome.status == "delivered"
    assert "delivery_attempt" not in ProviderTarget.__dataclass_fields__
    assert "delivery_attempt" not in ProviderEffectPlan.__dataclass_fields__
    assert "provider_message_key" not in ProviderEffectOutcome.__dataclass_fields__
