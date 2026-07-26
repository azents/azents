"""Discord Gateway Helm render contract tests."""

from scheduler_render_test import _helm_template


def test_discord_gateway_is_opt_in() -> None:
    """Default values do not create a Discord Gateway Deployment."""
    rendered = _helm_template()

    assert "./bin/discordgatewayworker.sh" not in rendered


def test_discord_gateway_renders_as_a_separate_worker_role() -> None:
    """The opt-in Gateway role has a distinct command and health port."""
    rendered = _helm_template("server.discordGateway.enabled=true")

    assert "name: discord-gateway" in rendered
    assert "./bin/discordgatewayworker.sh" in rendered
    assert 'value: "8013"' in rendered
