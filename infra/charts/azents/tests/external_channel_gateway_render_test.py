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


def test_external_channel_gateway_inherits_global_image_pull_secrets() -> None:
    """The gateway can pull the same private server image as other deployments."""
    rendered = _helm_template(
        "global.imagePullSecrets[0].name=ghcr-pull-secret",
    )
    start = rendered.index(
        "kind: Deployment\nmetadata:\n  name: external-channel-gateway"
    )
    gateway = rendered[start : rendered.index("\n---\n", start)]

    assert "imagePullSecrets:\n        - name: ghcr-pull-secret" in gateway
