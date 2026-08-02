"""External Channel Gateway Helm render contract tests."""

from scheduler_render_test import _helm_template


def test_external_channel_gateway_renders_by_default() -> None:
    """Every server deployment includes the persistent provider ingress role."""
    rendered = _helm_template()

    assert "name: external-channel-gateway" in rendered
    assert "./bin/externalchannelgateway.sh" in rendered


def test_external_channel_gateway_replaces_discord_specific_role() -> None:
    """The chart exposes only the provider-neutral gateway identity."""
    rendered = _helm_template()

    assert 'app.kubernetes.io/component: "external-channel-gateway"' in rendered
    assert 'value: "8013"' in rendered
    assert "name: discord-gateway" not in rendered
    assert "./bin/discordgatewayworker.sh" not in rendered


def test_external_channel_participation_rollout_gate_is_deployment_controlled() -> None:
    """The shared server ConfigMap retains a disabled, overridable rollout gate."""
    disabled = _helm_template()
    enabled = _helm_template(
        "server.env.AZ_EXTERNAL_CHANNEL_PARTICIPATION_ENABLED=true"
    )

    assert 'AZ_EXTERNAL_CHANNEL_PARTICIPATION_ENABLED: "false"' in disabled
    assert 'AZ_EXTERNAL_CHANNEL_PARTICIPATION_ENABLED: "true"' in enabled
