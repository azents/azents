"""Reference Docker Compose persistence contract tests."""

from pathlib import Path

_COMPOSE = Path(__file__).resolve().parents[4] / "docker-compose.azents.yaml"


def test_reference_valkey_is_explicitly_ephemeral() -> None:
    """Local Valkey disables persistence and has no durable data volume."""
    compose = _COMPOSE.read_text()

    assert 'command: ["valkey-server", "--save", "", "--appendonly", "no"]' in compose
    assert "valkeydata" not in compose
