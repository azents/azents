"""Tests for the read-only External Channel ingress operator CLI."""

from typer.testing import CliRunner

from azents.cli.external_channel_ingress import app


def test_cli_exposes_only_read_only_status_command() -> None:
    """Operator CLI has no mutation or release command."""
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "status" in result.stdout
    assert "release" not in result.stdout
    assert "delete" not in result.stdout
