"""Strict-network control-plane evidence contract tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from support.strict_network_control_plane import (
    ControlPlaneEvidence,
    load_control_plane_evidence,
)


def _evidence_payload() -> dict[str, object]:
    """Return one complete secret-free control-plane evidence object."""
    return {
        "classification": "control_plane_only",
        "event": "command_completed",
        "provider_id": "system-kubernetes-e2e",
        "command_type": "start",
        "runtime_id": "runtime-1",
        "network_mode": "proxy_required",
        "configuration_sequence": 3,
        "desired_generation": 4,
        "digest": "a" * 64,
        "provider_acknowledgement": True,
        "runner_process_started": True,
        "recorded_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC).isoformat(),
    }


def test_control_plane_evidence_round_trips_without_packet_authority(
    tmp_path: Path,
) -> None:
    """The artifact records only bounded control-plane transitions."""
    path = tmp_path / "evidence.jsonl"
    path.write_text(json.dumps(_evidence_payload()) + "\n", encoding="utf-8")

    evidence = load_control_plane_evidence(path)

    assert len(evidence) == 1
    assert evidence[0].classification == "control_plane_only"
    assert evidence[0].network_mode == "proxy_required"
    assert set(evidence[0].model_dump()) == {
        "classification",
        "event",
        "provider_id",
        "command_type",
        "runtime_id",
        "network_mode",
        "configuration_sequence",
        "desired_generation",
        "digest",
        "provider_acknowledgement",
        "runner_process_started",
        "recorded_at",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("packet_enforced", True),
        ("probe_outcome", "denied"),
        ("endpoint", "https://example.com"),
        ("credential", "secret"),
        ("kubeconfig", "secret"),
        ("ca_pem", "certificate"),
    ],
)
def test_control_plane_evidence_rejects_packet_or_secret_fields(
    field: str,
    value: object,
) -> None:
    """Deterministic artifacts cannot expand into packet or secret evidence."""
    payload = _evidence_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ControlPlaneEvidence.model_validate(payload)


def test_control_plane_evidence_rejects_packet_classification() -> None:
    """The simulator cannot present its result as packet enforcement."""
    payload = _evidence_payload()
    payload["classification"] = "packet_enforcement"

    with pytest.raises(ValidationError, match="control_plane_only"):
        ControlPlaneEvidence.model_validate(payload)
