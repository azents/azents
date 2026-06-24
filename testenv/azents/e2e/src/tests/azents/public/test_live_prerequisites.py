"""Live prerequisite snapshot E2E test."""

import json
from typing import Any

import pytest

from support.consts import PROJECT_ROOT

pytestmark = pytest.mark.live_external


def _snapshot_entries() -> dict[str, dict[str, Any]]:
    """live profile prerequisite snapshot entry t contract id t returnt."""
    snapshot_path = PROJECT_ROOT.parent / ".state" / "prerequisites" / "live.json"
    if not snapshot_path.exists():
        pytest.skip("Live prerequisite snapshot is missing")
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return {entry["contract_id"]: entry for entry in payload["entries"]}


def _ready_entry(contract_id: str) -> dict[str, Any]:
    """preparet prerequisite snapshot entry t returnt live E2E t skip t."""
    entry = _snapshot_entries().get(contract_id)
    if entry is None:
        pytest.skip(f"Live prerequisite is not present in snapshot: {contract_id}")
    assert entry is not None
    if entry["status"] != "ready":
        pytest.skip(f"Live prerequisite is not ready: {contract_id}")
    return entry


def test_bedrock_snapshot_is_ready_for_live_e2e() -> None:
    """Bedrock live E2E t prepare snapshot t t checkt."""
    entry = _ready_entry("bedrock-aws")
    assert entry["kind"] == "credential"
    assert all(check["status"] == "pass" for check in entry["checks"])


def test_browser_oauth_snapshot_is_ready_for_live_e2e() -> None:
    """Browser OAuth live E2E t prepare snapshot t t checkt."""
    entry = _ready_entry("browser-oauth")
    assert entry["kind"] == "prerequisite"
    assert all(check["status"] == "pass" for check in entry["checks"])
