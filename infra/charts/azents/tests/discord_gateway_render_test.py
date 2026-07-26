"""Discord Gateway Helm render contract tests."""

from scheduler_render_test import _helm_template


def test_discord_gateway_renders_by_default() -> None:
    """Every server deployment includes the dedicated Discord Gateway role."""
    rendered = _helm_template()

    assert "name: discord-gateway" in rendered
    assert "./bin/discordgatewayworker.sh" in rendered


def test_discord_gateway_renders_as_a_separate_worker_role() -> None:
    """The Gateway role has a distinct command and health port."""
    rendered = _helm_template()

    assert "name: discord-gateway" in rendered
    assert "./bin/discordgatewayworker.sh" in rendered
    assert 'value: "8013"' in rendered
